#!/usr/bin/env python3
"""Ingest 私立学校法 / 学校教育法 / 私立学校振興助成法 違反による行政処分.

Scope (per directive 2026-04-25):
  - 私立大学等経常費補助金 不交付 / 減額 (日本私立学校振興・共済事業団 公表)
    --> 学校法人 X / 学校 Y, 取扱い (不交付 / N% 減額交付), 事由
  - 文部科学大臣 解散命令 (私立学校法第62条第1項) — 堀越学園 案件
  - その他 MEXT 公表の改善命令 / 認可取消 (any future hits)

Sources walked:
  PRIMARY (multi-row, high yield):
    1. https://www.shigaku.go.jp/files/s_hojo_h25.pdf .. r06.pdf (12 PDFs)
       Each contains 「表6 (or 表7) 減額又は不交付法人一覧」.
  PRIMARY (single events):
    2. https://www.mext.go.jp/a_menu/koutou/shinkou/07021403/1332588.htm
       学校法人堀越学園に対する解散命令 (2013-03-28)

Schema mapping (am_enforcement_detail):
  - enforcement_kind:
      "不交付" / "減額" → 'grant_refund' (subsidy non-disbursement / reduction)
      "解散命令" / "認可取消" → 'license_revoke'
      "改善命令" → 'business_improvement'
      "管理運営不適正 ヒアリング" → 'investigation'
  - issuing_authority:
      shigaku-bg → '日本私立学校振興・共済事業団'
      MEXT-bg → '文部科学省'
      都道府県知事-bg → '<県名>知事'
  - related_law_ref:
      補助金関係 → "私立学校振興助成法第12条" (when 不交付 reasoning involves
        管理運営不適正) and "私立大学等経常費補助金取扱要領4(1)"
      解散命令 → "私立学校法第62条第1項"
      改善命令 → "私立学校法第60条" (旧法) or "私立学校法第133条" (令和5年改正
        後) — date-dependent.

Idempotent dedup key:
  canonical_id = "enforcement:shigaku:{year_num}:{hojin_slug}:{school_slug}"
  Re-runs UPDATE row for the same year+法人+学校.

Parallel-safe: BEGIN IMMEDIATE + busy_timeout=300000 (per §5).

License: shigaku.go.jp は MEXT 関連の独立行政機関、公表資料は出典明記で
転載/引用可。raw_json に source_attribution + license フィールド付与。

CLI:
    python scripts/ingest/ingest_enforcement_shigaku.py \
        [--db autonomath.db] [--limit N] [--dry-run] [--verbose]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    import pdfplumber  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"ERROR: pdfplumber not installed: {exc}", file=sys.stderr)
    raise

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.http import HttpClient  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest.shigaku")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"

AUTHORITY_SHIGAKU = "authority:shigaku"
AUTHORITY_MEXT = "authority:mext"


# ---------------------------------------------------------------------------
# Source list
# ---------------------------------------------------------------------------

# 12 yearly PDFs from 私学事業団. Filename pattern: s_hojo_<year>.pdf
SHIGAKU_PDFS: list[dict[str, object]] = [
    {
        "slug": "h25",
        "year_label": "平成25年度",
        "year_num": 2013,
        "url": "https://www.shigaku.go.jp/files/s_hojo_h25.pdf",
    },
    {
        "slug": "h26",
        "year_label": "平成26年度",
        "year_num": 2014,
        "url": "https://www.shigaku.go.jp/files/s_hojo_h26.pdf",
    },
    {
        "slug": "h27",
        "year_label": "平成27年度",
        "year_num": 2015,
        "url": "https://www.shigaku.go.jp/files/s_hojo_h27.pdf",
    },
    {
        "slug": "h28",
        "year_label": "平成28年度",
        "year_num": 2016,
        "url": "https://www.shigaku.go.jp/files/s_hojo_h28.pdf",
    },
    {
        "slug": "h29",
        "year_label": "平成29年度",
        "year_num": 2017,
        "url": "https://www.shigaku.go.jp/files/s_hojo_h29.pdf",
    },
    {
        "slug": "h30",
        "year_label": "平成30年度",
        "year_num": 2018,
        "url": "https://www.shigaku.go.jp/files/s_hojo_h30.pdf",
    },
    {
        "slug": "r01",
        "year_label": "令和元年度",
        "year_num": 2019,
        "url": "https://www.shigaku.go.jp/files/s_hojo_r01.pdf",
    },
    {
        "slug": "r02",
        "year_label": "令和2年度",
        "year_num": 2020,
        "url": "https://www.shigaku.go.jp/files/s_hojo_r02.pdf",
    },
    {
        "slug": "r03",
        "year_label": "令和3年度",
        "year_num": 2021,
        "url": "https://www.shigaku.go.jp/files/s_hojo_r03.pdf",
    },
    {
        "slug": "r04",
        "year_label": "令和4年度",
        "year_num": 2022,
        "url": "https://www.shigaku.go.jp/files/s_hojo_r04.pdf",
    },
    {
        "slug": "r05",
        "year_label": "令和5年度",
        "year_num": 2023,
        "url": "https://www.shigaku.go.jp/files/s_hojo_r05.pdf",
    },
    {
        "slug": "r06",
        "year_label": "令和6年度",
        "year_num": 2024,
        "url": "https://www.shigaku.go.jp/files/s_hojo_r06.pdf",
    },
]

# Single event: MEXT 解散命令 (堀越学園, 2013-03-28).
MEXT_ONE_OFFS: list[dict[str, object]] = [
    {
        "slug": "horikoshi-2013",
        "url": "https://www.mext.go.jp/a_menu/koutou/shinkou/07021403/1332588.htm",
        "issuing_authority": "文部科学省",
        "authority_canonical": AUTHORITY_MEXT,
        "issuance_date": "2013-03-28",
        "hojin_name": "学校法人堀越学園",
        "school_names": ["創造学園大学", "堀越学園"],
        "enforcement_kind": "license_revoke",
        "related_law_ref": "私立学校法第62条第1項",
        "reason_summary": (
            "学校法人堀越学園は、私立学校法（昭和24年法律第270号）等の規定に違反し、"
            "他の方法により監督の目的を達することができないため、同法第62条第1項の"
            "規定に基づき、文部科学大臣により解散を命じられた。必要な財産が保有されて"
            "いないなど、私立学校法の違反が解消される見込みがなく、学生等に予期せぬ"
            "不利益が生じかねない状況にあったため、解散命令の手続が開始された。"
        ),
        "source_attribution": "文部科学省ウェブサイト",
        "license": "政府機関の著作物（出典明記で転載引用可）",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm(s: str | None) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s.replace("\n", " ")).strip()


def _to_clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", _norm(s))


def _strip_inner_spaces(s: str) -> str:
    """Remove ALL whitespace (typical 私学事業団 PDF column spacing artifact)."""
    return re.sub(r"\s+", "", _norm(s))


def split_schools(s: str) -> list[str]:
    """Split a 'X大学 Y短期大学部' string into per-school tokens.

    Strategy: walk left-to-right, at each position find the EARLIEST
    end-position where any school-suffix keyword fits, preferring the
    longest matching keyword if multiple start at the same position.
    """
    s = _strip_inner_spaces(s)
    keywords = [
        "大学院大学",
        "短期大学部",
        "短期大学",
        "大学",
        "高等専門学校",
        "高等学校",
        "高校",
        "専門学校",
    ]
    out: list[str] = []
    pos = 0
    while pos < len(s):
        chosen_end: int | None = None
        scan = pos
        while scan < len(s):
            matched_end: int | None = None
            for kw in keywords:
                if s.startswith(kw, scan):
                    matched_end = scan + len(kw)
                    break
            if matched_end is not None:
                chosen_end = matched_end
                break
            scan += 1
        if chosen_end is None:
            tail = s[pos:].strip()
            if tail:
                out.append(tail)
            break
        chunk = s[pos:chosen_end].strip()
        if chunk:
            out.append(chunk)
        pos = chosen_end
    return out


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


_TREATMENT_PCT_RE = re.compile(r"(\d{1,3})\s*%")


def classify_kind_from_treatment(treatment: str) -> str:
    """Map shigaku 取扱い text → am_enforcement_kind enum.

    不交付 / 減額 are both treated as 'grant_refund' since they represent
    subsidy adjustments based on 私立学校振興助成法第12条 / 取扱要領4(1).
    The percentage / 不交付 distinction is preserved in raw_json.
    """
    t = _strip_inner_spaces(treatment)
    if "不交付" in t:
        return "grant_refund"
    if "減額" in t:
        return "grant_refund"
    return "other"


def reduction_pct(treatment: str) -> int | None:
    """Extract reduction percentage if present (10/25/50/75 etc)."""
    t = _strip_inner_spaces(treatment)
    m = _TREATMENT_PCT_RE.search(t)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    if "不交付" in t:
        return 100
    return None


def detect_law_basis(jiyu: str, treatment: str) -> str:
    """Return canonical 法令条文 reference for shigaku 助成 cases.

    All shigaku 不交付/減額 are issued under 私立学校振興助成法第12条
    (補助金の減額・不交付・返還) operationalized via 経常費補助金取扱要領
    4(1). Reasons (役員の刑事処分 / 入学者選抜の不適切 / 管理運営不適正)
    typically also cite 私立学校法 第60条 (改正前) or 第133条 (改正後)
    for the underlying 不適正 finding, but these only attach when a
    parallel administrative order is on record.
    """
    base = "私立学校振興助成法第12条 / 私立大学等経常費補助金取扱要領4(1)"
    j = _strip_inner_spaces(jiyu)
    extras = []
    if "刑事処分" in j or "刑事" in j:
        extras.append("私立学校法第63条の2 (改正前)")
    if "管理運営" in j or "管理運営不適正" in j or "適正を欠く" in j:
        extras.append("私立学校法第60条")
    if extras:
        return base + " / " + " / ".join(extras)
    return base


# ---------------------------------------------------------------------------
# Row dataclass
# ---------------------------------------------------------------------------


@dataclass
class ShigakuRow:
    year_label: str
    year_num: int
    hojin_name: str
    school_name: str
    treatment: str
    treatment_pct: int | None
    jiyu: str
    enforcement_kind: str
    related_law_ref: str
    section_label: str | None
    source_url: str
    source_slug: str

    # Synthesized
    issuance_date: str  # YYYY-04-01 (年度初日 as proxy; PDFs published in March)
    issuing_authority: str = "日本私立学校振興・共済事業団"
    authority_canonical: str = AUTHORITY_SHIGAKU


# ---------------------------------------------------------------------------
# PDF parser
# ---------------------------------------------------------------------------


def parse_shigaku_pdf(
    pdf_bytes: bytes,
    *,
    year_label: str,
    year_num: int,
    source_url: str,
    source_slug: str,
) -> list[ShigakuRow]:
    """Parse one annual shigaku 表6/表7 PDF, return per-school rows."""
    rows: list[ShigakuRow] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            # We track section labels by scanning each page text and
            # recording the most recent (Ⅰ) / (1) / (２) parenthesis
            # subheader within the table-context page. For now, we tag
            # all rows of a page with the latest such label.
            for page in pdf.pages:
                txt = page.extract_text() or ""
                # Identify section sub-label: "（１）新規に減額措置を講じた法人"
                section_label = None
                section_match = re.findall(
                    r"（[一二三四五六七８１２３４５６７０-９0-9]+）\s*([^（）\n]{4,80})",
                    txt,
                )
                if section_match:
                    # Take the LAST occurrence on the page as the most
                    # local context — table immediately follows.
                    last_label = section_match[-1].strip()
                    section_label = re.sub(r"\s+", "", last_label)[:60]
                tables = page.extract_tables() or []
                for tbl in tables:
                    if not tbl or len(tbl) < 2 or not tbl[0]:
                        continue
                    first_cells = "".join(
                        (c or "").replace("\n", "").replace(" ", "").replace("　", "")
                        for c in tbl[0]
                    )
                    if "法人名" not in first_cells or "対象学校名" not in first_cells:
                        continue
                    # Header row found, parse data rows
                    for r in tbl[1:]:
                        if r is None:
                            continue
                        cols = [_to_clean(c) for c in r]
                        if len(cols) < 4:
                            continue
                        # Column layout variants:
                        #   5 cols: [idx, hojin, schools, treatment, jiyu]
                        #   4 cols: [hojin, schools, treatment, jiyu]
                        if cols[0].isdigit():
                            if len(cols) < 5:
                                continue
                            hojin, schools, treatment, jiyu = (cols[1], cols[2], cols[3], cols[4])
                        else:
                            hojin, schools, treatment, jiyu = (cols[0], cols[1], cols[2], cols[3])
                        if not hojin or not schools or "法人名" in hojin:
                            continue
                        # Strip column-spacing artifacts in name fields
                        hojin = _strip_inner_spaces(hojin)
                        treatment_clean = _strip_inner_spaces(treatment)
                        jiyu_clean = _to_clean(jiyu)
                        kind = classify_kind_from_treatment(treatment_clean)
                        pct = reduction_pct(treatment_clean)
                        law_ref = detect_law_basis(jiyu_clean, treatment_clean)
                        # Per-year proxy date = April 1 of fiscal year
                        # (PDFs publish in March of following year, but
                        # 措置 is a 当年度 decision — 年度初日 is the most
                        # honest proxy).
                        issuance_date = f"{year_num:04d}-04-01"
                        for sch in split_schools(schools):
                            rows.append(
                                ShigakuRow(
                                    year_label=year_label,
                                    year_num=year_num,
                                    hojin_name=hojin,
                                    school_name=sch,
                                    treatment=treatment_clean,
                                    treatment_pct=pct,
                                    jiyu=jiyu_clean,
                                    enforcement_kind=kind,
                                    related_law_ref=law_ref,
                                    section_label=section_label,
                                    source_url=source_url,
                                    source_slug=source_slug,
                                    issuance_date=issuance_date,
                                )
                            )
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("shigaku pdf parse failed %s: %s", source_url, exc)
    return rows


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def _slug(s: str, n: int = 12) -> str:
    return hashlib.sha1(_norm(s).encode("utf-8")).hexdigest()[:n]


def _entity_canonical_id(bucket: str, year_num: int, hojin_name: str, school_name: str) -> str:
    """E.g. enforcement:shigaku:2024:<sha12-hojin>:<sha12-school>."""
    h = _slug(hojin_name, 10)
    s = _slug(school_name, 10)
    return f"enforcement:{bucket}:{year_num}:{h}:{s}"


def _entity_canonical_id_mext(slug: str, school_name: str) -> str:
    s = _slug(school_name, 10)
    return f"enforcement:mext:{slug}:{s}"


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(f"missing table '{tbl}' — apply migrations first")


def upsert_entity(
    conn: sqlite3.Connection,
    *,
    canonical_id: str,
    primary_name: str,
    source_url: str,
    raw_json: str,
    now_iso: str,
    authority_canonical: str,
    source_topic: str,
) -> None:
    domain = urlparse(source_url).netloc or None
    conn.execute(
        """
        INSERT INTO am_entities (
            canonical_id, record_kind, source_topic, source_record_index,
            primary_name, authority_canonical, confidence,
            source_url, source_url_domain, fetched_at, raw_json,
            canonical_status, citation_status
        ) VALUES (?, 'enforcement', ?, NULL,
                  ?, ?, 0.92, ?, ?, ?, ?, 'active', 'ok')
        ON CONFLICT(canonical_id) DO UPDATE SET
            primary_name        = excluded.primary_name,
            authority_canonical = excluded.authority_canonical,
            source_url          = excluded.source_url,
            source_url_domain   = excluded.source_url_domain,
            fetched_at          = excluded.fetched_at,
            raw_json            = excluded.raw_json,
            updated_at          = datetime('now')
        """,
        (
            canonical_id,
            source_topic,
            primary_name[:500],
            authority_canonical,
            source_url,
            domain,
            now_iso,
            raw_json,
        ),
    )


def upsert_enforcement(
    conn: sqlite3.Connection,
    *,
    entity_id: str,
    target_name: str,
    issuance_date: str,
    issuing_authority: str,
    enforcement_kind: str,
    reason_summary: str | None,
    related_law_ref: str | None,
    amount_yen: int | None,
    source_url: str,
    source_fetched_at: str,
) -> str:
    """Insert or replace the row keyed on entity_id (1:1 by design)."""
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
        ) VALUES (?, NULL, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?)
        """,
        (
            entity_id,
            target_name[:500],
            enforcement_kind,
            issuing_authority,
            issuance_date,
            (reason_summary or "")[:4000] or None,
            (related_law_ref or "")[:1000] or None,
            amount_yen,
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
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--limit", type=int, default=None, help="cap total inserts (debugging)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--max-sources", type=int, default=None, help="cap number of yearly PDFs walked"
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

    conn: sqlite3.Connection | None = None
    if not args.dry_run:
        if not args.db.exists():
            _LOG.error("autonomath.db missing: %s", args.db)
            return 2
        conn = sqlite3.connect(str(args.db))
        conn.execute("PRAGMA busy_timeout=300000")
        conn.execute("PRAGMA foreign_keys=ON")
        ensure_tables(conn)

    stats: dict[str, int] = {
        "pdfs_fetched": 0,
        "pdfs_failed": 0,
        "rows_parsed": 0,
        "rows_inserted": 0,
        "rows_updated": 0,
        "rows_skipped_dup": 0,
        "mext_inserted": 0,
        "mext_failed": 0,
    }
    by_year: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    sample_rows: list[dict[str, object]] = []

    def _flush(commit: bool = True) -> None:
        if conn is None:
            return
        if commit:
            conn.commit()

    # -- Phase 1: shigaku PDFs --------------------------------------------
    sources = SHIGAKU_PDFS[: args.max_sources] if args.max_sources else SHIGAKU_PDFS

    if conn is not None:
        conn.execute("BEGIN IMMEDIATE")

    try:
        for src in sources:
            if args.limit and stats["rows_inserted"] >= args.limit:
                _LOG.info("limit reached: %d", args.limit)
                break
            url = str(src["url"])
            slug = str(src["slug"])
            year_label = str(src["year_label"])
            year_num = int(src["year_num"])  # type: ignore[arg-type]

            _LOG.info("[%s] fetch %s", slug, url)
            res = http.get(url, max_bytes=15 * 1024 * 1024)
            if not res.ok:
                stats["pdfs_failed"] += 1
                _LOG.warning("[%s] fetch fail status=%s url=%s", slug, res.status, url)
                continue
            stats["pdfs_fetched"] += 1
            rows = parse_shigaku_pdf(
                res.body,
                year_label=year_label,
                year_num=year_num,
                source_url=url,
                source_slug=slug,
            )
            stats["rows_parsed"] += len(rows)
            _LOG.info("[%s] parsed=%d rows", slug, len(rows))

            for r in rows:
                if args.limit and stats["rows_inserted"] >= args.limit:
                    break
                canonical_id = _entity_canonical_id(
                    "shigaku", r.year_num, r.hojin_name, r.school_name
                )
                primary_name = (
                    f"{r.hojin_name} ({r.school_name}) — {r.year_label} 経常費補助金 {r.treatment}"
                )
                raw_json = json.dumps(
                    {
                        "year_label": r.year_label,
                        "year_num": r.year_num,
                        "hojin_name": r.hojin_name,
                        "school_name": r.school_name,
                        "treatment": r.treatment,
                        "treatment_pct": r.treatment_pct,
                        "section_label": r.section_label,
                        "jiyu": r.jiyu,
                        "enforcement_kind": r.enforcement_kind,
                        "related_law_ref": r.related_law_ref,
                        "issuance_date": r.issuance_date,
                        "issuing_authority": r.issuing_authority,
                        "authority_canonical": r.authority_canonical,
                        "source_url": r.source_url,
                        "source_slug": r.source_slug,
                        "source_attribution": ("日本私立学校振興・共済事業団 公表資料"),
                        "license": ("公的助成業務における公表資料 (出典明記で引用可)"),
                    },
                    ensure_ascii=False,
                )
                if conn is None:
                    if len(sample_rows) < 8:
                        sample_rows.append(
                            {
                                "year": r.year_label,
                                "hojin": r.hojin_name,
                                "school": r.school_name,
                                "kind": r.enforcement_kind,
                                "treatment": r.treatment,
                                "law": r.related_law_ref,
                            }
                        )
                    stats["rows_inserted"] += 1
                    by_year[r.year_label] = by_year.get(r.year_label, 0) + 1
                    by_kind[r.enforcement_kind] = by_kind.get(r.enforcement_kind, 0) + 1
                    continue
                try:
                    upsert_entity(
                        conn,
                        canonical_id=canonical_id,
                        primary_name=primary_name,
                        source_url=r.source_url,
                        raw_json=raw_json,
                        now_iso=now_iso,
                        authority_canonical=r.authority_canonical,
                        source_topic="shigaku_subsidy_enforcement",
                    )
                    target_name = f"{r.hojin_name} / {r.school_name}"
                    verdict = upsert_enforcement(
                        conn,
                        entity_id=canonical_id,
                        target_name=target_name,
                        issuance_date=r.issuance_date,
                        issuing_authority=r.issuing_authority,
                        enforcement_kind=r.enforcement_kind,
                        reason_summary=(
                            f"[{r.year_label}] {r.treatment} — 事由: {r.jiyu}"
                            + (f" / 区分: {r.section_label}" if r.section_label else "")
                        ),
                        related_law_ref=r.related_law_ref,
                        amount_yen=None,
                        source_url=r.source_url,
                        source_fetched_at=now_iso,
                    )
                    if verdict == "insert":
                        stats["rows_inserted"] += 1
                    else:
                        stats["rows_updated"] += 1
                    by_year[r.year_label] = by_year.get(r.year_label, 0) + 1
                    by_kind[r.enforcement_kind] = by_kind.get(r.enforcement_kind, 0) + 1
                    if len(sample_rows) < 8:
                        sample_rows.append(
                            {
                                "year": r.year_label,
                                "hojin": r.hojin_name,
                                "school": r.school_name,
                                "kind": r.enforcement_kind,
                                "treatment": r.treatment,
                                "law": r.related_law_ref[:60],
                            }
                        )
                except sqlite3.Error as exc:
                    _LOG.error("[%s] DB error %s/%s: %s", slug, r.hojin_name, r.school_name, exc)
                    continue

        # -- Phase 2: MEXT one-offs --------------------------------------
        for src in MEXT_ONE_OFFS:
            if args.limit and stats["rows_inserted"] >= args.limit:
                break
            slug = str(src["slug"])
            url = str(src["url"])
            schools = src.get("school_names") or []
            if not isinstance(schools, list):
                schools = [str(schools)]
            for school in schools:
                school_str = str(school)
                canonical_id = _entity_canonical_id_mext(slug, school_str)
                primary_name = (
                    f"{src['hojin_name']} ({school_str}) — "
                    f"{src['issuance_date']} {src['issuing_authority']} "
                    f"{src['enforcement_kind']}"
                )
                raw_json = json.dumps(
                    {
                        "source_slug": slug,
                        "issuance_date": src["issuance_date"],
                        "hojin_name": src["hojin_name"],
                        "school_name": school_str,
                        "enforcement_kind": src["enforcement_kind"],
                        "related_law_ref": src["related_law_ref"],
                        "issuing_authority": src["issuing_authority"],
                        "authority_canonical": src["authority_canonical"],
                        "source_url": url,
                        "source_attribution": src["source_attribution"],
                        "license": src["license"],
                    },
                    ensure_ascii=False,
                )
                if conn is None:
                    stats["mext_inserted"] += 1
                    if len(sample_rows) < 8:
                        sample_rows.append(
                            {
                                "year": str(src["issuance_date"])[:4],
                                "hojin": src["hojin_name"],
                                "school": school_str,
                                "kind": src["enforcement_kind"],
                                "treatment": "解散命令",
                                "law": src["related_law_ref"],
                            }
                        )
                    continue
                try:
                    upsert_entity(
                        conn,
                        canonical_id=canonical_id,
                        primary_name=primary_name,
                        source_url=url,
                        raw_json=raw_json,
                        now_iso=now_iso,
                        authority_canonical=str(src["authority_canonical"]),
                        source_topic="mext_shigaku_enforcement",
                    )
                    target_name = f"{src['hojin_name']} / {school_str}"
                    verdict = upsert_enforcement(
                        conn,
                        entity_id=canonical_id,
                        target_name=target_name,
                        issuance_date=str(src["issuance_date"]),
                        issuing_authority=str(src["issuing_authority"]),
                        enforcement_kind=str(src["enforcement_kind"]),
                        reason_summary=str(src["reason_summary"]),
                        related_law_ref=str(src["related_law_ref"]),
                        amount_yen=None,
                        source_url=url,
                        source_fetched_at=now_iso,
                    )
                    if verdict == "insert":
                        stats["mext_inserted"] += 1
                        stats["rows_inserted"] += 1
                    else:
                        stats["rows_updated"] += 1
                    by_kind[str(src["enforcement_kind"])] = (
                        by_kind.get(str(src["enforcement_kind"]), 0) + 1
                    )
                    if len(sample_rows) < 8:
                        sample_rows.append(
                            {
                                "year": str(src["issuance_date"])[:4],
                                "hojin": src["hojin_name"],
                                "school": school_str,
                                "kind": src["enforcement_kind"],
                                "treatment": "解散命令",
                                "law": src["related_law_ref"],
                            }
                        )
                except sqlite3.Error as exc:
                    stats["mext_failed"] += 1
                    _LOG.error("[%s] MEXT DB error: %s", slug, exc)
                    continue

        if conn is not None:
            conn.commit()
    except sqlite3.Error as exc:
        _LOG.error("BEGIN/commit failed: %s", exc)
        if conn is not None:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
    finally:
        http.close()
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    _LOG.info(
        "done pdfs_ok=%d pdfs_fail=%d parsed=%d inserted=%d updated=%d "
        "mext_inserted=%d mext_failed=%d",
        stats["pdfs_fetched"],
        stats["pdfs_failed"],
        stats["rows_parsed"],
        stats["rows_inserted"],
        stats["rows_updated"],
        stats["mext_inserted"],
        stats["mext_failed"],
    )
    print("=== SUMMARY ===")
    print(f"pdfs_fetched: {stats['pdfs_fetched']}")
    print(f"pdfs_failed: {stats['pdfs_failed']}")
    print(f"rows_parsed: {stats['rows_parsed']}")
    print(f"rows_inserted: {stats['rows_inserted']}")
    print(f"rows_updated: {stats['rows_updated']}")
    print(f"mext_inserted: {stats['mext_inserted']}")
    print(f"by_year: {by_year}")
    print(f"by_kind: {by_kind}")
    print(f"sample rows ({len(sample_rows)}):")
    for s in sample_rows:
        print(f"  - {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
