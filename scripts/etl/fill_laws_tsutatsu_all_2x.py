#!/usr/bin/env python3
"""Wave 43.1.6 — 各省庁 通達 (15 ministry) all-government ingest into
`am_law_tsutatsu_all` (migration 253).

Target: +6,800 rows (avg 450 rows/ministry × 15 ministry).

CLAUDE.md constraints: NO LLM API, no aggregator URLs, idempotent.
License = 'gov_standard'.

Usage:
    python scripts/etl/fill_laws_tsutatsu_all_2x.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
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
    from scripts.etl._playwright_helper import fetch_with_fallback_sync
except ImportError:
    fetch_with_fallback_sync = None  # type: ignore[assignment]

try:
    import certifi

    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

LOG = logging.getLogger("fill_laws_tsutatsu_all_2x")

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "autonomath.db"

UA = "jpcite-tsutatsu-bot/1.0 (+https://bookyou.net; operator=info@bookyou.net)"
DEFAULT_DELAY = 2.0
DEFAULT_TIMEOUT = 30

BANNED_SOURCE_HOSTS = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "hojo-navi",
    "mirai-joho",
    "subsidy-portal",
)

AGENCY_SEEDS: dict[str, dict[str, Any]] = {
    "nta": {
        "name": "国税庁",
        "default_jsic": "K",
        "seeds": [
            ("html_index", "https://www.nta.go.jp/law/tsutatsu/index.htm"),
            ("html_index", "https://www.nta.go.jp/law/tsutatsu/kobetsu/hojin/index.htm"),
            ("html_index", "https://www.nta.go.jp/law/tsutatsu/kobetsu/shotoku/index.htm"),
            ("html_index", "https://www.nta.go.jp/law/tsutatsu/kobetsu/shohi/index.htm"),
            ("html_index", "https://www.nta.go.jp/law/tsutatsu/kobetsu/sozoku/index.htm"),
        ],
    },
    "meti": {
        "name": "経済産業省",
        "default_jsic": "E",
        "seeds": [
            ("rss", "https://www.meti.go.jp/rss/topics.rdf"),
            ("html_index", "https://www.meti.go.jp/policy/economy/koukai/index.html"),
            ("html_index", "https://www.meti.go.jp/feedback/data/g05r-att/g05r-att-tsutatsu.html"),
        ],
    },
    "mhlw": {
        "name": "厚生労働省",
        "default_jsic": "P",
        "seeds": [
            ("rss", "https://www.mhlw.go.jp/stf/news.rdf"),
            ("html_index", "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/index.html"),
            ("html_index", "https://www.mhlw.go.jp/web/t_doc"),
        ],
    },
    "env": {
        "name": "環境省",
        "default_jsic": "E",
        "seeds": [
            ("rss", "https://www.env.go.jp/rss/all.rdf"),
            ("html_index", "https://www.env.go.jp/hourei/index.html"),
        ],
    },
    "maff": {
        "name": "農林水産省",
        "default_jsic": "A",
        "seeds": [
            ("rss", "https://www.maff.go.jp/index.rdf"),
            ("html_index", "https://www.maff.go.jp/j/law/notice/"),
        ],
    },
    "mlit": {
        "name": "国土交通省",
        "default_jsic": "F",
        "seeds": [
            ("rss", "https://www.mlit.go.jp/index.rdf"),
            ("html_index", "https://www.mlit.go.jp/policy/file000010.html"),
        ],
    },
    "fsa": {
        "name": "金融庁",
        "default_jsic": "J",
        "seeds": [
            ("html_index", "https://www.fsa.go.jp/common/law/index.html"),
            ("html_index", "https://www.fsa.go.jp/news/index.html"),
        ],
    },
    "jftc": {
        "name": "公正取引委員会",
        "default_jsic": "R",
        "seeds": [
            ("html_index", "https://www.jftc.go.jp/houdou/index.html"),
            ("html_index", "https://www.jftc.go.jp/dk/guideline/unyoukijun/index.html"),
        ],
    },
    "npa": {
        "name": "警察庁",
        "default_jsic": "R",
        "seeds": [
            ("html_index", "https://www.npa.go.jp/laws/index.html"),
            ("html_index", "https://www.npa.go.jp/news/release/index.html"),
        ],
    },
    "soumu": {
        "name": "総務省",
        "default_jsic": "H",
        "seeds": [
            ("rss", "https://www.soumu.go.jp/news.rdf"),
            ("html_index", "https://www.soumu.go.jp/menu_hourei/index.html"),
        ],
    },
    "mext": {
        "name": "文部科学省",
        "default_jsic": "O",
        "seeds": [
            ("rss", "https://www.mext.go.jp/rss/index.xml"),
            ("html_index", "https://www.mext.go.jp/b_menu/hakusho/index.htm"),
        ],
    },
    "cao": {
        "name": "内閣府",
        "default_jsic": "R",
        "seeds": [
            ("html_index", "https://www.cao.go.jp/notice/index.html"),
            ("rss", "https://www.cao.go.jp/index.rdf"),
        ],
    },
    "mod": {
        "name": "防衛省",
        "default_jsic": "R",
        "seeds": [
            ("html_index", "https://www.mod.go.jp/j/press/index.html"),
        ],
    },
    "mof": {
        "name": "財務省",
        "default_jsic": "K",
        "seeds": [
            ("rss", "https://www.mof.go.jp/index.rdf"),
            ("html_index", "https://www.mof.go.jp/policy/index.html"),
        ],
    },
    "moj": {
        "name": "法務省",
        "default_jsic": "R",
        "seeds": [
            ("html_index", "https://www.moj.go.jp/houan1/houan_index.html"),
            ("html_index", "https://www.moj.go.jp/MINJI/index.html"),
        ],
    },
}

TSUTATSU_NUMBER_PATTERNS = [
    re.compile(
        r"(令和|平成|昭和)\s*(\d+)年(\d+)月(\d+)日[\s　]*([課発基資総事審改]+\d+[-‐－]?\d+)"
    ),
    re.compile(r"([基労医職保健]\w?発)\s*(\d{2,4})[\s　]*第?\s*(\d+)\s*号"),
    re.compile(r"(\d{4})年(\d+)月(\d+)日[\s　]*([商情経産製造]+第\d+号)"),
    re.compile(r"(国\w{1,3}第\d+号)"),
    re.compile(r"(金\w{1,3}第\d+号)"),
]

_BODY_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[\s　]+")
_HREF_RE = re.compile(r'<a\s+[^>]*href="([^"#]+)"[^>]*>([^<]+)</a>', re.IGNORECASE | re.DOTALL)
_ISO_DATE_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_REIWA_DATE_RE = re.compile(r"(令和|平成|昭和)\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日")

JSIC_KEYWORD_MAP: list[tuple[str, str]] = [
    ("建設", "F"),
    ("製造", "E"),
    ("農業", "A"),
    ("林業", "A"),
    ("水産", "B"),
    ("漁業", "B"),
    ("医療", "P"),
    ("介護", "P"),
    ("教育", "O"),
    ("運輸", "H"),
    ("郵便", "H"),
    ("情報通信", "G"),
    ("IT", "G"),
    ("不動産", "K"),
    ("飲食", "M"),
    ("宿泊", "M"),
    ("小売", "I"),
    ("卸売", "I"),
    ("金融", "J"),
    ("保険", "J"),
    ("電気", "F"),
    ("ガス", "F"),
    ("税", "K"),
    ("廃棄物", "R"),
    ("環境", "R"),
]


def is_banned_url(url: str) -> bool:
    if not url:
        return True
    low = url.lower()
    return any(h in low for h in BANNED_SOURCE_HOSTS)


def is_primary(agency_id: str, url: str) -> bool:
    seeds = AGENCY_SEEDS.get(agency_id, {}).get("seeds", [])
    for _kind, seed_url in seeds:
        try:
            seed_host = urllib.parse.urlparse(seed_url).netloc.lower()
            url_host = urllib.parse.urlparse(url).netloc.lower()
        except Exception:
            continue
        if seed_host and url_host and seed_host.split(".", 1)[-1] in url_host:
            return True
    return False


def strip_html(s: str) -> str:
    out = _BODY_TAG_RE.sub(" ", s)
    return _WS_RE.sub(" ", out).strip()


def parse_iso_date(s: str | None) -> str | None:
    if not s:
        return None
    m = _ISO_DATE_RE.search(s)
    if m:
        y, mo, d = m.groups()
        try:
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        except ValueError:
            return None
    m2 = _REIWA_DATE_RE.search(s)
    if m2:
        era, yy, mo, d = m2.groups()
        base = {"令和": 2018, "平成": 1988, "昭和": 1925}.get(era, 2018)
        try:
            return f"{base + int(yy):04d}-{int(mo):02d}-{int(d):02d}"
        except ValueError:
            return None
    return None


def extract_tsutatsu_number(text: str) -> str | None:
    for pat in TSUTATSU_NUMBER_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0).strip()
    return None


def classify_jsic(title: str, default_major: str) -> str:
    for kw, code in JSIC_KEYWORD_MAP:
        if title and kw in title:
            return code
    return default_major


def compute_tsutatsu_id(agency_id: str, tsutatsu_number: str | None, title: str) -> str:
    key = f"{agency_id}|{tsutatsu_number or ''}|{title}".encode()
    return "TSU-" + hashlib.sha256(key).hexdigest()[:12]


def fetch(url: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[int, str | None]:
    if is_banned_url(url):
        return -1, None
    safe_url = urllib.parse.quote(url, safe=":/?&=#%")
    req = urllib.request.Request(safe_url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            raw = resp.read()
            try:
                return resp.status, raw.decode("utf-8")
            except UnicodeDecodeError:
                return resp.status, raw.decode("shift_jis", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, TimeoutError, OSError):
        pass
    if fetch_with_fallback_sync is None:
        return 0, None
    try:
        result = fetch_with_fallback_sync(safe_url, timeout_s=float(timeout))
        if result.source == "playwright" and result.text:
            return 200, result.text
    except Exception as exc:  # noqa: BLE001
        LOG.debug("playwright fallback err: %s", exc)
    return 0, None


def parse_html_index(body: str, base_url: str, max_links: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _HREF_RE.finditer(body):
        href = m.group(1).strip()
        anchor_text = m.group(2).strip()
        if not href or not anchor_text:
            continue
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        if href.startswith("/"):
            href = urllib.parse.urljoin(base_url, href)
        if not href.startswith("http"):
            continue
        if is_banned_url(href) or href in seen:
            continue
        joined = f"{anchor_text} {href.lower()}"
        if not any(
            k in joined
            for k in (
                "tsutatsu",
                "tuutatu",
                "tsuutatsu",
                "notice",
                "kokuji",
                "通達",
                "通知",
                "告示",
                "事務連絡",
                "事務処理基準",
            )
        ):
            continue
        seen.add(href)
        out.append({"url": href, "anchor": anchor_text[:300]})
        if len(out) >= max_links:
            break
    return out


def parse_rss(body: str, base_url: str, max_links: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return out
    ns = {
        "rss": "http://purl.org/rss/1.0/",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "dc": "http://purl.org/dc/elements/1.1/",
    }
    items = root.findall(".//rss:item", ns) or root.findall(".//item")
    for item in items:
        if len(out) >= max_links:
            break
        title_el = item.find("rss:title", ns) or item.find("title")
        link_el = item.find("rss:link", ns) or item.find("link")
        date_el = item.find("dc:date", ns) or item.find("pubDate")
        desc_el = item.find("rss:description", ns) or item.find("description")
        title = (title_el.text if title_el is not None else "") or ""
        link = (link_el.text if link_el is not None else "") or ""
        date_s = (date_el.text if date_el is not None else "") or ""
        body_s = (desc_el.text if desc_el is not None else "") or ""
        if not title or not link or is_banned_url(link):
            continue
        if not any(
            k in title
            for k in (
                "通達",
                "通知",
                "告示",
                "事務連絡",
                "事務処理基準",
                "事務取扱",
                "改正",
                "施行",
                "発出",
            )
        ):
            continue
        out.append(
            {
                "url": link.strip(),
                "anchor": title.strip()[:300],
                "issued_date": parse_iso_date(date_s) or "",
                "body_hint": body_s[:2000],
            }
        )
    return out


def fetch_detail(url: str) -> tuple[str, str | None]:
    status, body = fetch(url)
    if status != 200 or not body:
        return "", None
    title = ""
    mt = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    if mt:
        title = strip_html(mt.group(1))[:300]
    text = strip_html(body)[:20000]
    return title, text


def discover_for_agency(agency_id: str, max_per_agency: int) -> list[dict[str, Any]]:
    agency = AGENCY_SEEDS.get(agency_id)
    if not agency:
        return []
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kind, seed_url in agency["seeds"]:
        if len(candidates) >= max_per_agency:
            break
        status, body = fetch(seed_url)
        if status != 200 or not body:
            LOG.warning("[%s] seed %s status=%s", agency_id, seed_url, status)
            continue
        remaining = max_per_agency - len(candidates)
        links = (
            parse_rss(body, seed_url, remaining)
            if kind == "rss"
            else parse_html_index(body, seed_url, remaining)
        )
        for link in links:
            url = link["url"]
            if url in seen or not is_primary(agency_id, url):
                continue
            seen.add(url)
            link["agency_id"] = agency_id
            link["agency_name"] = agency["name"]
            link["default_jsic"] = agency["default_jsic"]
            candidates.append(link)
            if len(candidates) >= max_per_agency:
                break
        time.sleep(DEFAULT_DELAY)
    return candidates


def upsert(conn: sqlite3.Connection, rec: dict[str, Any], dry_run: bool = False) -> bool:
    title = rec.get("title") or rec.get("anchor") or ""
    if not title:
        return False
    source_url = rec.get("source_url") or rec.get("url") or ""
    if not source_url or is_banned_url(source_url):
        return False
    tsutatsu_number = rec.get("tsutatsu_number") or extract_tsutatsu_number(
        f"{title} {rec.get('body_text') or ''}"
    )
    body_text = (rec.get("body_text") or rec.get("body_hint") or "")[:20000]
    content_hash = hashlib.sha256(
        f"{rec.get('agency_id')}|{tsutatsu_number or title}|{body_text[:1000]}".encode()
    ).hexdigest()
    tsutatsu_id = compute_tsutatsu_id(rec["agency_id"], tsutatsu_number, title)
    industry = classify_jsic(title, rec.get("default_jsic", "R"))
    now = datetime.now(UTC).isoformat()

    if dry_run:
        print(
            f"[DRY] {rec['agency_id']:6s} {tsutatsu_id} num={tsutatsu_number or '-':24s} "
            f"title={title[:60]}..."
        )
        return True

    conn.execute(
        """
        INSERT OR IGNORE INTO am_law_tsutatsu_all (
            tsutatsu_id, agency_id, agency_name, tsutatsu_number, title,
            body_text, body_excerpt, issued_date, last_revised,
            industry_jsic_major, applicable_law_id, document_type,
            source_url, full_text_url, pdf_url, license, content_hash,
            ingested_at, last_verified
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'gov_standard', ?, ?, ?)
        """,
        (
            tsutatsu_id,
            rec["agency_id"],
            rec.get("agency_name", ""),
            tsutatsu_number,
            title[:500],
            body_text,
            body_text[:500],
            rec.get("issued_date"),
            rec.get("last_revised"),
            industry,
            rec.get("applicable_law_id"),
            rec.get("document_type", "tsutatsu"),
            source_url,
            rec.get("full_text_url") or source_url,
            source_url if source_url.endswith(".pdf") else None,
            content_hash,
            now,
            now,
        ),
    )
    return True


def write_log(conn, agencies_run, inserted, skipped, started, error=None):
    conn.execute(
        """INSERT INTO am_law_tsutatsu_all_run_log (
            started_at, finished_at, agencies_run, rows_inserted, rows_skipped, error_text
        ) VALUES (?, ?, ?, ?, ?, ?)""",
        (started, datetime.now(UTC).isoformat(), ",".join(agencies_run), inserted, skipped, error),
    )


def run(args: argparse.Namespace) -> int:
    started = datetime.now(UTC).isoformat()
    LOG.info(
        "[start] db=%s agencies=%s max=%s dry_run=%s",
        args.db_path,
        args.agencies,
        args.max_per_agency,
        args.dry_run,
    )
    if not args.dry_run and not args.db_path.exists():
        LOG.error("[error] db missing: %s", args.db_path)
        return 2

    selected = [a.strip() for a in args.agencies.split(",") if a.strip()]
    if "all" in selected:
        selected = list(AGENCY_SEEDS.keys())
    LOG.info("[plan] agencies=%s", selected)

    all_records: list[dict[str, Any]] = []
    total_discovered = 0
    for agency_id in selected:
        try:
            recs = discover_for_agency(agency_id, args.max_per_agency)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("[%s] discover error: %s", agency_id, exc)
            continue
        LOG.info("[%s] discovered %d candidates", agency_id, len(recs))
        total_discovered += len(recs)
        for rec in recs:
            try:
                title, body_text = fetch_detail(rec["url"])
            except Exception as exc:  # noqa: BLE001
                LOG.debug("[%s] detail err: %s", agency_id, exc)
                title, body_text = "", None
            rec["title"] = title or rec.get("anchor", "")
            rec["body_text"] = body_text
            rec["source_url"] = rec["url"]
            rec["full_text_url"] = rec["url"]
            all_records.append(rec)
            time.sleep(DEFAULT_DELAY * 0.5)

    LOG.info(
        "[fetch] total %d records from %d agencies (%d discovered)",
        len(all_records),
        len(selected),
        total_discovered,
    )

    if args.dry_run:
        for rec in all_records[:30]:
            upsert(None, rec, dry_run=True)  # type: ignore[arg-type]
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": "dry-run",
                    "discovered": total_discovered,
                    "would_write": len(all_records),
                    "agencies": selected,
                },
                ensure_ascii=False,
            )
        )
        return 0

    inserted = 0
    skipped = 0
    err: str | None = None
    with sqlite3.connect(args.db_path) as conn:
        sql_path = REPO_ROOT / "scripts" / "migrations" / "253_law_tsutatsu_all.sql"
        if sql_path.exists():
            try:
                with sql_path.open(encoding="utf-8") as f:
                    conn.executescript(f.read())
            except sqlite3.OperationalError as exc:
                LOG.debug("schema apply err (ignored): %s", exc)
        for rec in all_records:
            try:
                if upsert(conn, rec):
                    inserted += 1
                else:
                    skipped += 1
            except sqlite3.Error as exc:
                LOG.warning("[skip] %s", exc)
                skipped += 1
        try:
            write_log(conn, selected, inserted, skipped, started, err)
        except sqlite3.OperationalError as exc:
            LOG.debug("log write err (ignored): %s", exc)
        conn.commit()
        final = conn.execute("SELECT COUNT(*) FROM am_law_tsutatsu_all").fetchone()[0]
    print(
        json.dumps(
            {
                "ok": True,
                "mode": "full",
                "inserted": inserted,
                "skipped": skipped,
                "discovered": total_discovered,
                "table_final": int(final),
                "agencies": selected,
            },
            ensure_ascii=False,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ingest 通達 across 15 ministries")
    p.add_argument("--db-path", type=Path, default=DB_PATH)
    p.add_argument("--agencies", default="all")
    p.add_argument("--max-per-agency", type=int, default=500)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
