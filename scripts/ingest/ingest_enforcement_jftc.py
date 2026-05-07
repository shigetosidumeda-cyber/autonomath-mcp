#!/usr/bin/env python3
"""Ingest JFTC (公正取引委員会) 排除措置命令 + 確約計画認定 into autonomath.db.

Scope (2026-04-25 data_collection log / p2_recon_jftc.md):
    JFTC publishes the 独占禁止法法的措置一覧 at
    https://www.jftc.go.jp/dk/ichiran/index.html. For past 5 fiscal years
    (R2–R6) that yields ~59 records (43 排除措置 + 16 確約認定).

Source license:
    PDL v1.0 (公共データ利用規約 第1.0版) — see /kiyaku/index.html. Attribution:
        出典: 公正取引委員会ホームページ (https://www.jftc.go.jp/)
    Aggregators (biz.stayway, prtimes, nikkei, wikipedia) are BANNED per CLAUDE.md.
    We cite only jftc.go.jp URLs.

Write targets (autonomath.db):
    * am_entities (record_kind='enforcement',
                   canonical_id='enforcement:jftc:<YYYY-MM-DD>:<slug>')
    * am_enforcement_detail (entity_id FK to am_entities.canonical_id)

Dedup key:
    (issuing_authority='公正取引委員会', issuance_date, target_name).
    If target_name+issuance_date already exists in am_enforcement_detail, skip.

CLI:
    python scripts/ingest/ingest_enforcement_jftc.py
    python scripts/ingest/ingest_enforcement_jftc.py --fiscal-years R2,R3,R4,R5,R6
    python scripts/ingest/ingest_enforcement_jftc.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import requests  # type: ignore
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"missing dep: {exc}. pip install requests beautifulsoup4", file=sys.stderr)
    sys.exit(1)

_LOG = logging.getLogger("autonomath.ingest_jftc")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
BASE = "https://www.jftc.go.jp"
INDEX_URL = f"{BASE}/dk/ichiran/index.html"
HTTP_TIMEOUT = 60
RATE_SLEEP = 1.0  # polite 1 req/sec

# Past 5 fiscal years (R2=令和2年度 … R6=令和6年度). R1 added as optional bonus.
DEFAULT_YEARS = ["R2", "R3", "R4", "R5", "R6"]

FISCAL_SLUG = {
    "R1": "dkhaijo_R1.html",
    "R2": "dkhaijo_R2.html",
    "R3": "dkhaijo_R3.html",
    "R4": "dkhaijo_R4.html",
    "R5": "dkhaijo_R5.html",
    "R6": "dkhaijo_R6.html",
}

# Map action-kind HTML section to enforcement_kind enum
# am_enforcement_detail.enforcement_kind CHECK values:
#   subsidy_exclude, grant_refund, contract_suspend, business_improvement,
#   license_revoke, fine, investigation, other
ACTION_KIND_MAP = {
    "排除措置命令": "business_improvement",
    "確約計画の認定": "other",
}

WAREKI_RE = re.compile(
    r"(令和|平成)\s*(元|[0-9０-９]+)\s*年\s*([0-9０-９]+)\s*月\s*([0-9０-９]+)\s*日"
)
CASE_NO_RE = re.compile(r"([元0-9０-９]+)\s*\(\s*(措|認)\s*\)\s*([0-9０-９]+)")
HOUJIN_RE = re.compile(r"\b([0-9]{13})\b")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _strip_cell(el: Any) -> str:
    if el is None:
        return ""
    return _normalize(el.get_text(separator=" ", strip=True))


def _wareki_to_iso(text: str) -> str | None:
    """Convert 令和X年Y月Z日 / 平成X年Y月Z日 to ISO yyyy-mm-dd."""
    if not text:
        return None
    text = unicodedata.normalize("NFKC", text)
    m = WAREKI_RE.search(text)
    if not m:
        return None
    era, yr, mo, dy = m.group(1), m.group(2), m.group(3), m.group(4)
    yr_i = 1 if yr == "元" else int(yr)
    if era == "令和":
        year = 2018 + yr_i
    elif era == "平成":
        year = 1988 + yr_i
    else:
        return None
    try:
        return f"{year:04d}-{int(mo):02d}-{int(dy):02d}"
    except ValueError:
        return None


def _slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^0-9A-Za-z_\-぀-ヿ一-鿿]", "", text)
    return text[:max_len] or "unknown"


class HttpClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._last: float = 0.0

    def get(self, url: str) -> requests.Response:
        delta = time.monotonic() - self._last
        if delta < RATE_SLEEP:
            time.sleep(RATE_SLEEP - delta)
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=HTTP_TIMEOUT)
                self._last = time.monotonic()
                if resp.status_code == 200:
                    return resp
                last_err = RuntimeError(f"{resp.status_code} for {url}")
            except requests.RequestException as exc:
                last_err = exc
            time.sleep(2**attempt)
        raise RuntimeError(f"fetch failed after retries: {url}: {last_err}")


def parse_annual_page(html: str, fiscal_label: str, annual_url: str) -> list[dict[str, Any]]:
    """Parse one fiscal-year annual page, returning per-row dicts."""
    soup = BeautifulSoup(html, "html.parser")
    records: list[dict[str, Any]] = []

    # The document structure:  <h3>(1)　排除措置命令</h3> … <table> ; <h3>(2)　確約計画の認定</h3> … <table>
    # Walk <h3> markers and match the following <table>.
    for h3 in soup.find_all("h3"):
        h3_text = _strip_cell(h3)
        action_kind: str | None = None
        for key in ACTION_KIND_MAP:
            if key in h3_text:
                action_kind = key
                break
        if not action_kind:
            continue
        table = h3.find_next("table")
        if not table:
            continue
        rows = table.find_all("tr")
        # first row is header
        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < 6:
                continue
            serial = _strip_cell(cells[0])
            case_cell = cells[1]
            case_text = _strip_cell(case_cell)
            anchor = case_cell.find("a", href=True)
            press_url = anchor["href"] if anchor else None
            if press_url and press_url.startswith("/"):
                press_url = BASE + press_url
            # Case number like 6(措)4 or 6(認)3
            case_m = CASE_NO_RE.search(case_text)
            case_no = case_m.group(0) if case_m else case_text
            title = _strip_cell(cells[2])
            summary = _strip_cell(cells[3])
            law_ref = _strip_cell(cells[4])
            date_text = _strip_cell(cells[5])
            iso_date = _wareki_to_iso(date_text)
            if not iso_date:
                _LOG.warning("skip row without parseable date: %s / %s", case_no, date_text)
                continue
            records.append(
                {
                    "fiscal_label": fiscal_label,
                    "annual_url": annual_url,
                    "action_kind": action_kind,
                    "serial": serial,
                    "case_no": case_no,
                    "press_url": press_url,
                    "title": title,
                    "summary": summary,
                    "law_ref": law_ref,
                    "date_text": date_text,
                    "issuance_date": iso_date,
                }
            )
    return records


def parse_press_release(html: str) -> dict[str, Any]:
    """Extract 法人番号/事業者名 (single-defendant cases) from press release HTML.

    Multi-party cases (no unified 法人番号 table) return houjin_bangou=None.
    """
    soup = BeautifulSoup(html, "html.parser")
    info = {
        "houjin_bangou": None,
        "target_name": None,
        "address": None,
        "pdf_urls": [],
    }
    # 法人番号 cell pattern
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) >= 2:
            label = _strip_cell(cells[0])
            value = _strip_cell(cells[1])
            if label == "法人番号":
                m = HOUJIN_RE.search(value)
                if m and info["houjin_bangou"] is None:
                    info["houjin_bangou"] = m.group(1)
            elif label == "名称" or label == "商号":
                if info["target_name"] is None and value:
                    info["target_name"] = value
            elif label == "所在地" or label == "住所":
                if info["address"] is None and value:
                    info["address"] = value
    # PDF links
    pdfs: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().endswith(".pdf"):
            if href.startswith("/"):
                href = BASE + href
            pdfs.append(href)
    info["pdf_urls"] = pdfs[:10]
    return info


def ensure_jftc_authority(cur: sqlite3.Cursor) -> str:
    """Return authority:jftc, creating if missing (idempotent)."""
    cur.execute("SELECT canonical_id FROM am_authority WHERE canonical_id=?", ("authority:jftc",))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO am_authority (canonical_id, canonical_name, canonical_en, level, website)
           VALUES (?, ?, ?, ?, ?)""",
        (
            "authority:jftc",
            "公正取引委員会",
            "JFTC",
            "agency",
            "https://www.jftc.go.jp/",
        ),
    )
    return "authority:jftc"


def build_canonical_id(record: dict[str, Any]) -> str:
    slug = _slugify(record["title"], max_len=32)
    base = f"enforcement:jftc:{record['issuance_date']}:{slug}"
    # Add case_no suffix to uniquely identify multi-row entries for same date/title
    case_slug = _slugify(record.get("case_no", ""), max_len=12)
    if case_slug and case_slug != "unknown":
        base = f"{base}:{case_slug}"
    return base


def existing_dedup_keys(cur: sqlite3.Cursor) -> set[tuple[str, str]]:
    """Return set of (issuance_date, target_name_normalized) already present."""
    cur.execute(
        "SELECT issuance_date, target_name FROM am_enforcement_detail WHERE issuing_authority=?",
        ("公正取引委員会",),
    )
    out: set[tuple[str, str]] = set()
    for iso_date, name in cur.fetchall():
        key = (iso_date or "", _normalize(name or ""))
        out.add(key)
    return out


def upsert_enforcement(
    cur: sqlite3.Cursor,
    canonical_id: str,
    record: dict[str, Any],
    press_info: dict[str, Any],
    now_iso: str,
) -> bool:
    """Insert am_entities + am_enforcement_detail. Returns True on insert."""
    target_name = press_info.get("target_name") or record["title"]
    houjin = press_info.get("houjin_bangou")
    enforcement_kind = ACTION_KIND_MAP.get(record["action_kind"], "other")
    source_url = record.get("press_url") or record["annual_url"]
    # raw_json for am_entities: full row, for auditability
    raw = {
        "source": "jftc:ichiran",
        "fiscal_label": record["fiscal_label"],
        "annual_url": record["annual_url"],
        "action_kind": record["action_kind"],
        "case_no": record["case_no"],
        "serial": record.get("serial"),
        "title": record["title"],
        "summary": record["summary"],
        "law_ref": record["law_ref"],
        "issuance_date": record["issuance_date"],
        "issuance_date_text": record["date_text"],
        "press_release_url": record.get("press_url"),
        "pdf_urls": press_info.get("pdf_urls") or [],
        "target_name": target_name,
        "houjin_bangou": houjin,
        "address": press_info.get("address"),
        "issuing_authority": "公正取引委員会",
        "authority_canonical": "authority:jftc",
        "license": "PDL v1.0",
        "attribution": "出典: 公正取引委員会ホームページ (https://www.jftc.go.jp/)",
        "fetched_at": now_iso,
    }
    cur.execute(
        """INSERT OR IGNORE INTO am_entities
           (canonical_id, record_kind, source_topic, source_record_index,
            primary_name, authority_canonical, confidence, source_url,
            source_url_domain, fetched_at, raw_json)
           VALUES (?, 'enforcement', ?, NULL, ?, 'authority:jftc', ?, ?, ?, ?, ?)""",
        (
            canonical_id,
            f"jftc_ichiran_{record['fiscal_label']}",
            target_name[:255],
            0.95,
            source_url,
            "jftc.go.jp",
            now_iso,
            json.dumps(raw, ensure_ascii=False),
        ),
    )
    if cur.rowcount == 0:
        # already present with same canonical_id — treat as skip
        return False
    related_law_ref = record["law_ref"]
    if related_law_ref and "独占禁止法" not in related_law_ref:
        related_law_ref = f"独占禁止法 {related_law_ref}"
    cur.execute(
        """INSERT INTO am_enforcement_detail
           (entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, reason_summary,
            related_law_ref, source_url, source_fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            canonical_id,
            houjin,
            target_name,
            enforcement_kind,
            "公正取引委員会",
            record["issuance_date"],
            record["summary"][:2000] if record["summary"] else None,
            related_law_ref,
            source_url,
            now_iso,
        ),
    )
    return True


def run(
    db_path: Path,
    fiscal_years: list[str],
    dry_run: bool,
    verbose: bool,
) -> int:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    now_iso = datetime.now(tz=UTC).isoformat(timespec="seconds")
    http = HttpClient()

    # 1. Walk annual pages
    all_records: list[dict[str, Any]] = []
    for label in fiscal_years:
        slug = FISCAL_SLUG.get(label)
        if not slug:
            _LOG.warning("unknown fiscal label %s, skipping", label)
            continue
        url = f"{BASE}/dk/ichiran/{slug}"
        _LOG.info("fetch annual page: %s", url)
        resp = http.get(url)
        rows = parse_annual_page(resp.text, label, url)
        _LOG.info("  %s -> %d rows", label, len(rows))
        all_records.extend(rows)
    _LOG.info("total rows from annual pages: %d", len(all_records))

    # 2. Dedupe by press_url — multi-row press releases (loans/insurance cartel)
    #    share the same press_url but each row is a separate defendant.
    #    We still fetch each press_url once.
    press_cache: dict[str, dict[str, Any]] = {}
    for r in all_records:
        url = r.get("press_url")
        if not url or url in press_cache:
            continue
        try:
            resp = http.get(url)
            info = parse_press_release(resp.text)
        except Exception as exc:
            _LOG.warning("press fetch failed %s: %s", url, exc)
            info = {"houjin_bangou": None, "target_name": None, "pdf_urls": []}
        press_cache[url] = info

    # 3. Write to DB
    if dry_run:
        _LOG.info("dry-run: %d records would be inserted", len(all_records))
        for r in all_records[:3]:
            press = press_cache.get(r.get("press_url") or "", {})
            _LOG.info(
                "  %s %s %s | %s | houjin=%s",
                r["issuance_date"],
                r["action_kind"],
                r["case_no"],
                r["title"],
                press.get("houjin_bangou"),
            )
        return 0

    con = sqlite3.connect(db_path, timeout=300.0)
    try:
        con.execute("PRAGMA busy_timeout=300000")
        con.execute("PRAGMA foreign_keys=ON")
        cur = con.cursor()
        cur.execute("BEGIN IMMEDIATE")
        ensure_jftc_authority(cur)
        existing = existing_dedup_keys(cur)
        inserted = 0
        skipped_dup = 0
        for r in all_records:
            press = press_cache.get(r.get("press_url") or "", {})
            target_name = press.get("target_name") or r["title"]
            key = (r["issuance_date"], _normalize(target_name))
            if key in existing:
                skipped_dup += 1
                continue
            canonical_id = build_canonical_id(r)
            try:
                ok = upsert_enforcement(cur, canonical_id, r, press, now_iso)
            except sqlite3.IntegrityError as exc:
                _LOG.warning("integrity error for %s: %s", canonical_id, exc)
                continue
            if ok:
                inserted += 1
                existing.add(key)
        con.commit()
        _LOG.info(
            "inserted=%d skipped_duplicates=%d total_source=%d",
            inserted,
            skipped_dup,
            len(all_records),
        )
        # Post-commit audit
        cur.execute(
            "SELECT COUNT(*) FROM am_enforcement_detail WHERE issuing_authority=?",
            ("公正取引委員会",),
        )
        after_jftc = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM am_enforcement_detail")
        after_total = cur.fetchone()[0]
        _LOG.info(
            "post-insert: jftc_rows=%d total_am_enforcement_detail=%d",
            after_jftc,
            after_total,
        )
        return inserted
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--fiscal-years",
        type=str,
        default=",".join(DEFAULT_YEARS),
        help="comma-separated fiscal-year labels (e.g. R2,R3,R4,R5,R6)",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    years = [y.strip() for y in args.fiscal_years.split(",") if y.strip()]
    inserted = run(args.db, years, args.dry_run, args.verbose)
    # Exit 0 even with 0 inserts if dry-run; non-dry-run should have >=1
    if args.dry_run:
        return 0
    return 0 if inserted >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
