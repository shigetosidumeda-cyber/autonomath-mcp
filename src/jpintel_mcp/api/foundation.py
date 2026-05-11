"""GET /v1/foundation/list + /v1/foundation/{foundation_id} — 民間助成財団 surface.

Wave 43.1.3 REST endpoint backed by ``am_program_private_foundation``
(migration 250). Surfaces 公益財団 / 一般財団 / NPO / 業界団体 grant
programs precomputed by ``scripts/etl/fill_programs_foundation_2x.py``.

Source discipline (non-negotiable)
----------------------------------
* 公益財団協会 (https://www.koeki-info.go.jp/).
* 各 公益財団 official sites — primary domain only.
* 内閣府 NPO 公開資料 (https://www.npo-homepage.go.jp/).
* 業界団体 — 経団連 / 商工会議所 / 同友会 grant pages.

Aggregators (助成財団検索サイト, hojyokin-portal.com 等) are banned per
CLAUDE.md "Aggregators ... are banned" + memory `feedback_no_fake_data`.

Sensitive surface
-----------------
助成 program eligibility 表示 は 民間財団 規程 + 一次資料 の機械的整理に
過ぎず、助成金 受給 助言 (税理士法 §2, 助成金 申請代理 = 行政書士法 §1) には
該当しない。各 row は ``source_url`` で原典確認必須。``_disclaimer`` を 2xx
レスポンスに 必ず stamp する。

CLAUDE.md / memory constraints
------------------------------
* NO LLM call — pure SQLite SELECT.
* NO cross-DB ATTACH; autonomath.db read-only handle.
* Memory `feedback_no_quick_check_on_huge_sqlite` honored — index-only
  walk via ``idx_am_foundation_type`` / ``idx_am_foundation_theme``.
* Read budget: ¥3/req (1 ``_billing_unit``).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi import Path as FastPath
from fastapi.responses import JSONResponse

from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.foundation")

router = APIRouter(prefix="/v1/foundation", tags=["foundation", "grants"])


_FOUNDATION_DISCLAIMER = (
    "本レスポンスは jpcite が 公益財団協会 / 各 公益財団 公式 site / "
    "内閣府 NPO 公開資料 / 業界団体 公式 site を機械的に整理した結果を "
    "返却するものであり、税理士法 §2 (税務代理) ・行政書士法 §1 (助成金 "
    "申請代理) ・弁護士法 §72 (法令解釈) のいずれの士業役務 にも該当 "
    "しません。掲載の grant_amount_range / application_period_json は "
    "公表時点の事実であり、現在の状態が変更されている可能性があります。"
    "各 row の source_url で原典を確認のうえ、確定判断は資格を有する "
    "税理士・行政書士・公認会計士 等 へご相談ください。"
)


_VALID_TYPES = frozenset({"公益財団", "一般財団", "NPO", "業界団体"})


def _autonomath_db_path() -> str:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return raw
    return str(Path(__file__).resolve().parents[3] / "autonomath.db")


def _open_am_ro() -> sqlite3.Connection | None:
    path = _autonomath_db_path()
    try:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError:
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    period_raw = r["application_period_json"]
    try:
        period = json.loads(period_raw) if period_raw else None
    except (TypeError, ValueError):
        period = None
    return {
        "foundation_id": r["foundation_id"],
        "foundation_name": r["foundation_name"],
        "foundation_type": r["foundation_type"],
        "grant_program_name": r["grant_program_name"],
        "grant_amount_range": r["grant_amount_range"],
        "grant_theme": r["grant_theme"],
        "donation_category": r["donation_category"],
        "application_period": period,
        "source_url": r["source_url"],
        "source_kind": r["source_kind"],
        "notes": r["notes"],
        "refreshed_at": r["refreshed_at"],
    }


@router.get(
    "/list",
    summary="List 民間助成財団 grant programs (filter by type + theme)",
    description=(
        "Returns 民間 (公益財団 / 一般財団 / NPO / 業界団体) 助成 program "
        "rows with optional ``foundation_type`` / ``grant_theme`` filters. "
        "NO LLM call. Pure SQLite + index walk on "
        "``am_program_private_foundation`` (migration 250).\n\n"
        "**Pricing**: ¥3 / call (``_billing_unit: 1``).\n\n"
        "**Sensitive**: 税理士法 §2 / 行政書士法 §1 / 弁護士法 §72 fence — "
        "every 2xx carries ``_disclaimer`` (envelope key). LLM agents MUST "
        "relay the disclaimer verbatim to end users."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {"description": "Foundation grant program list envelope."},
    },
)
def list_foundations(
    conn: DbDep,
    ctx: ApiContextDep,
    foundation_type: Annotated[
        str | None,
        Query(
            description=(
                "Filter by foundation type. One of "
                "'公益財団', '一般財団', 'NPO', '業界団体'."
            ),
        ),
    ] = None,
    grant_theme: Annotated[
        str | None,
        Query(description="Filter by grant theme (e.g. '研究', '環境')."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """List 民間助成財団 grants."""
    t0 = time.perf_counter()

    if foundation_type is not None and foundation_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"foundation_type must be one of {sorted(_VALID_TYPES)}, "
                f"got {foundation_type!r}."
            ),
        )

    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    am = _open_am_ro()
    if am is not None:
        try:
            if _table_exists(am, "am_program_private_foundation"):
                where = []
                params: list[Any] = []
                if foundation_type:
                    where.append("foundation_type = ?")
                    params.append(foundation_type)
                if grant_theme:
                    where.append("grant_theme = ?")
                    params.append(grant_theme)
                where_sql = (" WHERE " + " AND ".join(where)) if where else ""
                params.extend([limit, offset])
                fetched = am.execute(
                    "SELECT foundation_id, foundation_name, foundation_type, "
                    "       grant_program_name, grant_amount_range, grant_theme, "
                    "       donation_category, application_period_json, "
                    "       source_url, source_kind, notes, refreshed_at "
                    f"FROM am_program_private_foundation{where_sql} "
                    "ORDER BY refreshed_at DESC, foundation_id ASC "
                    "LIMIT ? OFFSET ?",
                    params,
                ).fetchall()
                rows = [_row_to_dict(r) for r in fetched]
                # cheap summary roll-up
                if _table_exists(am, "v_program_private_foundation_summary"):
                    summary_rows = am.execute(
                        "SELECT foundation_type, donation_category, "
                        "       program_count, foundation_count "
                        "FROM v_program_private_foundation_summary"
                    ).fetchall()
                    summary = {
                        "by_type": [
                            {
                                "foundation_type": s["foundation_type"],
                                "donation_category": s["donation_category"],
                                "program_count": s["program_count"],
                                "foundation_count": s["foundation_count"],
                            }
                            for s in summary_rows
                        ]
                    }
        except sqlite3.OperationalError as exc:
            logger.warning("foundation list query failed: %s", exc)
        finally:
            with suppress(Exception):
                am.close()

    result = {
        "rows": rows,
        "summary": summary,
        "filters": {
            "foundation_type": foundation_type,
            "grant_theme": grant_theme,
            "limit": limit,
            "offset": offset,
        },
        "_billing_unit": 1,
        "_disclaimer": _FOUNDATION_DISCLAIMER,
        "precompute_source": "am_program_private_foundation (mig 250)",
    }

    latency_ms = int((time.perf_counter() - t0) * 1000)
    log_usage(
        conn,
        ctx,
        "foundation_list",
        latency_ms=latency_ms,
        result_count=len(rows),
        params={
            "foundation_type": foundation_type,
            "grant_theme": grant_theme,
            "limit": limit,
            "offset": offset,
        },
        strict_metering=True,
    )
    return JSONResponse(content=result, status_code=200)


@router.get(
    "/{foundation_id}",
    summary="Fetch one 民間助成財団 row by foundation_id",
    description=(
        "Returns one row from ``am_program_private_foundation`` by its "
        "internal ``foundation_id``. ¥3 / call. NO LLM. ``_disclaimer`` "
        "envelope key is mandatory."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {"description": "Foundation grant program envelope."},
        404: {"description": "foundation_id not present."},
    },
)
def get_foundation(
    conn: DbDep,
    ctx: ApiContextDep,
    foundation_id: Annotated[
        int,
        FastPath(ge=1, description="Internal autoincrement id from migration 250."),
    ],
) -> JSONResponse:
    """Fetch one 民間助成財団 row."""
    t0 = time.perf_counter()
    row: dict[str, Any] | None = None
    am = _open_am_ro()
    if am is not None:
        try:
            if _table_exists(am, "am_program_private_foundation"):
                r = am.execute(
                    "SELECT foundation_id, foundation_name, foundation_type, "
                    "       grant_program_name, grant_amount_range, grant_theme, "
                    "       donation_category, application_period_json, "
                    "       source_url, source_kind, notes, refreshed_at "
                    "FROM am_program_private_foundation "
                    "WHERE foundation_id = ? LIMIT 1",
                    (foundation_id,),
                ).fetchone()
                if r is not None:
                    row = _row_to_dict(r)
        except sqlite3.OperationalError as exc:
            logger.warning("foundation get query failed: %s", exc)
        finally:
            with suppress(Exception):
                am.close()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No 民間助成財団 row found for foundation_id={foundation_id}. "
                "Honest absence — this is NOT a statement about the grant program's "
                "existence in reality, only that our corpus does not carry it."
            ),
        )

    result = {
        **row,
        "_billing_unit": 1,
        "_disclaimer": _FOUNDATION_DISCLAIMER,
        "precompute_source": "am_program_private_foundation (mig 250)",
    }

    latency_ms = int((time.perf_counter() - t0) * 1000)
    log_usage(
        conn,
        ctx,
        "foundation_get",
        latency_ms=latency_ms,
        result_count=1,
        params={"foundation_id": foundation_id},
        strict_metering=True,
    )
    return JSONResponse(content=result, status_code=200)


__all__ = ["router"]
