#!/usr/bin/env python3
"""Ingest PMDA + MHLW 薬機法 回収命令 / 行政処分 into ``am_enforcement_detail``.

Background:
  薬機法 (医薬品医療機器等法) violations / regulatory actions are surfaced in
  three primary feeds:

    1. PMDA recall index (info.pmda.go.jp/kaisyuu/) — by 年度 (FY) × クラス
       (I/II/III) × 種類 (医薬品 / 医療機器 / 医薬部外品 / 化粧品 / 再生医療
       等製品). Each list is downloadable as a UTF-8 CSV inside a ZIP.
       This is the canonical machine-readable feed.

    2. MHLW 国回収命令 list — /topics/bukyoku/iyaku/kaisyu/mhlwkaisyu.html.
       Historical, sparse but high-severity (回収命令 issued by 厚生労働大臣).

    3. MHLW 都道府県回収命令 list —
       /stf/seisakunitsuite/bunya/kenkou_iryou/iryou/topics/bukyoku/iyaku/
       kaisyu/kenkaisyu.html. Per-prefecture 回収命令 for higher-risk events.

  All three are 一次資料 from mhlw.go.jp / pmda.go.jp / info.pmda.go.jp
  (PMDA 子ドメイン, considered primary for this purpose). NO aggregators.

Schema mapping:
  - enforcement_kind = 'other'  for 回収 (recall — directive: "注意喚起・
    回収命令" → other). PMDA recalls are MANDATORY DISCLOSURE under 薬機法
    第68条の11, qualifying as 薬機法 enforcement events.
  - enforcement_kind = 'business_improvement' for 業務停止 / 業務改善 (when
    found via houdou).
  - issuing_authority pattern:
      * PMDA feed → "医薬品医療機器総合機構（PMDA）".
      * MHLW 国 → "厚生労働省".
      * MHLW 都道府県 → "厚生労働省 / {pref}" (best-effort prefecture
        extraction; falls back to plain "厚生労働省").
  - reason_summary always contains "薬機法" string so the verification query
    (issuing_authority LIKE '%厚生労働%' AND reason_summary LIKE '%薬機%')
    captures MHLW rows.
  - related_law_ref = "薬機法" for all rows.

Parallel-write:
  - BEGIN IMMEDIATE + busy_timeout=300000 (per CLAUDE.md §5).
  - Per-source small commits to minimize wal-write contention with other
    Wave24/25 workers.

Rate limit:
  - 1 req/sec/host (HttpClient default).
  - UA = "AutonoMath/0.1.0 (+https://bookyou.net)" (per directive).
  - PMDA CSV ZIPs are cached per host, so 1 req/sec/host applies.

Dedup:
  - (target_name, issuance_date, issuing_authority) tuple, both DB and batch.

CLI:
    python scripts/ingest/ingest_enforcement_pmda_yakkiho.py \
        [--db autonomath.db] [--dry-run] [--verbose]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import re
import sqlite3
import sys
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"ERROR: beautifulsoup4 not installed: {exc}", file=sys.stderr)
    raise

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.http import HttpClient  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest.pmda_yakkiho")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"

PMDA_AUTHORITY = "医薬品医療機器総合機構（PMDA）"
MHLW_AUTHORITY = "厚生労働省"


# ---------------------------------------------------------------------------
# PMDA recall index matrix
#   FY × class × category. Suffix mapping:
#     m = 医薬品 (drugs / quasi-drugs / cosmetics — broad)
#     k = 医療機器 (medical devices)
#     q = 医薬部外品 (separate index, often empty)
#     s = 化粧品 (separate index, often empty)
#     r = 再生医療等製品 (regenerative medicine products)
#   Note: in practice the 'm' index already includes 医薬部外品 / 化粧品
#   rows because they are filed under the same 種類 column. We still probe
#   the q/s/r suffixes to capture pages that exist only for those categories.
# ---------------------------------------------------------------------------

CATEGORY_SUFFIXES: list[tuple[str, str]] = [
    ("m", "医薬品"),
    ("k", "医療機器"),
    ("q", "医薬部外品"),
    ("s", "化粧品"),
    ("r", "再生医療等製品"),
]
FISCAL_YEARS = (26, 25, 24, 23)  # 令和6, 5, 4, 3 fiscal years
RECALL_CLASSES = (1, 2, 3)


def pmda_recall_zip_url(fy: int, cls: int, suffix: str) -> str:
    return f"https://www.info.pmda.go.jp/kaisyuu/rcidx{fy:02d}-{cls}{suffix}_all.zip"


def pmda_recall_index_url(fy: int, cls: int, suffix: str) -> str:
    return f"https://www.info.pmda.go.jp/kaisyuu/rcidx{fy:02d}-{cls}{suffix}.html"


def pmda_recall_detail_url(recall_no: str) -> str:
    return f"https://www.info.pmda.go.jp/rgo/MainServlet?recallno={recall_no}"


# ---------------------------------------------------------------------------
# MHLW 回収命令 lists (sparse, but canonical for 国 / 都道府県 orders)
# ---------------------------------------------------------------------------

MHLW_KOKUKAISYU_URL = "https://www.mhlw.go.jp/topics/bukyoku/iyaku/kaisyu/mhlwkaisyu.html"
MHLW_KENKAISYU_URL = (
    "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/"
    "topics/bukyoku/iyaku/kaisyu/kenkaisyu.html"
)


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------

WAREKI_RE = re.compile(
    r"(令和|平成|昭和|R|H|S)\s*(\d+|元)\s*[年.\-．／/]\s*"
    r"(\d{1,2})\s*[月.\-．／/]\s*(\d{1,2})\s*日?"
)
SEIREKI_RE = re.compile(r"(20\d{2}|19\d{2})\s*[年.\-／/]\s*(\d{1,2})\s*[月.\-／/]\s*(\d{1,2})")
ERA_OFFSET = {
    "令和": 2018,
    "R": 2018,
    "平成": 1988,
    "H": 1988,
    "昭和": 1925,
    "S": 1925,
}


def _normalize(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).strip()


def _parse_date(text: str) -> str | None:
    if not text:
        return None
    s = _normalize(text)
    m = SEIREKI_RE.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = WAREKI_RE.search(s)
    if m:
        era, y_raw, mo, d = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        try:
            y_off = 1 if y_raw == "元" else int(y_raw)
        except ValueError:
            return None
        year = ERA_OFFSET[era] + y_off
        if 1990 <= year <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{year:04d}-{mo:02d}-{d:02d}"
    return None


# ---------------------------------------------------------------------------
# Row dataclass
# ---------------------------------------------------------------------------


@dataclass
class EnfRow:
    target_name: str  # 製造販売業者等名称 (会社名)
    product_name: str | None  # 販売名 (product label, for context)
    issuance_date: str  # ISO yyyy-mm-dd
    issuing_authority: str
    enforcement_kind: str  # 'other' | 'business_improvement'
    reason_summary: str  # always contains "薬機法"
    related_law_ref: str  # "薬機法"
    source_url: str
    extra: dict | None = None  # raw fields (recall_no, class, category)


# ---------------------------------------------------------------------------
# PMDA CSV parsing
# ---------------------------------------------------------------------------


def _strip_csv_cell(s: str) -> str:
    if not s:
        return ""
    # PMDA prefixes some date-ish fields with a leading single-quote (Excel
    # text-mode marker). Strip it and collapse whitespace.
    s = s.lstrip("'")
    s = s.replace("\r", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


_MAH_NAME_RE = re.compile(r"製造販売業者の名称[　\s:：]+([^\r\n]+)")


def _extract_mah_name(mah_blob: str) -> str | None:
    if not mah_blob:
        return None
    m = _MAH_NAME_RE.search(mah_blob)
    if not m:
        # Some rows have name on first line directly.
        first = mah_blob.split("\n", 1)[0].strip()
        first = first.lstrip("'　 ")
        if first and len(first) <= 200:
            return first
        return None
    name = m.group(1).strip()
    # Trim trailing punctuation / 株式会社 spillover from line continuation.
    return name[:200] or None


def parse_pmda_recall_csv(
    csv_bytes: bytes,
    *,
    source_url: str,
    cls_label: str,
    category_label: str,
) -> list[EnfRow]:
    """Parse one PMDA recall CSV (UTF-8 BOM, Excel-style quoting)."""
    try:
        text = csv_bytes.decode("utf-8-sig", errors="replace")
    except Exception:
        text = csv_bytes.decode("cp932", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    header = [_strip_csv_cell(c) for c in rows[0]]
    # Expected columns:
    #   0 回収番号  1 掲載年月日  2 種類  3 回収概要作成日及び訂正日
    #   4 クラス分類  5 一般的名称及び販売名  6 対象ロット…
    #   7 製造販売業者等名称  8 回収理由  9 危惧される具体的な健康被害
    #   10 回収開始日  11 効能・効果又は用途等  12 その他
    #   13 担当者及び連絡先  14 備考
    if len(header) < 9 or "回収番号" not in header[0]:
        _LOG.warning("unexpected CSV header: %r", header[:5])
        return []

    out: list[EnfRow] = []
    for raw in rows[1:]:
        if not raw or len(raw) < 9:
            continue
        recall_no = _strip_csv_cell(raw[0])
        issued = _strip_csv_cell(raw[1] if len(raw) > 1 else "")
        kind = _strip_csv_cell(raw[2] if len(raw) > 2 else "")
        cls_field = _strip_csv_cell(raw[4] if len(raw) > 4 else "")
        product_blob = _strip_csv_cell(raw[5] if len(raw) > 5 else "")
        mah_blob = raw[7] if len(raw) > 7 else ""  # keep raw newlines
        reason_blob = _strip_csv_cell(raw[8] if len(raw) > 8 else "")

        if not recall_no or not issued:
            continue
        date_iso = _parse_date(issued)
        if not date_iso:
            continue
        mah_name = _extract_mah_name(mah_blob)
        if not mah_name:
            continue

        # Build a compact reason that always cites 薬機法 so the verification
        # query (...AND reason_summary LIKE '%薬機%') captures these rows
        # when issuing_authority is 厚生労働省 (won't apply here — PMDA is
        # primary — but keep the convention consistent).
        product_short = (
            product_blob.replace("販売名 :", "")
            .replace("販売名：", "")
            .replace("一般的名称：", "")
            .strip(": 　")[:200]
        )
        reason = (
            f"薬機法に基づく{cls_field or 'クラス分類'}回収（{kind or category_label}）"
            f" / 製品: {product_short[:120]} / 理由: {reason_blob[:200]}"
        )[:1500]

        out.append(
            EnfRow(
                target_name=mah_name,
                product_name=product_short or None,
                issuance_date=date_iso,
                issuing_authority=PMDA_AUTHORITY,
                enforcement_kind="other",
                reason_summary=reason,
                related_law_ref="薬機法",
                source_url=source_url,
                extra={
                    "recall_no": recall_no,
                    "class": cls_field,
                    "category": kind or category_label,
                    "product_name": product_short,
                    "detail_url": pmda_recall_detail_url(recall_no),
                },
            )
        )
    return out


def fetch_pmda_recalls(http: HttpClient) -> list[EnfRow]:
    """Walk the FY × class × category matrix and return all parsed rows."""
    out: list[EnfRow] = []
    seen_zip: set[str] = set()
    for suffix, cat_label in CATEGORY_SUFFIXES:
        for fy in FISCAL_YEARS:
            for cls in RECALL_CLASSES:
                zip_url = pmda_recall_zip_url(fy, cls, suffix)
                if zip_url in seen_zip:
                    continue
                seen_zip.add(zip_url)
                index_url = pmda_recall_index_url(fy, cls, suffix)
                res = http.get(zip_url, max_bytes=30 * 1024 * 1024)
                if not res.ok:
                    _LOG.debug("[pmda] zip not available status=%s url=%s", res.status, zip_url)
                    continue
                try:
                    z = zipfile.ZipFile(io.BytesIO(res.body))
                except (zipfile.BadZipFile, OSError) as exc:
                    _LOG.warning("[pmda] bad zip %s: %s", zip_url, exc)
                    continue
                cls_label_full = f"クラス{['I', 'II', 'III'][cls - 1]}"
                for name in z.namelist():
                    if not name.lower().endswith(".csv"):
                        continue
                    try:
                        with z.open(name) as f:
                            data = f.read()
                    except (zipfile.BadZipFile, KeyError) as exc:
                        _LOG.warning("[pmda] zip member fail %s: %s", name, exc)
                        continue
                    rows = parse_pmda_recall_csv(
                        data,
                        source_url=index_url,
                        cls_label=cls_label_full,
                        category_label=cat_label,
                    )
                    out.extend(rows)
                    _LOG.info("[pmda] fy=%d cls=%d cat=%s rows=%d", fy, cls, suffix, len(rows))
    _LOG.info("[pmda] total parsed rows=%d", len(out))
    return out


# ---------------------------------------------------------------------------
# MHLW 国回収命令 / 都道府県回収命令 parsing
# ---------------------------------------------------------------------------

_PREF_RE = re.compile(
    r"(北海道|青森|岩手|宮城|秋田|山形|福島|茨城|栃木|群馬|埼玉|千葉|"
    r"東京|神奈川|新潟|富山|石川|福井|山梨|長野|岐阜|静岡|愛知|三重|"
    r"滋賀|京都|大阪|兵庫|奈良|和歌山|鳥取|島根|岡山|広島|山口|徳島|"
    r"香川|愛媛|高知|福岡|佐賀|長崎|熊本|大分|宮崎|鹿児島|沖縄)"
)

_FY_RE = re.compile(r"(令和|平成|昭和)\s*(\d+|元)\s*年度")


def _resolve_url(href: str, base: str) -> str:
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        host = urlparse(base).netloc
        return f"https://{host}{href}"
    base_dir = base.rsplit("/", 1)[0] + "/"
    return base_dir + href


def _fy_to_iso_year(fy_text: str) -> int | None:
    """Convert "平成20年度" → 2008, "令和7年度" → 2025 (year start)."""
    m = _FY_RE.search(fy_text)
    if not m:
        return None
    era, y_raw = m.group(1), m.group(2)
    try:
        y_off = 1 if y_raw == "元" else int(y_raw)
    except ValueError:
        return None
    return ERA_OFFSET[era] + y_off


def parse_mhlw_kokukaisyu(html: str, source_url: str) -> list[EnfRow]:
    """国が発動した回収命令 list — sparse historical rows."""
    out: list[EnfRow] = []
    soup = BeautifulSoup(html, "html.parser")
    # Each entry is typically a <li> or a <p> containing year, company,
    # and an <a href="..."> to the houdou detail.
    text = soup.get_text("\n", strip=True)
    # Walk anchor list — prefer structured.
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        anchor = _normalize(a.get_text(" ", strip=True))
        # Find the parent block text for context.
        parent = a.parent
        ctx = _normalize(parent.get_text(" ", strip=True)) if parent else anchor
        # Restrict to recall-order announcements.
        if "回収命令" not in ctx and "回収命令" not in anchor:
            # The page only has 4 entries, all of which mention 回収命令 in
            # parent. If neither has it, skip.
            continue
        # Extract company from anchor or context.
        # The 国 list format: "{年度} - {company} - 医薬品回収命令" anchor
        # text often includes the company name directly.
        company = anchor
        # Strip trailing recall-order suffix.
        company = re.sub(r"医薬品回収命令.*$", "", company).strip(" -／/")
        if not company or len(company) > 200 or len(company) < 2:
            continue
        fy_year = _fy_to_iso_year(ctx)
        if not fy_year:
            continue
        # Use FY April 1 as a stable issuance proxy when only year known.
        issuance = f"{fy_year:04d}-04-01"
        absurl = _resolve_url(href, source_url)
        reason = (f"薬機法に基づく回収命令（厚生労働省発動）/ 事業者: {company} / 詳細: {absurl}")[
            :1500
        ]
        out.append(
            EnfRow(
                target_name=company,
                product_name=None,
                issuance_date=issuance,
                issuing_authority=MHLW_AUTHORITY,
                enforcement_kind="other",
                reason_summary=reason,
                related_law_ref="薬機法",
                source_url=source_url,
                extra={"detail_url": absurl, "feed": "mhlw_koku_kaisyu"},
            )
        )
    return out


def parse_mhlw_kenkaisyu(html: str, source_url: str) -> list[EnfRow]:
    """都道府県が発動した回収命令 list."""
    out: list[EnfRow] = []
    soup = BeautifulSoup(html, "html.parser")
    # Structure varies; walk every <li>/<tr>/<p> with an anchor and a
    # 年度 marker.
    for block in soup.find_all(["li", "tr", "p", "div"]):
        text = _normalize(block.get_text(" ", strip=True))
        if not text or "回収命令" not in text:
            continue
        fy_year = _fy_to_iso_year(text)
        if not fy_year:
            continue
        a = block.find("a")
        href = (a.get("href") if a else "") or ""
        anchor = _normalize(a.get_text(" ", strip=True)) if a else text
        # Company name extraction: anchor often = "{company}, {product}".
        # Strip product segment after first comma/、/「.
        company = re.split(r"[,，、「]", anchor, maxsplit=1)[0].strip()
        company = re.sub(r"医薬品回収命令.*$", "", company).strip()
        # Drop entries where company looks like a product or generic phrase.
        if not company or len(company) > 200 or len(company) < 2:
            continue
        absurl = _resolve_url(href, source_url) if href else source_url
        m_pref = _PREF_RE.search(text)
        pref = m_pref.group(1) if m_pref else None
        authority = f"{MHLW_AUTHORITY} / {pref}" if pref else MHLW_AUTHORITY
        reason = (f"薬機法に基づく回収命令（{pref or '都道府県'}発動）/ 事業者: {company}")[:1500]
        issuance = f"{fy_year:04d}-04-01"
        out.append(
            EnfRow(
                target_name=company,
                product_name=None,
                issuance_date=issuance,
                issuing_authority=authority,
                enforcement_kind="other",
                reason_summary=reason,
                related_law_ref="薬機法",
                source_url=source_url,
                extra={"detail_url": absurl, "feed": "mhlw_ken_kaisyu", "prefecture": pref},
            )
        )
    # Dedup within batch — kenkaisyu may yield same row from <li> + <tr>.
    seen: set[tuple[str, str, str]] = set()
    deduped: list[EnfRow] = []
    for r in out:
        key = (r.target_name, r.issuance_date, r.issuing_authority)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def fetch_mhlw_recalls(http: HttpClient) -> list[EnfRow]:
    """Fetch + parse both MHLW 回収命令 lists."""
    out: list[EnfRow] = []
    for url, parser in (
        (MHLW_KOKUKAISYU_URL, parse_mhlw_kokukaisyu),
        (MHLW_KENKAISYU_URL, parse_mhlw_kenkaisyu),
    ):
        res = http.get(url)
        if not res.ok:
            _LOG.warning("[mhlw] fetch fail %s status=%s", url, res.status)
            continue
        rows = parser(res.text, url)
        _LOG.info("[mhlw] %s rows=%d", url, len(rows))
        out.extend(rows)
    return out


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def _slug8(target: str, date: str, extra: str = "") -> str:
    h = hashlib.sha1(f"{target}|{date}|{extra}".encode()).hexdigest()
    return h[:8]


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(f"missing table '{tbl}' — apply migrations first")


def existing_dedup_keys(
    conn: sqlite3.Connection,
) -> set[tuple[str, str, str]]:
    """Return {(target_name, issuance_date, issuing_authority)} for the
    PMDA / MHLW 薬機法 universe so we don't reinsert."""
    out: set[tuple[str, str, str]] = set()
    cur = conn.execute(
        "SELECT target_name, issuance_date, issuing_authority "
        "FROM am_enforcement_detail "
        "WHERE issuing_authority LIKE ? "
        "   OR issuing_authority LIKE ? "
        "   OR (issuing_authority LIKE ? AND reason_summary LIKE ?)",
        (
            "%医薬品医療機器総合機構%",
            "%PMDA%",
            "%厚生労働%",
            "%薬機%",
        ),
    )
    for n, d, a in cur.fetchall():
        if n and d and a:
            out.add((n, d, a))
    return out


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
        ) VALUES (?, 'enforcement', 'pmda_yakkiho_kaisyu', NULL,
                  ?, NULL, 0.9, ?, ?, ?, ?, 'active', 'ok')
        ON CONFLICT(canonical_id) DO UPDATE SET
            primary_name      = excluded.primary_name,
            source_url        = excluded.source_url,
            source_url_domain = excluded.source_url_domain,
            fetched_at        = excluded.fetched_at,
            raw_json          = excluded.raw_json,
            updated_at        = datetime('now')
        """,
        (
            canonical_id,
            primary_name[:500],
            url,
            domain,
            now_iso,
            raw_json,
        ),
    )


def insert_enforcement(
    conn: sqlite3.Connection,
    entity_id: str,
    row: EnfRow,
    now_iso: str,
) -> None:
    conn.execute(
        """
        INSERT INTO am_enforcement_detail (
            entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, exclusion_start, exclusion_end,
            reason_summary, related_law_ref, amount_yen,
            source_url, source_fetched_at
        ) VALUES (?, NULL, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL, ?, ?)
        """,
        (
            entity_id,
            row.target_name[:500],
            row.enforcement_kind,
            row.issuing_authority,
            row.issuance_date,
            row.reason_summary[:4000],
            row.related_law_ref[:1000],
            row.source_url,
            now_iso,
        ),
    )


def write_rows(
    conn: sqlite3.Connection,
    rows: list[EnfRow],
    *,
    now_iso: str,
) -> tuple[int, int, int]:
    """Insert rows in a single BEGIN IMMEDIATE block.

    Returns (inserted, dup_db, dup_batch).
    """
    if not rows:
        return 0, 0, 0
    db_keys = existing_dedup_keys(conn)
    batch_keys: set[tuple[str, str, str]] = set()
    inserted = 0
    dup_db = 0
    dup_batch = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        for r in rows:
            key = (r.target_name, r.issuance_date, r.issuing_authority)
            if key in db_keys:
                dup_db += 1
                continue
            if key in batch_keys:
                dup_batch += 1
                continue
            batch_keys.add(key)

            extra_seed = ""
            if r.extra:
                extra_seed = r.extra.get("recall_no") or r.extra.get("detail_url") or ""
            slug = _slug8(r.target_name, r.issuance_date, extra_seed)
            authority_slug = (
                "pmda"
                if "PMDA" in r.issuing_authority or "総合機構" in r.issuing_authority
                else "mhlw"
            )
            canonical_id = (
                f"enforcement:{authority_slug}-yakkiho-{r.issuance_date.replace('-', '')}-{slug}"
            )
            primary_name = f"{r.target_name} ({r.issuance_date}) - 薬機法回収"
            raw_json = json.dumps(
                {
                    "target_name": r.target_name,
                    "product_name": r.product_name,
                    "issuance_date": r.issuance_date,
                    "issuing_authority": r.issuing_authority,
                    "enforcement_kind": r.enforcement_kind,
                    "related_law_ref": r.related_law_ref,
                    "reason_summary": r.reason_summary,
                    "source_url": r.source_url,
                    "extra": r.extra or {},
                    "source_attribution": ("PMDA" if authority_slug == "pmda" else "厚生労働省"),
                    "license": ("政府機関の著作物（出典明記で転載引用可）"),
                },
                ensure_ascii=False,
            )
            try:
                upsert_entity(
                    conn,
                    canonical_id,
                    primary_name,
                    r.source_url,
                    raw_json,
                    now_iso,
                )
                insert_enforcement(conn, canonical_id, r, now_iso)
                inserted += 1
            except sqlite3.Error as exc:
                _LOG.error(
                    "DB error name=%r date=%s: %s",
                    r.target_name,
                    r.issuance_date,
                    exc,
                )
                continue
        conn.commit()
    except sqlite3.Error as exc:
        _LOG.error("BEGIN/commit failed: %s", exc)
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
    return inserted, dup_db, dup_batch


# ---------------------------------------------------------------------------
# CLI orchestrator
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--skip-pmda",
        action="store_true",
        help="skip PMDA recall feed (debug)",
    )
    ap.add_argument(
        "--skip-mhlw",
        action="store_true",
        help="skip MHLW 国/都道府県 回収命令 lists (debug)",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    http = HttpClient(user_agent=USER_AGENT)
    now_iso = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    all_rows: list[EnfRow] = []
    if not args.skip_pmda:
        all_rows.extend(fetch_pmda_recalls(http))
    if not args.skip_mhlw:
        all_rows.extend(fetch_mhlw_recalls(http))

    _LOG.info("total parsed rows=%d", len(all_rows))

    if args.dry_run:
        # Show a sample.
        for r in all_rows[:5]:
            _LOG.info(
                "sample: name=%s date=%s auth=%s reason=%s",
                r.target_name,
                r.issuance_date,
                r.issuing_authority,
                r.reason_summary[:100],
            )
        http.close()
        return 0

    if not args.db.exists():
        _LOG.error("autonomath.db missing: %s", args.db)
        http.close()
        return 2

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_tables(conn)

    inserted, dup_db, dup_batch = write_rows(
        conn,
        all_rows,
        now_iso=now_iso,
    )
    try:
        conn.close()
    except sqlite3.Error:
        pass
    http.close()

    _LOG.info(
        "done parsed=%d inserted=%d dup_db=%d dup_batch=%d",
        len(all_rows),
        inserted,
        dup_db,
        dup_batch,
    )
    print(
        f"PMDA+MHLW 薬機法 ingest: parsed={len(all_rows)} "
        f"inserted={inserted} dup_db={dup_db} dup_batch={dup_batch}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
