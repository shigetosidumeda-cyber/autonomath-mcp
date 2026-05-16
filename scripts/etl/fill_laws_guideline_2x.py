#!/usr/bin/env python3
"""Wave 43.1.7 — 業種ガイドライン (省庁 + 業界団体) ingest into
`am_law_guideline` (migration 254). NO LLM API. License = gov_standard /
industry_body. Idempotent.

Usage:
    python scripts/etl/fill_laws_guideline_2x.py --dry-run
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

LOG = logging.getLogger("fill_laws_guideline_2x")

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "autonomath.db"

UA = "jpcite-guideline-bot/1.0 (+https://bookyou.net; operator=info@bookyou.net)"
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

ISSUERS: list[dict[str, Any]] = [
    {
        "issuer_type": "ministry",
        "issuer_org": "経済産業省",
        "issuer_agency_id": "meti",
        "default_jsic_major": "E",
        "license": "gov_standard",
        "seeds": [
            ("rss", "https://www.meti.go.jp/rss/topics.rdf"),
            ("html_index", "https://www.meti.go.jp/policy/economy/index.html"),
            (
                "html_index",
                "https://www.meti.go.jp/policy/safety_security/industrial_safety/sangyo/guideline/index.html",
            ),
        ],
    },
    {
        "issuer_type": "ministry",
        "issuer_org": "厚生労働省",
        "issuer_agency_id": "mhlw",
        "default_jsic_major": "P",
        "license": "gov_standard",
        "seeds": [
            ("rss", "https://www.mhlw.go.jp/stf/news.rdf"),
            ("html_index", "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/index.html"),
        ],
    },
    {
        "issuer_type": "ministry",
        "issuer_org": "環境省",
        "issuer_agency_id": "env",
        "default_jsic_major": "E",
        "license": "gov_standard",
        "seeds": [
            ("rss", "https://www.env.go.jp/rss/all.rdf"),
            ("html_index", "https://www.env.go.jp/policy/guideline.html"),
        ],
    },
    {
        "issuer_type": "ministry",
        "issuer_org": "農林水産省",
        "issuer_agency_id": "maff",
        "default_jsic_major": "A",
        "license": "gov_standard",
        "seeds": [
            ("rss", "https://www.maff.go.jp/index.rdf"),
            ("html_index", "https://www.maff.go.jp/j/guide/"),
        ],
    },
    {
        "issuer_type": "ministry",
        "issuer_org": "国土交通省",
        "issuer_agency_id": "mlit",
        "default_jsic_major": "F",
        "license": "gov_standard",
        "seeds": [
            ("rss", "https://www.mlit.go.jp/index.rdf"),
            ("html_index", "https://www.mlit.go.jp/page/kanbo01_hy_001247.html"),
        ],
    },
    {
        "issuer_type": "ministry",
        "issuer_org": "文部科学省",
        "issuer_agency_id": "mext",
        "default_jsic_major": "O",
        "license": "gov_standard",
        "seeds": [
            ("rss", "https://www.mext.go.jp/rss/index.xml"),
        ],
    },
    {
        "issuer_type": "ministry",
        "issuer_org": "金融庁",
        "issuer_agency_id": "fsa",
        "default_jsic_major": "J",
        "license": "gov_standard",
        "seeds": [
            ("html_index", "https://www.fsa.go.jp/common/law/guide/index.html"),
            ("html_index", "https://www.fsa.go.jp/news/index.html"),
        ],
    },
    {
        "issuer_type": "ministry",
        "issuer_org": "公正取引委員会",
        "issuer_agency_id": "jftc",
        "default_jsic_major": "R",
        "license": "gov_standard",
        "seeds": [
            ("html_index", "https://www.jftc.go.jp/dk/guideline/unyoukijun/index.html"),
        ],
    },
    {
        "issuer_type": "ministry",
        "issuer_org": "総務省",
        "issuer_agency_id": "soumu",
        "default_jsic_major": "H",
        "license": "gov_standard",
        "seeds": [
            ("rss", "https://www.soumu.go.jp/news.rdf"),
            ("html_index", "https://www.soumu.go.jp/menu_hourei/index.html"),
        ],
    },
    {
        "issuer_type": "ministry",
        "issuer_org": "国税庁",
        "issuer_agency_id": "nta",
        "default_jsic_major": "K",
        "license": "gov_standard",
        "seeds": [
            ("html_index", "https://www.nta.go.jp/law/joho-zeikaishaku/index.htm"),
        ],
    },
    {
        "issuer_type": "public_corp",
        "issuer_org": "中小企業庁",
        "issuer_agency_id": "meti",
        "default_jsic_major": "R",
        "license": "gov_standard",
        "seeds": [
            ("html_index", "https://www.chusho.meti.go.jp/keiei/sapoin/index.html"),
            ("html_index", "https://www.chusho.meti.go.jp/zaimu/shokibo/index.html"),
        ],
    },
    {
        "issuer_type": "public_corp",
        "issuer_org": "中小企業基盤整備機構",
        "issuer_agency_id": None,
        "default_jsic_major": "R",
        "license": "industry_body",
        "seeds": [
            ("html_index", "https://www.smrj.go.jp/regional_hq/index.html"),
        ],
    },
    {
        "issuer_type": "industry_body",
        "issuer_org": "日本商工会議所",
        "issuer_agency_id": None,
        "default_jsic_major": "R",
        "license": "industry_body",
        "seeds": [
            ("html_index", "https://www.jcci.or.jp/news/"),
        ],
    },
    {
        "issuer_type": "industry_body",
        "issuer_org": "全国商工会連合会",
        "issuer_agency_id": None,
        "default_jsic_major": "R",
        "license": "industry_body",
        "seeds": [
            ("html_index", "https://www.shokokai.or.jp/"),
        ],
    },
    {
        "issuer_type": "industry_body",
        "issuer_org": "日本経済団体連合会",
        "issuer_agency_id": None,
        "default_jsic_major": "R",
        "license": "industry_body",
        "seeds": [
            ("html_index", "https://www.keidanren.or.jp/policy/index.html"),
        ],
    },
    {
        "issuer_type": "industry_body",
        "issuer_org": "日本税理士会連合会",
        "issuer_agency_id": None,
        "default_jsic_major": "K",
        "license": "industry_body",
        "seeds": [
            ("html_index", "https://www.nichizeiren.or.jp/news/"),
        ],
    },
    {
        "issuer_type": "industry_body",
        "issuer_org": "日本公認会計士協会",
        "issuer_agency_id": None,
        "default_jsic_major": "K",
        "license": "industry_body",
        "seeds": [
            ("html_index", "https://jicpa.or.jp/specialized_field/index.html"),
        ],
    },
]


JSIC_KEYWORD_MAP: list[tuple[str, str]] = [
    ("建設", "F"),
    ("製造", "E"),
    ("農業", "A"),
    ("林業", "A"),
    ("漁業", "B"),
    ("水産", "B"),
    ("医療", "P"),
    ("介護", "P"),
    ("教育", "O"),
    ("運輸", "H"),
    ("情報通信", "G"),
    ("IT", "G"),
    ("不動産", "K"),
    ("飲食", "M"),
    ("宿泊", "M"),
    ("小売", "I"),
    ("卸売", "I"),
    ("金融", "J"),
    ("保険", "J"),
    ("税理士", "K"),
    ("税務", "K"),
    ("会計", "K"),
    ("環境", "R"),
    ("廃棄物", "R"),
]

GUIDELINE_KEYWORDS = (
    "ガイドライン",
    "指針",
    "手引",
    "マニュアル",
    "ベストプラクティス",
    "モデル規程",
    "事例集",
    "実務指針",
    "通達",
    "解釈通達",
    "通知",
)

_HREF_RE = re.compile(r'<a\s+[^>]*href="([^"#]+)"[^>]*>([^<]+)</a>', re.IGNORECASE | re.DOTALL)
_BODY_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[\s　]+")
_ISO_DATE_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")


def is_banned_url(url: str) -> bool:
    if not url:
        return True
    low = url.lower()
    return any(h in low for h in BANNED_SOURCE_HOSTS)


def strip_html(s: str) -> str:
    return _WS_RE.sub(" ", _BODY_TAG_RE.sub(" ", s)).strip()


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


def classify_jsic(title: str, default_major: str) -> str:
    for kw, code in JSIC_KEYWORD_MAP:
        if title and kw in title:
            return code
    return default_major


def classify_compliance(title: str) -> str:
    if not title:
        return "recommended"
    if "義務" in title or "強制" in title or "必須" in title:
        return "mandatory"
    if "推奨" in title or "ガイドライン" in title or "指針" in title:
        return "recommended"
    if "参考" in title or "モデル" in title or "ベストプラクティス" in title:
        return "voluntary"
    return "recommended"


def classify_doc_type(title: str) -> str:
    if not title:
        return "guideline"
    if "マニュアル" in title:
        return "manual"
    if "手引" in title:
        return "tebiki"
    if "指針" in title:
        return "shishin"
    if "モデル規程" in title:
        return "model_rules"
    if "ベストプラクティス" in title:
        return "best_practice"
    return "guideline"


def compute_guideline_id(issuer_org: str, title: str) -> str:
    key = f"{issuer_org}|{title}".encode()
    return "GL2-" + hashlib.sha256(key).hexdigest()[:12]


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
        LOG.debug("playwright err: %s", exc)
    return 0, None


def parse_html_index(body: str, base_url: str, max_links: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _HREF_RE.finditer(body):
        href = m.group(1).strip()
        anchor = m.group(2).strip()
        if not href or not anchor:
            continue
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        if href.startswith("/"):
            href = urllib.parse.urljoin(base_url, href)
        if not href.startswith("http") or is_banned_url(href) or href in seen:
            continue
        if not any(k in anchor for k in GUIDELINE_KEYWORDS):
            continue
        seen.add(href)
        out.append({"url": href, "anchor": anchor[:300]})
        if len(out) >= max_links:
            break
    return out


def parse_rss(body: str, max_links: int) -> list[dict[str, str]]:
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
        if not any(k in title for k in GUIDELINE_KEYWORDS):
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


def discover_for_issuer(issuer: dict[str, Any], max_links: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kind, seed_url in issuer["seeds"]:
        if len(out) >= max_links:
            break
        status, body = fetch(seed_url)
        if status != 200 or not body:
            LOG.warning("[%s] seed %s status=%s", issuer["issuer_org"], seed_url, status)
            continue
        remaining = max_links - len(out)
        links = (
            parse_rss(body, remaining)
            if kind == "rss"
            else parse_html_index(body, seed_url, remaining)
        )
        for link in links:
            url = link["url"]
            if url in seen:
                continue
            seen.add(url)
            link["issuer_type"] = issuer["issuer_type"]
            link["issuer_org"] = issuer["issuer_org"]
            link["issuer_agency_id"] = issuer.get("issuer_agency_id")
            link["default_jsic_major"] = issuer["default_jsic_major"]
            link["license"] = issuer.get("license", "gov_standard")
            out.append(link)
            if len(out) >= max_links:
                break
        time.sleep(DEFAULT_DELAY)
    return out


def upsert(conn: sqlite3.Connection, rec: dict[str, Any], dry_run: bool = False) -> bool:
    title = rec.get("title") or rec.get("anchor") or ""
    if not title:
        return False
    source_url = rec.get("source_url") or rec.get("url") or ""
    if not source_url or is_banned_url(source_url):
        return False
    body_text = (rec.get("body_text") or rec.get("body_hint") or "")[:20000]
    industry = classify_jsic(title, rec.get("default_jsic_major", "R"))
    compliance = classify_compliance(title)
    doc_type = classify_doc_type(title)
    guideline_id = compute_guideline_id(rec["issuer_org"], title)
    content_hash = hashlib.sha256(
        f"{rec['issuer_org']}|{title}|{body_text[:1000]}".encode()
    ).hexdigest()
    now = datetime.now(UTC).isoformat()

    if dry_run:
        print(
            f"[DRY] {rec['issuer_type']:14s} {guideline_id} jsic={industry} "
            f"compl={compliance} title={title[:60]}..."
        )
        return True

    conn.execute(
        """
        INSERT OR IGNORE INTO am_law_guideline (
            guideline_id, issuer_type, issuer_org, issuer_agency_id,
            title, short_title, body_text, body_excerpt,
            industry_jsic_major, industry_jsic_minor, industry_jsic_label,
            target_audience, compliance_status, issued_date, last_revised,
            related_law_ids_json, document_type, source_url, full_text_url,
            pdf_url, license, content_hash, ingested_at, last_verified
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            guideline_id,
            rec["issuer_type"],
            rec["issuer_org"],
            rec.get("issuer_agency_id"),
            title[:500],
            title[:120],
            body_text,
            body_text[:500],
            industry,
            rec.get("industry_jsic_minor"),
            rec.get("industry_jsic_label"),
            rec.get("target_audience"),
            compliance,
            rec.get("issued_date"),
            rec.get("last_revised"),
            doc_type,
            source_url,
            rec.get("full_text_url") or source_url,
            source_url if source_url.endswith(".pdf") else None,
            rec.get("license", "gov_standard"),
            content_hash,
            now,
            now,
        ),
    )
    return True


def write_log(conn, issuers_run, inserted, skipped, started, err=None):
    conn.execute(
        """INSERT INTO am_law_guideline_run_log (
            started_at, finished_at, issuers_run, rows_inserted, rows_skipped, error_text
        ) VALUES (?, ?, ?, ?, ?, ?)""",
        (started, datetime.now(UTC).isoformat(), ",".join(issuers_run), inserted, skipped, err),
    )


def run(args: argparse.Namespace) -> int:
    started = datetime.now(UTC).isoformat()
    LOG.info(
        "[start] db=%s issuer_filter=%s max=%s dry_run=%s",
        args.db_path,
        args.issuers,
        args.max_per_issuer,
        args.dry_run,
    )
    if not args.dry_run and not args.db_path.exists():
        LOG.error("[error] db missing: %s", args.db_path)
        return 2

    filter_types: list[str] | None = None
    if args.issuers and args.issuers != "all":
        filter_types = [s.strip() for s in args.issuers.split(",") if s.strip()]
    selected = [
        iss for iss in ISSUERS if filter_types is None or iss["issuer_type"] in filter_types
    ]
    LOG.info("[plan] %d issuers", len(selected))

    all_records: list[dict[str, Any]] = []
    discovered = 0
    for issuer in selected:
        try:
            recs = discover_for_issuer(issuer, args.max_per_issuer)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("[%s] discover err: %s", issuer["issuer_org"], exc)
            continue
        LOG.info("[%s] %d candidates", issuer["issuer_org"], len(recs))
        discovered += len(recs)
        for rec in recs:
            try:
                title, body_text = fetch_detail(rec["url"])
            except Exception as exc:  # noqa: BLE001
                LOG.debug("detail err: %s", exc)
                title, body_text = "", None
            rec["title"] = title or rec.get("anchor", "")
            rec["body_text"] = body_text
            rec["source_url"] = rec["url"]
            rec["full_text_url"] = rec["url"]
            all_records.append(rec)
            time.sleep(DEFAULT_DELAY * 0.5)

    LOG.info("[fetch] total=%d (discovered=%d)", len(all_records), discovered)

    if args.dry_run:
        for rec in all_records[:30]:
            upsert(None, rec, dry_run=True)  # type: ignore[arg-type]
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": "dry-run",
                    "discovered": discovered,
                    "would_write": len(all_records),
                    "issuers": [s["issuer_org"] for s in selected],
                },
                ensure_ascii=False,
            )
        )
        return 0

    inserted = 0
    skipped = 0
    err: str | None = None
    with sqlite3.connect(args.db_path) as conn:
        sql_path = REPO_ROOT / "scripts" / "migrations" / "254_law_guideline.sql"
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
            write_log(conn, [s["issuer_org"] for s in selected], inserted, skipped, started, err)
        except sqlite3.OperationalError as exc:
            LOG.debug("log err (ignored): %s", exc)
        conn.commit()
        final = conn.execute("SELECT COUNT(*) FROM am_law_guideline").fetchone()[0]
    print(
        json.dumps(
            {
                "ok": True,
                "mode": "full",
                "inserted": inserted,
                "skipped": skipped,
                "discovered": discovered,
                "table_final": int(final),
                "issuers": [s["issuer_org"] for s in selected],
            },
            ensure_ascii=False,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ingest 業種ガイドライン (省庁 + 業界団体)")
    p.add_argument("--db-path", type=Path, default=DB_PATH)
    p.add_argument("--issuers", default="all")
    p.add_argument("--max-per-issuer", type=int, default=50)
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
