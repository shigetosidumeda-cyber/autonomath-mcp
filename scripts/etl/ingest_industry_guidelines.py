"""Ingest sector guidelines from 10 major Japanese ministries.

Coverage targets (primary sources only):
    * env.go.jp   — 環境省
    * maff.go.jp  — 農林水産省
    * mhlw.go.jp  — 厚生労働省
    * meti.go.jp  — 経済産業省
    * mlit.go.jp  — 国土交通省
    * mext.go.jp  — 文部科学省
    * mof.go.jp   — 財務省
    * mic.go.jp   — 総務省
    * moj.go.jp   — 法務省
    * mod.go.jp   — 防衛省

Each ministry's official guideline pages are walked via its RSS feed or
sitemap. NO aggregator URLs (banned hosts list mirrors
scripts/ingest_external_data.BANNED_SOURCE_HOSTS).

Industry mapping = JSIC major (19 majors A-T). Mapping is heuristic:
ministry → default JSIC + keyword fence override.

Strategy:
    1. For each ministry, fetch the RSS index (canonical) or fall back to
       the sitemap.xml index.
    2. For each <item> / <url>, dedupe by URL + extract title + body
       snippet + dates.
    3. Insert into am_industry_guidelines with guideline_id =
       'GL-' + sha256(ministry + '|' + title)[:10].

CLAUDE.md constraints:
    * NO LLM API — HTML/XML/RSS only.
    * No aggregator URLs.
    * Idempotent — re-runs safe.
    * License = 'gov_standard' on every row.

Usage:
    python scripts/etl/ingest_industry_guidelines.py --dry-run
    python scripts/etl/ingest_industry_guidelines.py \\
        --ministries env,maff,mhlw --max-per-ministry 20
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

try:
    import certifi

    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "autonomath.db"

# Ministry → RSS / sitemap discovery roots.
# All entries are PRIMARY (ministry domain only) — no aggregator.
MINISTRY_FEEDS: dict[str, list[tuple[str, str]]] = {
    # (kind, url) — kind is 'rss' | 'sitemap' | 'html'
    "env": [
        ("rss", "https://www.env.go.jp/rss/all.rdf"),
        ("html", "https://www.env.go.jp/policy/guideline.html"),
    ],
    "maff": [
        ("rss", "https://www.maff.go.jp/index.rdf"),
        ("html", "https://www.maff.go.jp/j/guide/"),
    ],
    "mhlw": [
        ("rss", "https://www.mhlw.go.jp/stf/news.rdf"),
        ("html", "https://www.mhlw.go.jp/stf/seisakunitsuite/index.html"),
    ],
    "meti": [
        ("rss", "https://www.meti.go.jp/rss/topics.rdf"),
        ("html", "https://www.meti.go.jp/policy/"),
    ],
    "mlit": [
        ("rss", "https://www.mlit.go.jp/index.rdf"),
        ("html", "https://www.mlit.go.jp/page/kanbo01_hy_001247.html"),
    ],
    "mext": [
        ("rss", "https://www.mext.go.jp/rss/index.xml"),
    ],
    "mof": [
        ("rss", "https://www.mof.go.jp/index.rdf"),
    ],
    "mic": [
        ("rss", "https://www.soumu.go.jp/news.rdf"),
    ],
    "moj": [
        ("html", "https://www.moj.go.jp/"),
    ],
    "mod": [
        ("html", "https://www.mod.go.jp/"),
    ],
}

# Ministry → default JSIC major (heuristic) when title gives no other hint.
MINISTRY_DEFAULT_JSIC: dict[str, tuple[str, str]] = {
    "env": ("E", "製造業"),     # 環境関連 fab/manuf
    "maff": ("A", "農業,林業"),
    "mhlw": ("P", "医療,福祉"),
    "meti": ("E", "製造業"),
    "mlit": ("F", "建設業"),
    "mext": ("O", "教育,学習支援業"),
    "mof": ("K", "不動産業,物品賃貸業"),
    "mic": ("H", "運輸業,郵便業"),
    "moj": ("Q", "複合サービス事業"),
    "mod": ("R", "サービス業(他に分類されないもの)"),
}

# JSIC keyword override — checks title to remap when ministry default
# is wrong (e.g. METI publishes 建設業 guidelines too).
JSIC_KEYWORD_MAP: list[tuple[str, str, str]] = [
    ("建設", "F", "建設業"),
    ("製造", "E", "製造業"),
    ("農業", "A", "農業,林業"),
    ("林業", "A", "農業,林業"),
    ("漁業", "B", "漁業"),
    ("医療", "P", "医療,福祉"),
    ("介護", "P", "医療,福祉"),
    ("教育", "O", "教育,学習支援業"),
    ("運輸", "H", "運輸業,郵便業"),
    ("情報通信", "G", "情報通信業"),
    ("IT", "G", "情報通信業"),
    ("不動産", "K", "不動産業,物品賃貸業"),
    ("飲食", "M", "宿泊業,飲食サービス業"),
    ("宿泊", "M", "宿泊業,飲食サービス業"),
    ("小売", "I", "卸売業,小売業"),
    ("卸売", "I", "卸売業,小売業"),
    ("金融", "J", "金融業,保険業"),
    ("保険", "J", "金融業,保険業"),
    ("電気", "F", "建設業"),  # 電気工事
    ("ガス", "F", "建設業"),
]

BANNED_SOURCE_HOSTS = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "hojo-navi",
    "mirai-joho",
)

UA = "AutonoMath/0.3.5 jpcite-etl (+https://bookyou.net; info@bookyou.net)"
DEFAULT_DELAY = 2.0
DEFAULT_TIMEOUT = 30


def is_banned_url(url: str) -> bool:
    if not url:
        return True
    low = url.lower()
    return any(h in low for h in BANNED_SOURCE_HOSTS)


def compute_guideline_id(ministry: str, title: str) -> str:
    key = f"{ministry}|{title}".encode("utf-8")
    return "GL-" + hashlib.sha256(key).hexdigest()[:10]


def classify_jsic(ministry: str, title: str) -> tuple[str, str]:
    for kw, code, label in JSIC_KEYWORD_MAP:
        if kw in (title or ""):
            return code, label
    return MINISTRY_DEFAULT_JSIC.get(ministry, ("R", "サービス業(他に分類されないもの)"))


def fetch(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    if is_banned_url(url):
        raise ValueError(f"banned source: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        body = resp.read()
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return body.decode("shift_jis", errors="replace")


_ISO_DATE_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")


def parse_iso_date(s: str | None) -> str | None:
    if not s:
        return None
    m = _ISO_DATE_RE.search(s)
    if not m:
        return None
    y, mo, d = m.groups()
    try:
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    except ValueError:
        return None


def parse_rss(body: str, ministry: str, base_url: str, limit: int) -> list[dict[str, Any]]:
    """Parse RSS 2.0 / RDF feed and extract items."""
    records: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return records
    ns = {
        "rss": "http://purl.org/rss/1.0/",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "dc": "http://purl.org/dc/elements/1.1/",
    }
    # Try RDF Site Summary / RSS 1.0 first
    items = root.findall(".//rss:item", ns)
    if not items:
        items = root.findall(".//item")  # RSS 2.0 plain
    count = 0
    for item in items:
        if count >= limit:
            break
        title_el = item.find("rss:title", ns)
        if title_el is None:
            title_el = item.find("title")
        link_el = item.find("rss:link", ns)
        if link_el is None:
            link_el = item.find("link")
        date_el = item.find("dc:date", ns)
        if date_el is None:
            date_el = item.find("pubDate")
        desc_el = item.find("rss:description", ns)
        if desc_el is None:
            desc_el = item.find("description")
        title = (title_el.text if title_el is not None else "") or ""
        link = (link_el.text if link_el is not None else "") or ""
        date_s = (date_el.text if date_el is not None else "") or ""
        body_s = (desc_el.text if desc_el is not None else "") or ""
        title = title.strip()
        link = link.strip()
        if not title or not link:
            continue
        if is_banned_url(link):
            continue
        # Filter: only retain entries that look like guideline / 指針 / 通達 /
        # 通知 / 公表. RSS items mix news headlines (not relevant) too.
        if not any(k in title for k in (
            "ガイドライン", "指針", "通達", "通知", "告示", "公表",
            "業種", "事業者", "事業",
        )):
            continue
        records.append(
            {
                "ministry": ministry,
                "title": title[:300],
                "body": body_s[:2000],
                "source_url": link,
                "full_text_url": link,
                "pdf_url": link if link.endswith(".pdf") else None,
                "issued_date": parse_iso_date(date_s),
                "last_revised": parse_iso_date(date_s),
                "document_type": "guideline" if "ガイドライン" in title else "notice",
            }
        )
        count += 1
    return records


def parse_html_index(body: str, ministry: str, base_url: str, limit: int) -> list[dict[str, Any]]:
    """Coarse HTML index parser — extracts <a href="..."> with anchor text."""
    records: list[dict[str, Any]] = []
    # very naive — production parser would use BeautifulSoup. Stays
    # std-lib only so dry-run works on a fresh image.
    pattern = re.compile(r'<a\s+[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', re.IGNORECASE)
    count = 0
    for m in pattern.finditer(body):
        if count >= limit:
            break
        href = m.group(1)
        title = m.group(2).strip()
        if not href or not title:
            continue
        if href.startswith("/"):
            href = urllib.parse.urljoin(base_url, href)
        if is_banned_url(href):
            continue
        if not any(k in title for k in (
            "ガイドライン", "指針", "通達", "通知", "告示", "公表",
        )):
            continue
        records.append(
            {
                "ministry": ministry,
                "title": title[:300],
                "body": "",
                "source_url": href,
                "full_text_url": href,
                "pdf_url": href if href.endswith(".pdf") else None,
                "issued_date": None,
                "last_revised": None,
                "document_type": "guideline",
            }
        )
        count += 1
    return records


def fetch_ministry_records(
    ministry: str, max_per_ministry: int
) -> list[dict[str, Any]]:
    feeds = MINISTRY_FEEDS.get(ministry, [])
    out: list[dict[str, Any]] = []
    for kind, url in feeds:
        if len(out) >= max_per_ministry:
            break
        try:
            body = fetch(url)
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            print(f"[{ministry}] {kind} fetch failed: {exc}", file=sys.stderr)
            continue
        remaining = max_per_ministry - len(out)
        if kind == "rss":
            out.extend(parse_rss(body, ministry, url, remaining))
        else:
            out.extend(parse_html_index(body, ministry, url, remaining))
        time.sleep(DEFAULT_DELAY)
    # Dedupe by source_url within this ministry
    seen: set[str] = set()
    deduped = []
    for r in out:
        if r["source_url"] in seen:
            continue
        seen.add(r["source_url"])
        deduped.append(r)
    return deduped[:max_per_ministry]


def upsert(conn: sqlite3.Connection, rec: dict[str, Any], dry_run: bool = False) -> bool:
    gl_id = compute_guideline_id(rec["ministry"], rec["title"])
    jsic_code, jsic_label = classify_jsic(rec["ministry"], rec["title"])
    now = datetime.now(UTC).isoformat()
    if dry_run:
        print(
            f"[DRY] would upsert ministry={rec['ministry']} "
            f"jsic={jsic_code} title={rec['title'][:60]}... id={gl_id}"
        )
        return True
    if is_banned_url(rec.get("source_url") or ""):
        return False
    conn.execute(
        """
        INSERT OR IGNORE INTO am_industry_guidelines (
            guideline_id, ministry, industry_jsic_major, industry_jsic_label,
            title, body, full_text_url, pdf_url, issued_date, last_revised,
            document_type, source_url, license, ingested_at, last_verified
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'gov_standard', ?, ?)
        """,
        (
            gl_id,
            rec["ministry"],
            jsic_code,
            jsic_label,
            rec["title"],
            rec.get("body"),
            rec.get("full_text_url"),
            rec.get("pdf_url"),
            rec.get("issued_date"),
            rec.get("last_revised"),
            rec.get("document_type", "guideline"),
            rec["source_url"],
            now,
            now,
        ),
    )
    return True


def run(args: argparse.Namespace) -> int:
    print(f"[start] db={args.db_path} ministries={args.ministries} max={args.max_per_ministry} dry_run={args.dry_run}")
    if not args.dry_run and not args.db_path.exists():
        print(f"[error] db missing: {args.db_path}", file=sys.stderr)
        return 2

    selected = [m.strip() for m in args.ministries.split(",") if m.strip()]
    if "all" in selected:
        selected = list(MINISTRY_FEEDS.keys())
    all_records: list[dict[str, Any]] = []
    for ministry in selected:
        recs = fetch_ministry_records(ministry, args.max_per_ministry)
        print(f"[{ministry}] {len(recs)} records")
        all_records.extend(recs)

    print(f"[fetch] total {len(all_records)} records")
    if args.dry_run:
        for rec in all_records[:30]:
            upsert(None, rec, dry_run=True)  # type: ignore[arg-type]
        print(f"[dry-run] done — would write up to {len(all_records)} rows")
        return 0

    written = 0
    with sqlite3.connect(args.db_path) as conn:
        for rec in all_records:
            try:
                if upsert(conn, rec):
                    written += 1
            except sqlite3.Error as exc:
                print(f"[skip] {exc}", file=sys.stderr)
        conn.commit()
    print(f"[done] wrote {written}/{len(all_records)} rows")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ingest industry guidelines from ministries")
    p.add_argument("--db-path", type=Path, default=DB_PATH)
    p.add_argument("--ministries", default="all", help="comma list of ministry codes or 'all'")
    p.add_argument("--max-per-ministry", type=int, default=10)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
