"""municipality_tools — DEEP-44 自治体 補助金 page diff MCP tool surface (1 tool).

Single tool that surfaces the DEEP-44 corpus to the customer LLM:

  * ``search_municipality_subsidies(pref, muni_name=None, keyword=None)``
      — municipality_subsidy を pref + muni_name + keyword filter, top 20
        rows + 3-axis citation (subsidy_url + retrieved_at + sha256) +
        ``source_attribution`` envelope (政府著作物 §13). Surfaces 1次
        資料 only listing — aggregator URL は ingest 段階で 弾かれる
        (scripts/cron/ingest_municipality_subsidy_weekly.py).

The tool:

  * LLM call = 0. Pure SQLite over jpintel.db.
  * Single ¥3/req billing event per call.
  * source_attribution envelope (license = public_domain_jp_gov §13).
  * NO ``_disclaimer`` — pure listing of public domain 1次資料,
    not a §52 / §47条の2 / §72 / §3 sensitive surface (DEEP-44 §7).
  * ``_next_calls`` compounding hints for related-program walk.

Migration dependency: wave24_191_municipality_subsidy.sql (1 table).
Cron dependency: scripts/cron/ingest_municipality_subsidy_weekly.py.
"""

from __future__ import annotations

import datetime
import logging
import os
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.municipality")

# Env-gated registration (default ON). Flip to "0" for one-flag rollback.
_ENABLED = os.environ.get("AUTONOMATH_MUNICIPALITY_ENABLED", "1") == "1"


# ---------------------------------------------------------------------------
# DB helpers — municipality_subsidy lives in jpintel.db (target_db: jpintel).
# ---------------------------------------------------------------------------


def _jpintel_db_path() -> Path:
    """Return the jpintel.db path from env or settings (read-only opener)."""
    raw = os.environ.get("JPINTEL_DB_PATH")
    if raw:
        return Path(raw)
    # Fall back to repository default (data/jpintel.db).
    return Path(__file__).resolve().parents[5] / "data" / "jpintel.db"


def _open_db() -> sqlite3.Connection | dict[str, Any]:
    """Open jpintel.db read-only, returning either a conn or error envelope."""
    p = _jpintel_db_path()
    if not p.exists():
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db missing: {p}",
            hint="Ensure migration wave24_191 has applied + cron has populated rows.",
        )
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db open failed: {exc}",
        )


def _today_iso() -> str:
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()


# ---------------------------------------------------------------------------
# search_municipality_subsidies impl
# ---------------------------------------------------------------------------


def _search_municipality_subsidies_impl(
    pref: str,
    muni_name: str | None = None,
    keyword: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Pure SQL municipality_subsidy search by pref + muni_name + keyword.

    Returns top ``limit`` rows ordered by retrieved_at DESC. Each result
    carries subsidy_url + retrieved_at + sha256 (3-axis citation) + the
    source_attribution envelope (政府著作物 §13 license).
    """
    if not isinstance(pref, str) or not pref.strip():
        return make_error(
            code="missing_required_arg",
            message="pref must be a non-empty string (e.g. '東京都')",
            field="pref",
        )
    pref = pref.strip()
    limit = max(1, min(int(limit), 100))

    db = _open_db()
    if isinstance(db, dict):
        return db
    conn = db

    try:
        # Probe the table — if migration 191 hasn't applied yet, return a
        # graceful empty envelope rather than letting sqlite raise.
        try:
            conn.execute("SELECT 1 FROM municipality_subsidy LIMIT 0")
        except sqlite3.OperationalError as exc:
            logger.warning("municipality_subsidy table missing: %s", exc)
            return make_error(
                code="db_unavailable",
                message="municipality_subsidy table missing",
                hint="Apply migration wave24_191_municipality_subsidy.sql.",
            )

        clauses: list[str] = ["pref = ?"]
        params: list[Any] = [pref]
        if muni_name and isinstance(muni_name, str) and muni_name.strip():
            clauses.append("muni_name LIKE ?")
            params.append(f"%{muni_name.strip()}%")
        if keyword and isinstance(keyword, str) and keyword.strip():
            kw = keyword.strip()
            clauses.append(
                "(subsidy_name LIKE ? "
                " OR eligibility_text LIKE ? "
                " OR amount_text LIKE ? "
                " OR deadline_text LIKE ?)"
            )
            params.extend([f"%{kw}%"] * 4)
        # Default: only surface live + redirect rows. 404 rows are kept
        # in DB for liveness audits but are not user-facing listings.
        clauses.append("page_status IN ('active','redirect')")

        where = " AND ".join(clauses)
        sql = (  # nosec B608
            "SELECT pref, muni_code, muni_name, muni_type, subsidy_url, "
            "       subsidy_name, eligibility_text, amount_text, deadline_text, "
            "       retrieved_at, sha256, page_status "
            "  FROM municipality_subsidy "
            f" WHERE {where} "
            " ORDER BY retrieved_at DESC "
            " LIMIT ? "
        )
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("municipality_subsidy search failed: %s", exc)
        return make_error(
            code="db_unavailable",
            message=f"municipality_subsidy query failed: {exc}",
        )
    finally:
        conn.close()

    results: list[dict[str, Any]] = []
    for r in rows:
        results.append(
            {
                "pref": r["pref"],
                "muni_code": r["muni_code"],
                "muni_name": r["muni_name"],
                "muni_type": r["muni_type"],
                "subsidy_url": r["subsidy_url"],
                "subsidy_name": r["subsidy_name"],
                "eligibility_text": r["eligibility_text"],
                "amount_text": r["amount_text"],
                "deadline_text": r["deadline_text"],
                "retrieved_at": r["retrieved_at"],
                "sha256": r["sha256"],
                "page_status": r["page_status"],
                # Per-row source_attribution per DEEP-44 §6.
                "source_attribution": {
                    "muni_name": r["muni_name"],
                    "source_url": r["subsidy_url"],
                    "retrieved_at": r["retrieved_at"],
                    "license": "public_domain_jp_gov",
                },
            }
        )

    body: dict[str, Any] = {
        "pref": pref,
        "muni_name": muni_name,
        "keyword": keyword,
        "results": results,
        "total": len(results),
        "limit": limit,
        "offset": 0,
        "as_of_jst": _today_iso(),
        "_next_calls": [
            {
                "tool": "search_tax_incentives",
                "args": {"keyword": keyword or muni_name or pref},
                "rationale": "自治体 補助金 → 国 / 都道府県 税制 で stack 確認",
            },
            {
                "tool": "search_certifications",
                "args": {"keyword": keyword or "経営革新"},
                "rationale": "自治体 補助金 申請に 認定 が前提となる場合の chain",
            },
        ],
        "_billing_unit": 1,
    }
    return body


# ---------------------------------------------------------------------------
# MCP tool registration — gated by AUTONOMATH_MUNICIPALITY_ENABLED + global enable.
# ---------------------------------------------------------------------------

if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def search_municipality_subsidies(
        pref: Annotated[
            str,
            Field(
                description=(
                    "都道府県名 (e.g. '東京都', '北海道', '大阪府'). 完全一致 filter."
                ),
                min_length=1,
                max_length=20,
            ),
        ],
        muni_name: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "自治体名 substring filter (e.g. '新宿区', '札幌市'). "
                    "Optional — omit to span the entire prefecture."
                ),
            ),
        ] = None,
        keyword: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Substring keyword over subsidy_name + eligibility_text "
                    "+ amount_text + deadline_text. Optional."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                default=20,
                description="Max rows (1..100, default 20).",
                ge=1,
                le=100,
            ),
        ] = 20,
    ) -> dict[str, Any]:
        """[MUNICIPALITY] DEEP-44 自治体 1,741 補助金 page diff cron 1次資料 listing. Returns rows with subsidy_url + retrieved_at + sha256 (3-axis citation) + per-row source_attribution (政府著作物 §13). NOT §52/§47条の2/§72/§3 sensitive (pure listing). NO LLM, single ¥3/req billing."""
        return _search_municipality_subsidies_impl(
            pref=pref,
            muni_name=muni_name,
            keyword=keyword,
            limit=limit,
        )


__all__ = [
    "_search_municipality_subsidies_impl",
]
