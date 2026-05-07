#!/usr/bin/env python3
"""Ingest 消費者庁 執行 (措置命令 / 課徴金 / 確約 / 行政処分 / 注意喚起) into
``am_enforcement_detail`` + ``am_entities``.

Recon: ``analysis_wave18/data_collection_log/p2_recon_caa.md`` (2026-04-25).

Source: https://www.caa.go.jp/notice/enforcement/{YYYY}/ (2021-2025 open;
2020 以前 は 403 で WARP 経由のみ、MVP では扱わない).

Strategy:
  1. Walk 5 年別 index HTML → collect entry_id (6 digit).
  2. Fetch each entry HTML (rate-limited 1 req/s via scripts.lib.http).
  3. Parse headline / published_at / summary / detail / pdf links with
     BeautifulSoup.
  4. Headline regex map → law_name / action_type / business_name(s).
     Multi-company headlines (e.g. "3社", "A、B及びC") are split so each
     business gets its own row.
  5. Best-effort houjin_bangou lookup against local ``invoice_registrants``
     (13,801 rows, normalized_name exact match). Miss → NULL; still insert.
  6. UPSERT into am_entities (record_kind='enforcement',
     canonical_id='enforcement:caa:<entry_id>:<slug>') + am_enforcement_detail.

PDF bodies are NOT parsed in this MVP — only pdf_urls are preserved as part
of raw_json + source_url. Violation details (課徴金額, 事業者住所) are in PDF
and deferred to a later pass.

License: caa.go.jp is PDL v1.0 (same as NTA). Attribution carried in
raw_json 'source_attribution': '消費者庁ウェブサイト'.

Parallel-safe: BEGIN IMMEDIATE + busy_timeout=300000 (per §5 concurrency
policy — matches ingest_shohi_tsutatsu.py / ingest_law_articles_egov.py).

CLI:
    python scripts/ingest/ingest_enforcement_caa.py \\
        --db autonomath.db \\
        [--years 2025,2024,2023,2022,2021] \\
        [--limit N] \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"ERROR: beautifulsoup4 not installed: {exc}", file=sys.stderr)
    raise

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import contextlib

from scripts.lib.http import HttpClient  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest.caa")

BASE_URL = "https://www.caa.go.jp"
YEAR_INDEX_FMT = BASE_URL + "/notice/enforcement/{year}/"
ENTRY_URL_FMT = BASE_URL + "/notice/entry/{entry_id}/"
ENTRY_RE = re.compile(r"/notice/entry/(\d{6})/?")

DEFAULT_YEARS = (2025, 2024, 2023, 2022, 2021)
DEFAULT_DB = REPO_ROOT / "autonomath.db"

AUTHORITY_ID = "authority:cao-ccaj"
ISSUING_AUTHORITY = "消費者庁"
SOURCE_ATTRIBUTION = "消費者庁ウェブサイト"

# ---------------------------------------------------------------------------
# Headline parsing
# ---------------------------------------------------------------------------

# Law name tokens (order matters — longest first).
LAW_PATTERNS: tuple[tuple[str, str], ...] = (
    ("特定商品等の預託等取引契約に関する法律", "預託法"),
    ("預託等取引", "預託法"),
    ("預託法", "預託法"),
    ("特定商取引に関する法律", "特定商取引法"),
    ("特定商取引法", "特定商取引法"),
    ("特商法", "特定商取引法"),
    ("景品表示法", "景品表示法"),
    ("景表法", "景品表示法"),
    ("不当景品類及び不当表示防止法", "景品表示法"),
    ("食品表示法", "食品表示法"),
    ("消費者安全法", "消費者安全法"),
    ("特定継続的役務提供", "特定商取引法"),  # 特商法 分類
    ("通信販売", "特定商取引法"),
    ("電話勧誘販売", "特定商取引法"),
    ("連鎖販売取引", "特定商取引法"),
    ("訪問販売", "特定商取引法"),
    ("訪問購入", "特定商取引法"),
)

# Action type from headline tail.
ACTION_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # (keyword_in_headline, canonical_action_type, enforcement_kind_enum)
    ("措置命令", "措置命令", "business_improvement"),
    ("課徴金納付命令", "課徴金納付命令", "fine"),
    ("課徴金", "課徴金納付命令", "fine"),
    ("確約計画", "確約計画認定", "business_improvement"),
    ("業務停止", "業務停止命令", "contract_suspend"),
    ("指示", "指示", "business_improvement"),
    ("行政処分", "行政処分", "business_improvement"),
    ("注意喚起", "注意喚起", "investigation"),
    ("禁止命令", "禁止命令", "contract_suspend"),
    ("取消", "登録取消", "license_revoke"),
)

# 違反条項 pattern: 景品表示法第N条第M号 / 特定商取引法第N条 第M号
LAW_ARTICLE_RE = re.compile(
    r"(景品表示法|特定商取引法|預託法|食品表示法|消費者安全法)"
    r"第([0-9０-９]+)条(?:第([0-9０-９]+)項)?(?:第?([一二三四五六七八九十0-9０-９]+)号)?"
)

# Business name extraction patterns in headline.
# 1) 【 社名 】
BRACKET_NAME_RE = re.compile(r"【\s*([^【】]+?)\s*】")
# 2) "XX事業者3社" / "XX業者4社" — multi-company count trigger
MULTI_COMPANY_RE = re.compile(r"([0-9０-９]+)\s*社")
# 3) "○○株式会社" freeform (fallback single company)
CORP_SUFFIX_RE = re.compile(
    r"([^\s、,。「」『』【】]+?(?:株式会社|有限会社|合同会社|合名会社|合資会社|株式会社|\(株\)|（株）))"
)

WAREKI_RE = re.compile(r"(令和|平成|昭和)\s*(\d+|元)\s*年\s*(\d+)\s*月\s*(\d+)\s*日")
SEIREKI_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
ERA_OFFSET = {"令和": 2018, "平成": 1988, "昭和": 1925}


def _normalize(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").strip()


def _parse_date(text: str) -> str | None:
    """Return ISO YYYY-MM-DD from Japanese date text."""
    if not text:
        return None
    s = _normalize(text)
    m = SEIREKI_RE.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = WAREKI_RE.search(s)
    if m:
        era, y_raw, mo, d = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        y_off = 1 if y_raw == "元" else int(y_raw)
        year = ERA_OFFSET[era] + y_off
        return f"{year:04d}-{mo:02d}-{d:02d}"
    return None


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------


@dataclass
class Entry:
    entry_id: str
    url: str
    headline: str
    published_at: str | None
    summary: str
    detail: str
    pdf_urls: list[str] = field(default_factory=list)


def parse_year_index(html: str) -> list[tuple[str, str, str]]:
    """Return [(entry_id, url, headline_title)] dedup'd."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for a in soup.select('a[href*="/notice/entry/"]'):
        href = a.get("href", "")
        m = ENTRY_RE.search(href)
        if not m:
            continue
        eid = m.group(1)
        if eid in seen:
            continue
        seen.add(eid)
        url = urljoin(BASE_URL, href.strip())
        title = (a.get("title") or a.get_text(strip=True) or "").strip()
        out.append((eid, url, title))
    return out


def parse_entry(entry_id: str, url: str, html: str) -> Entry:
    soup = BeautifulSoup(html, "html.parser")

    headline = ""
    h1 = soup.find("h1")
    if h1:
        headline = h1.get_text(strip=True)

    published_at = None
    date_el = soup.select_one("p.al_right")
    if date_el:
        published_at = _parse_date(date_el.get_text(strip=True))

    summary = ""
    excerpt = soup.select_one("#block_excerpt")
    if excerpt:
        ps = [p.get_text(" ", strip=True) for p in excerpt.find_all("p")]
        summary = "\n".join(x for x in ps if x)

    detail = ""
    detail_el = soup.select_one("#block_detail")
    if detail_el:
        ps = [p.get_text(" ", strip=True) for p in detail_el.find_all("p")]
        detail = "\n".join(x for x in ps if x)

    pdfs: list[str] = []
    block_file = soup.select_one("#block_file")
    if block_file:
        for a in block_file.find_all("a"):
            href = (a.get("href") or "").strip()
            if href.lower().endswith(".pdf"):
                pdfs.append(urljoin(BASE_URL, href))

    return Entry(
        entry_id=entry_id,
        url=url,
        headline=_normalize(headline),
        published_at=published_at,
        summary=_normalize(summary),
        detail=_normalize(detail),
        pdf_urls=pdfs,
    )


# ---------------------------------------------------------------------------
# Headline → law / action / company split
# ---------------------------------------------------------------------------


def detect_law(headline: str, body: str) -> tuple[str | None, str | None]:
    """Return (canonical_law_name, related_law_ref).

    related_law_ref is parsed from body detail if possible (第N条第M号 etc).
    """
    law_name: str | None = None
    # Prefer longest match in both strings.
    for needle, canonical in LAW_PATTERNS:
        if needle in headline or needle in body:
            law_name = canonical
            break

    ref: str | None = None
    m = LAW_ARTICLE_RE.search(body)
    if not m:
        m = LAW_ARTICLE_RE.search(headline)
    if m:
        law_part = m.group(1)
        art = _normalize(m.group(2))
        clause = _normalize(m.group(3)) if m.group(3) else None
        item = _normalize(m.group(4)) if m.group(4) else None
        parts = [f"{law_part}第{art}条"]
        if clause:
            parts.append(f"第{clause}項")
        if item:
            parts.append(f"第{item}号")
        ref = "".join(parts)
        if law_name is None:
            law_name = law_part
    return law_name, ref


def detect_action(headline: str) -> tuple[str, str]:
    """Return (action_type_label, am_enforcement_kind_enum)."""
    for needle, action, kind in ACTION_PATTERNS:
        if needle in headline:
            return action, kind
    return "その他", "other"


_SPLIT_CHARS = re.compile(r"[、,，]|及び|並びに")


def _looks_like_company_token(tok: str) -> bool:
    t = tok.strip()
    if not t:
        return False
    # Keep tokens that look like company names.
    return any(
        suffix in t
        for suffix in ("株式会社", "有限会社", "合同会社", "合資会社", "合名会社", "(株)", "（株）")
    )


def extract_business_names(headline: str, detail: str) -> list[str]:
    """Return deduped list of company names (1-N).

    Strategy:
      1. If 【 ... 】 wrapper present → split its inside by 、,及び並びに.
      2. Else if "N社" present → mine detail for company-suffix tokens.
      3. Else fall back to single 株式会社 token in headline.
    """
    names: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        n = _normalize(raw).strip(" 　")
        # Strip surrounding 【 】 if any left
        n = n.strip("【】")
        if not n:
            return
        if n in seen:
            return
        seen.add(n)
        names.append(n)

    brack_matches = BRACKET_NAME_RE.findall(headline)
    if brack_matches:
        for raw in brack_matches:
            parts = _SPLIT_CHARS.split(raw)
            for part in parts:
                p = part.strip()
                if p:
                    _add(p)
        if names:
            return names

    # "○社" multi-company → mine detail
    if MULTI_COMPANY_RE.search(headline):
        # Extract all corp-suffix tokens from detail, dedup, cap at 10.
        tokens = CORP_SUFFIX_RE.findall(detail)
        for t in tokens:
            _add(t)
        if names:
            return names[:10]

    # Single company fallback (check headline first, then detail).
    for src in (headline, detail):
        tokens = CORP_SUFFIX_RE.findall(src)
        for t in tokens:
            _add(t)
            if len(names) >= 1:
                return names
    return names


# ---------------------------------------------------------------------------
# houjin_bangou best-effort lookup
# ---------------------------------------------------------------------------


class HoujinLookup:
    """Best-effort 法人番号 resolver against local invoice_registrants.

    If `data/jpintel.db` exists and has populated `invoice_registrants`,
    we do an exact + stripped normalized name match. Miss → None. Never
    raises; never calls external API (zero-touch + ¥0 policy).
    """

    def __init__(self, db_path: Path | None):
        self._conn: sqlite3.Connection | None = None
        if db_path and db_path.exists():
            try:
                c = sqlite3.connect(str(db_path))
                c.execute("PRAGMA busy_timeout=5000")
                self._conn = c
            except sqlite3.Error as exc:
                _LOG.warning("houjin lookup disabled (%s): %s", db_path, exc)

    @staticmethod
    def _strip_company_suffix(name: str) -> str:
        n = _normalize(name)
        for suf in ("株式会社", "有限会社", "合同会社", "合資会社", "合名会社", "(株)", "（株）"):
            n = n.replace(suf, "")
        return n.strip(" 　")

    def resolve(self, name: str) -> str | None:
        if not self._conn or not name:
            return None
        norm = _normalize(name)
        stripped = self._strip_company_suffix(name)
        try:
            row = self._conn.execute(
                "SELECT houjin_bangou FROM invoice_registrants WHERE normalized_name=? AND houjin_bangou IS NOT NULL LIMIT 1",
                (norm,),
            ).fetchone()
            if row and row[0]:
                return row[0]
            if stripped and stripped != norm:
                row = self._conn.execute(
                    "SELECT houjin_bangou FROM invoice_registrants "
                    "WHERE normalized_name LIKE ? AND houjin_bangou IS NOT NULL LIMIT 1",
                    (f"%{stripped}%",),
                ).fetchone()
                if row and row[0]:
                    return row[0]
        except sqlite3.Error as exc:
            _LOG.debug("houjin lookup error name=%r err=%s", name, exc)
        return None

    def close(self) -> None:
        if self._conn:
            with contextlib.suppress(sqlite3.Error):
                self._conn.close()


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def _slug(name: str, max_len: int = 16) -> str:
    """Stable short hash-based slug for canonical_id tail."""
    h = hashlib.sha1(_normalize(name).encode("utf-8")).hexdigest()
    return h[:max_len]


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(f"missing table '{tbl}' in DB — apply migrations before running")


def upsert_entity(
    conn: sqlite3.Connection,
    canonical_id: str,
    primary_name: str,
    url: str,
    raw_json: str,
    now_iso: str,
) -> None:
    domain = urlparse(url).netloc or None
    conn.execute(
        """
        INSERT INTO am_entities (
            canonical_id, record_kind, source_topic, source_record_index,
            primary_name, authority_canonical, confidence,
            source_url, source_url_domain, fetched_at, raw_json,
            canonical_status, citation_status
        ) VALUES (?, 'enforcement', 'caa_enforcement', NULL,
                  ?, ?, 0.9, ?, ?, ?, ?, 'active', 'ok')
        ON CONFLICT(canonical_id) DO UPDATE SET
            primary_name      = excluded.primary_name,
            authority_canonical = excluded.authority_canonical,
            confidence        = excluded.confidence,
            source_url        = excluded.source_url,
            source_url_domain = excluded.source_url_domain,
            fetched_at        = excluded.fetched_at,
            raw_json          = excluded.raw_json,
            updated_at        = datetime('now')
        """,
        (
            canonical_id,
            primary_name[:500],
            AUTHORITY_ID,
            url,
            domain,
            now_iso,
            raw_json,
        ),
    )


def upsert_enforcement(
    conn: sqlite3.Connection,
    entity_id: str,
    houjin_bangou: str | None,
    target_name: str,
    kind: str,
    issuance_date: str,
    reason_summary: str | None,
    related_law_ref: str | None,
    source_url: str,
    source_fetched_at: str,
) -> str:
    """Insert or update the single enforcement row for this entity_id.

    am_enforcement_detail has no UNIQUE on entity_id in the schema; we
    use DELETE-then-INSERT keyed by entity_id so re-runs don't duplicate.
    """
    existed = (
        conn.execute(
            "SELECT 1 FROM am_enforcement_detail WHERE entity_id=? LIMIT 1",
            (entity_id,),
        ).fetchone()
        is not None
    )
    if existed:
        conn.execute(
            "DELETE FROM am_enforcement_detail WHERE entity_id=?",
            (entity_id,),
        )
    conn.execute(
        """
        INSERT INTO am_enforcement_detail (
            entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, exclusion_start, exclusion_end,
            reason_summary, related_law_ref, amount_yen,
            source_url, source_fetched_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            entity_id,
            houjin_bangou,
            target_name[:500],
            kind,
            ISSUING_AUTHORITY,
            issuance_date,
            None,
            None,
            (reason_summary or "")[:4000],
            related_law_ref,
            None,
            source_url,
            source_fetched_at,
        ),
    )
    return "update" if existed else "insert"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help=f"autonomath.db path (default {DEFAULT_DB})"
    )
    ap.add_argument(
        "--years",
        type=str,
        default=",".join(str(y) for y in DEFAULT_YEARS),
        help="comma-separated years (default 2025,2024,2023,2022,2021)",
    )
    ap.add_argument("--limit", type=int, default=None, help="cap total entries walked")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--jpintel-db",
        type=Path,
        default=REPO_ROOT / "data" / "jpintel.db",
        help="path to jpintel.db for houjin_bangou lookup (best effort)",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        years = [int(y.strip()) for y in args.years.split(",") if y.strip()]
    except ValueError:
        _LOG.error("bad --years: %s", args.years)
        return 2

    http = HttpClient()
    houjin = HoujinLookup(args.jpintel_db)
    now_iso = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    conn: sqlite3.Connection | None = None
    if not args.dry_run:
        if not args.db.exists():
            _LOG.error("autonomath.db missing: %s", args.db)
            return 2
        conn = sqlite3.connect(str(args.db))
        conn.execute("PRAGMA busy_timeout=300000")
        conn.execute("PRAGMA foreign_keys=ON")
        ensure_tables(conn)

    stats = {
        "years": len(years),
        "entries_walked": 0,
        "entries_parsed": 0,
        "records_built": 0,
        "inserted": 0,
        "updated": 0,
        "skipped_no_date": 0,
        "skipped_no_business": 0,
        "skipped_fetch_err": 0,
        "houjin_hits": 0,
    }

    # -- 1. Walk year indexes ---------------------------------------------
    all_entries: list[tuple[str, str, str]] = []
    seen_ids: set[str] = set()
    for year in years:
        url = YEAR_INDEX_FMT.format(year=year)
        _LOG.info("fetch year index %s", url)
        res = http.get(url)
        if not res.ok:
            _LOG.warning(
                "year %s fetch failed status=%s skip=%s", year, res.status, res.skip_reason
            )
            continue
        items = parse_year_index(res.text)
        _LOG.info("year %s entries: %d", year, len(items))
        for eid, u, title in items:
            if eid in seen_ids:
                continue
            seen_ids.add(eid)
            all_entries.append((eid, u, title))

    if args.limit and args.limit > 0:
        all_entries = all_entries[: args.limit]
    _LOG.info("total unique entries queued: %d", len(all_entries))

    # -- 2. Walk each entry + commit in batches ---------------------------
    BATCH_SIZE = 25

    def _begin() -> None:
        if conn is not None:
            conn.execute("BEGIN IMMEDIATE")

    def _commit() -> None:
        if conn is not None:
            conn.commit()

    try:
        if conn is not None:
            _begin()
        batch_n = 0
        for _idx, (eid, url, _title) in enumerate(all_entries, start=1):
            stats["entries_walked"] += 1
            try:
                res = http.get(url)
                if not res.ok:
                    _LOG.warning("entry %s fetch failed status=%s", eid, res.status)
                    stats["skipped_fetch_err"] += 1
                    continue
                entry = parse_entry(eid, url, res.text)
            except Exception as exc:  # noqa: BLE001
                _LOG.exception("parse error entry_id=%s: %s", eid, exc)
                stats["skipped_fetch_err"] += 1
                continue
            stats["entries_parsed"] += 1

            if not entry.published_at:
                _LOG.warning("entry %s: no date — skip", eid)
                stats["skipped_no_date"] += 1
                continue
            if not entry.headline:
                _LOG.warning("entry %s: no headline — skip", eid)
                stats["skipped_no_business"] += 1
                continue

            action, kind_enum = detect_action(entry.headline)
            law_name, law_ref = detect_law(entry.headline, entry.summary + "\n" + entry.detail)
            businesses = extract_business_names(entry.headline, entry.detail)

            if not businesses:
                _LOG.warning(
                    "entry %s: no business name extracted from headline=%r — record with placeholder",
                    eid,
                    entry.headline[:80],
                )
                # Still create a single row using headline as target_name
                # so we don't lose the enforcement record (e.g. generic 注意喚起).
                businesses = [entry.headline[:120]]

            # Per-business record split
            reason_body = (entry.summary + ("\n" + entry.detail if entry.detail else "")).strip()
            shared_raw = {
                "entry_id": eid,
                "source_url": url,
                "headline": entry.headline,
                "published_at": entry.published_at,
                "summary": entry.summary,
                "detail": entry.detail[:2000],
                "pdf_urls": entry.pdf_urls,
                "law_name": law_name,
                "related_law_ref": law_ref,
                "action_type": action,
                "source_attribution": SOURCE_ATTRIBUTION,
                "license": "PDL v1.0",
            }

            for biz in businesses:
                hb = houjin.resolve(biz)
                if hb:
                    stats["houjin_hits"] += 1
                canonical_id = f"enforcement:caa:{eid}:{_slug(biz)}"
                primary_name = (
                    f"{biz} に対する{action}" if action != "その他" else entry.headline[:200]
                )
                raw_json = json.dumps(
                    dict(shared_raw, target_name=biz, houjin_bangou=hb),
                    ensure_ascii=False,
                )

                if conn is not None:
                    try:
                        upsert_entity(conn, canonical_id, primary_name, url, raw_json, now_iso)
                        verdict = upsert_enforcement(
                            conn=conn,
                            entity_id=canonical_id,
                            houjin_bangou=hb,
                            target_name=biz,
                            kind=kind_enum,
                            issuance_date=entry.published_at,
                            reason_summary=reason_body,
                            related_law_ref=law_ref,
                            source_url=url,
                            source_fetched_at=now_iso,
                        )
                        if verdict == "insert":
                            stats["inserted"] += 1
                        else:
                            stats["updated"] += 1
                    except sqlite3.Error as exc:
                        _LOG.error("DB error entry=%s biz=%r: %s", eid, biz, exc)
                        continue
                stats["records_built"] += 1
                _LOG.debug(
                    "OK %s | %s | %s | kind=%s law=%s ref=%s hb=%s",
                    eid,
                    entry.published_at,
                    biz[:40],
                    kind_enum,
                    law_name,
                    law_ref,
                    hb or "-",
                )

            batch_n += 1
            if conn is not None and batch_n >= BATCH_SIZE:
                _commit()
                _begin()
                batch_n = 0

        if conn is not None:
            _commit()
    finally:
        if conn is not None:
            with contextlib.suppress(sqlite3.Error):
                conn.close()
        http.close()
        houjin.close()

    _LOG.info(
        "done years=%d walked=%d parsed=%d records=%d inserted=%d updated=%d "
        "skipped_no_date=%d skipped_no_biz=%d fetch_err=%d houjin_hits=%d",
        stats["years"],
        stats["entries_walked"],
        stats["entries_parsed"],
        stats["records_built"],
        stats["inserted"],
        stats["updated"],
        stats["skipped_no_date"],
        stats["skipped_no_business"],
        stats["skipped_fetch_err"],
        stats["houjin_hits"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
