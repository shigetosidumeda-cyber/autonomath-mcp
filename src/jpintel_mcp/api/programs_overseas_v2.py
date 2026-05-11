"""GET /v1/programs/overseas — Wave 43.1.2 foreign FDI cohort surface.

Read-only REST router for the autonomath ``am_program_overseas`` table
(landed in migration 249_program_overseas_jetro). Surfaces +1,000
JETRO / METI / JBIC / NEXI rows keyed by ISO 3166-1 alpha-2
country_code + program_type bounded enum.

Cohort
------
Foreign FDI cohort #4 (memory:
``project_autonomath_business_model`` / cohort revenue model).
Designed to be queried by consultants advising 海外進出 / Invest Japan
applicants so the customer LLM can answer "what programs exist for a
日本企業 wanting to expand to {country}" or "what JBIC products fence
my supply chain risk in {country}" in a single GET.

Non-negotiable constraints
--------------------------
* NO LLM call inside the handler (memory:
  ``feedback_no_operator_llm_api``).
* Pure SQLite read. Soft-fail when autonomath.db is missing (test
  fixture) so the route returns 200 with empty results.
* Single ¥3 / call billing event (memory:
  ``project_autonomath_business_model`` 完全従量).
* No paid tier, no seat fee surface in the response shape.

Mounted in ``api/main.py`` under ``AnonIpLimitDep`` so anonymous IPs
inherit the 3 req/day fence (JST 翌日 00:00 リセット).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/programs/overseas", tags=["programs-overseas"])

_ALLOWED_TYPES = (
    "JETRO海外進出支援",
    "JETRO対日投資",
    "METI",
    "JBIC",
    "NEXI",
    "other",
)


def _open_autonomath_ro() -> sqlite3.Connection | None:
    try:
        from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

        return connect_autonomath()
    except Exception as exc:  # noqa: BLE001 — never let DB open break the call
        logger.debug("autonomath.db unavailable: %s", exc)
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
                (name,),
            ).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False


@router.get(
    "/search",
    summary="Search overseas (JETRO / METI / JBIC / NEXI) programs by country + type",
    description=(
        "Wave 43.1.2 surface for the foreign FDI cohort. Reads "
        "``am_program_overseas`` (migration 249) with ISO 3166-1 alpha-2 "
        "country_code + bounded program_type fence."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": "Overseas program slice with country + type filters.",
            "content": {
                "application/json": {
                    "example": {
                        "total": 0,
                        "limit": 20,
                        "offset": 0,
                        "results": [],
                    }
                }
            },
        },
    },
)
def search_overseas_programs(
    request: Request,
    country_code: Annotated[
        str | None,
        Query(
            min_length=2,
            max_length=2,
            description="ISO 3166-1 alpha-2 country code (e.g. 'US', 'TH', 'XX' for global).",
        ),
    ] = None,
    program_type: Annotated[
        str | None,
        Query(
            description=(
                "One of: JETRO海外進出支援 / JETRO対日投資 / METI / JBIC / NEXI / other."
            ),
            max_length=32,
        ),
    ] = None,
    q: Annotated[
        str | None,
        Query(description="Free-text LIKE filter over program_name.", max_length=200),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """Read overseas program rows. Soft-fails to empty results when DB is missing."""
    t0 = time.perf_counter()
    conn = _open_autonomath_ro()
    if conn is None or not _table_exists(conn, "am_program_overseas"):
        return JSONResponse(
            {
                "total": 0,
                "limit": limit,
                "offset": offset,
                "results": [],
                "note": "am_program_overseas not initialised on this volume",
            }
        )

    where: list[str] = []
    params: list[Any] = []
    if country_code:
        where.append("country_code = ?")
        params.append(country_code.upper())
    if program_type:
        if program_type not in _ALLOWED_TYPES:
            return JSONResponse(
                {"error": "invalid_program_type", "allowed": list(_ALLOWED_TYPES)},
                status_code=422,
            )
        where.append("program_type = ?")
        params.append(program_type)
    if q:
        where.append("COALESCE(program_name,'') LIKE ?")
        params.append(f"%{q}%")

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM am_program_overseas{where_sql}",  # noqa: S608 — bound params
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT overseas_id, program_id, country_code, jetro_id, program_type, "
            f"       program_name, source_url, fetched_at "
            f"  FROM am_program_overseas{where_sql} "
            f" ORDER BY fetched_at DESC, overseas_id DESC LIMIT ? OFFSET ?",  # noqa: S608
            (*params, limit, offset),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_program_overseas query failed: %s", exc)
        return JSONResponse(
            {"total": 0, "limit": limit, "offset": offset, "results": []}
        )

    results = [
        {
            "overseas_id": r["overseas_id"],
            "program_id": r["program_id"],
            "country_code": r["country_code"],
            "jetro_id": r["jetro_id"],
            "program_type": r["program_type"],
            "program_name": r["program_name"],
            "source_url": r["source_url"],
            "fetched_at": r["fetched_at"],
        }
        for r in rows
    ]
    elapsed = round((time.perf_counter() - t0) * 1000)
    return JSONResponse(
        {
            "total": total,
            "limit": limit,
            "offset": offset,
            "elapsed_ms": elapsed,
            "results": results,
        }
    )


@router.get(
    "/country_density",
    summary="Country × program-type density (FDI cohort scoping)",
    description=(
        "Read the ``v_program_overseas_country_density`` view to surface "
        "country × type rollup counts. Useful for foreign-FDI consultants "
        "picking a target country fence."
    ),
)
def country_density(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JSONResponse:
    """Read the country/type density view; soft-fail when DB is missing."""
    conn = _open_autonomath_ro()
    if conn is None or not _table_exists(conn, "v_program_overseas_country_density"):
        return JSONResponse({"total": 0, "results": []})
    try:
        rows = conn.execute(
            "SELECT country_code, program_type, programs_count, latest_fetched_at "
            "  FROM v_program_overseas_country_density "
            " ORDER BY programs_count DESC, country_code ASC LIMIT ?",
            (limit,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("country_density read failed: %s", exc)
        return JSONResponse({"total": 0, "results": []})
    return JSONResponse(
        {
            "total": len(rows),
            "results": [
                {
                    "country_code": r["country_code"],
                    "program_type": r["program_type"],
                    "programs_count": r["programs_count"],
                    "latest_fetched_at": r["latest_fetched_at"],
                }
                for r in rows
            ],
        }
    )
