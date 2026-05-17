"""dd2_municipality_tools — DD2 Geo expansion MCP tool surface (1 tool).

Single tool that surfaces the DD2 1,714 市町村 structured subsidy corpus to
the customer LLM:

  * ``find_municipality_subsidies(prefecture, municipality_code, jsic_major,
    target_size)`` — am_municipality_subsidy lookup with 4-axis fan-out
    (prefecture / municipality_code / jsic_major / target_size). Returns top
    20 rows + 5-axis citation (subsidy_url + source_pdf_s3_uri + ocr_s3_uri +
    ocr_job_id + sha256) + ``source_attribution`` envelope (政府著作物 §13).

The tool:

  * LLM call = 0. Pure SQLite over autonomath.db.
  * Single ¥3/req billing event per call.
  * source_attribution envelope (license = public_domain_jp_gov §13).
  * NO ``_disclaimer`` — pure listing of public domain 1次資料.
  * ``_next_calls`` compounding hints (window lookup, related programs).

Migration dependency: wave24_217_am_municipality_subsidy.sql (1 table, 2 views).
ETL dependencies:
  * scripts/etl/build_dd2_municipality_manifest_2026_05_17.py (1,714 munic)
  * scripts/etl/crawl_municipality_subsidy_2026_05_17.py (S3 PDF stage)
  * scripts/aws_credit_ops/textract_municipality_bulk_2026_05_17.py (Textract)
  * scripts/etl/ingest_dd2_municipality_subsidy_2026_05_17.py (structured ingest)
"""

from __future__ import annotations

import datetime
import json
import logging
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpcite.mcp.autonomath.dd2_municipality")

# Env-gated registration (default ON). Flip to "0" for one-flag rollback.
_ENABLED = (
    get_flag(
        "JPCITE_DD2_MUNICIPALITY_ENABLED",
        "AUTONOMATH_DD2_MUNICIPALITY_ENABLED",
        "1",
    )
    == "1"
)


# ---------------------------------------------------------------------------
# DB helpers — am_municipality_subsidy lives in autonomath.db.
# ---------------------------------------------------------------------------


def _autonomath_db_path() -> Path:
    """Return the autonomath.db path from env or repository default."""
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[5] / "autonomath.db"


def _open_db() -> sqlite3.Connection | dict[str, Any]:
    """Open autonomath.db read-only; return conn or error envelope."""
    p = _autonomath_db_path()
    if not p.exists():
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {p}",
            hint="Ensure migration wave24_217 has applied + DD2 ingest has run.",
        )
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
        )


def _today_iso() -> str:
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()


# ---------------------------------------------------------------------------
# find_municipality_subsidies impl
# ---------------------------------------------------------------------------


_VALID_JSIC_MAJORS: frozenset[str] = frozenset("ABCDEFGHIJKLMNOPQRS")

# Approximate 平均年商 (annual revenue) buckets for target_size.
_TARGET_SIZE_BUCKETS: dict[str, tuple[int | None, int | None]] = {
    "micro": (None, 50_000_000),  # 〜5,000万
    "small": (50_000_001, 300_000_000),  # 5,001万〜3億
    "medium": (300_000_001, 3_000_000_000),  # 3億〜30億
    "large": (3_000_000_001, None),  # 30億〜
    "any": (None, None),
}


def _find_municipality_subsidies_impl(
    prefecture: str | None = None,
    municipality_code: str | None = None,
    jsic_major: str | None = None,
    target_size: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Pure SQL am_municipality_subsidy search by 4-axis cohort filter.

    Returns top ``limit`` rows ordered by amount_yen_max DESC, deadline ASC.
    Each result carries 5-axis citation (subsidy_url + s3 URIs + sha256) and
    the source_attribution envelope (政府著作物 §13 license).
    """
    limit = max(1, min(int(limit), 100))
    if jsic_major is not None and jsic_major.strip():
        jsic_major = jsic_major.strip().upper()
        if jsic_major not in _VALID_JSIC_MAJORS:
            return make_error(
                code="invalid_enum",
                message=(f"jsic_major must be one of A..S (got {jsic_major!r})."),
                field="jsic_major",
            )
    target_size = (target_size or "any").strip().lower()
    if target_size not in _TARGET_SIZE_BUCKETS:
        return make_error(
            code="invalid_enum",
            message=(
                f"target_size must be one of {sorted(_TARGET_SIZE_BUCKETS)} (got {target_size!r})."
            ),
            field="target_size",
        )

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    rows: list[sqlite3.Row] = []
    try:
        # Graceful empty envelope if migration 217 hasn't applied yet.
        try:
            conn.execute("SELECT 1 FROM am_municipality_subsidy LIMIT 0")
        except sqlite3.OperationalError as exc:
            logger.warning("am_municipality_subsidy table missing: %s", exc)
            return make_error(
                code="db_unavailable",
                message="am_municipality_subsidy table missing",
                hint="Apply migration wave24_217_am_municipality_subsidy.sql.",
            )

        clauses: list[str] = []
        params: list[Any] = []
        if prefecture and prefecture.strip():
            clauses.append("prefecture = ?")
            params.append(prefecture.strip())
        if municipality_code and municipality_code.strip():
            clauses.append("municipality_code = ?")
            params.append(municipality_code.strip())
        if jsic_major:
            clauses.append("(target_jsic_majors IS NULL OR target_jsic_majors LIKE ?)")
            params.append(f'%"{jsic_major}"%')
        if target_size != "any":
            lo, hi = _TARGET_SIZE_BUCKETS[target_size]
            if lo is not None:
                clauses.append("(amount_yen_max IS NULL OR amount_yen_max >= ?)")
                params.append(lo // 100)  # heuristic: 0.01x of bucket floor
            if hi is not None:
                clauses.append("(amount_yen_max IS NULL OR amount_yen_max <= ?)")
                params.append(hi // 10)  # heuristic: 0.1x of bucket ceiling

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (  # nosec B608 — params bound via ? placeholders
            "SELECT subsidy_id, municipality_code, prefecture, "
            "       municipality_name, municipality_type, program_name, "
            "       amount_yen_max, amount_yen_min, subsidy_rate, deadline, "
            "       target_jsic_majors, target_corporate_forms, "
            "       target_region_codes, source_url, source_pdf_s3_uri, "
            "       ocr_s3_uri, ocr_job_id, ocr_confidence, ocr_page_count, "
            "       sha256, fetched_at, ingested_at, license "
            "  FROM am_municipality_subsidy "
            f"{where_sql} "
            " ORDER BY (amount_yen_max IS NULL), amount_yen_max DESC, "
            "          (deadline IS NULL), deadline ASC "
            " LIMIT ? "
        )
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_municipality_subsidy query failed: %s", exc)
        return make_error(
            code="db_unavailable",
            message=f"am_municipality_subsidy query failed: {exc}",
        )
    finally:
        conn.close()

    results: list[dict[str, Any]] = []
    for r in rows:
        try:
            jsic_majors = json.loads(r["target_jsic_majors"] or "[]")
        except (TypeError, ValueError):
            jsic_majors = []
        try:
            corporate_forms = json.loads(r["target_corporate_forms"] or "[]")
        except (TypeError, ValueError):
            corporate_forms = []

        results.append(
            {
                "subsidy_id": r["subsidy_id"],
                "municipality_code": r["municipality_code"],
                "prefecture": r["prefecture"],
                "municipality_name": r["municipality_name"],
                "municipality_type": r["municipality_type"],
                "program_name": r["program_name"],
                "amount_yen_max": r["amount_yen_max"],
                "amount_yen_min": r["amount_yen_min"],
                "subsidy_rate": r["subsidy_rate"],
                "deadline": r["deadline"],
                "target_jsic_majors": jsic_majors,
                "target_corporate_forms": corporate_forms,
                "source_url": r["source_url"],
                "source_pdf_s3_uri": r["source_pdf_s3_uri"],
                "ocr_s3_uri": r["ocr_s3_uri"],
                "ocr_job_id": r["ocr_job_id"],
                "ocr_confidence": r["ocr_confidence"],
                "ocr_page_count": r["ocr_page_count"],
                "sha256": r["sha256"],
                "fetched_at": r["fetched_at"],
                "ingested_at": r["ingested_at"],
                # Per-row source_attribution (§13 政府著作物).
                "source_attribution": {
                    "municipality_name": r["municipality_name"],
                    "source_url": r["source_url"],
                    "fetched_at": r["fetched_at"],
                    "license": r["license"] or "public_domain_jp_gov",
                },
            }
        )

    body: dict[str, Any] = {
        "prefecture": prefecture,
        "municipality_code": municipality_code,
        "jsic_major": jsic_major,
        "target_size": target_size,
        "results": results,
        "total": len(results),
        "limit": limit,
        "offset": 0,
        "as_of_jst": _today_iso(),
        "_next_calls": [
            {
                "tool": "find_filing_window",
                "args": {
                    "kind": "municipality",
                    "region_code": municipality_code,
                },
                "rationale": "DD2 補助金 → 申請窓口 (am_window_directory) chain",
            },
            {
                "tool": "search_tax_incentives",
                "args": {"keyword": prefecture or "事業承継"},
                "rationale": "市町村 補助金 → 都道府県 / 国 税制 stack 検証",
            },
        ],
        "_billing_unit": 1,
    }
    return body


# ---------------------------------------------------------------------------
# MCP tool registration — gated by AUTONOMATH_DD2_MUNICIPALITY_ENABLED
# ---------------------------------------------------------------------------

if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def find_municipality_subsidies(
        prefecture: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "都道府県名 (例 '東京都', '北海道'). 完全一致 filter. 省略時は全国 fan-out."
                ),
            ),
        ] = None,
        municipality_code: Annotated[
            str | None,
            Field(
                default=None,
                description=("J-LIS 5-digit 自治体コード (例 '13104' 新宿区). 完全一致."),
                max_length=10,
            ),
        ] = None,
        jsic_major: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "JSIC 大分類 1 文字 (A〜S). 省略時は全業種 fan-out. "
                    "Subsidy が全業種対象の場合も hit."
                ),
                max_length=1,
            ),
        ] = None,
        target_size: Annotated[
            str | None,
            Field(
                default="any",
                description=(
                    "事業規模 bucket: 'micro' (〜5,000万) / 'small' (5,001万〜3億) "
                    "/ 'medium' (3億〜30億) / 'large' (30億〜) / 'any' (全規模)."
                ),
                max_length=10,
            ),
        ] = "any",
        limit: Annotated[
            int,
            Field(
                default=20,
                description="最大行数 (1..100, default 20).",
                ge=1,
                le=100,
            ),
        ] = 20,
    ) -> dict[str, Any]:
        """[DD2 GEO] 1,714 市町村 補助金 4-axis cohort lookup. Returns rows with 5-axis citation (subsidy_url + S3 PDF URI + OCR S3 URI + ocr_job_id + sha256). 政府著作物 §13 license — source_attribution envelope per row. NO LLM. Single ¥3/req."""
        return _find_municipality_subsidies_impl(
            prefecture=prefecture,
            municipality_code=municipality_code,
            jsic_major=jsic_major,
            target_size=target_size,
            limit=limit,
        )


__all__ = [
    "_find_municipality_subsidies_impl",
]
