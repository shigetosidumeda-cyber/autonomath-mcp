"""GET /v1/industry/sector/175 — JSIC 175 中分類 cohort surface.

Wave 41 Axis 7c REST endpoint backed by ``am_industry_jsic_175`` and
``am_program_sector_175_map`` (migration 247). Returns either:

* the full 175-row dimension table (no path arg), or
* a per-sector slice (``/v1/industry/sector/175/{jsic_code}``) with
  programs / adoption / enforcement counts for that single 中分類.

Aggregator
----------
Counts are refreshed weekly by
``scripts/cron/aggregate_industry_sector_175_weekly.py``. The endpoint
is a pure SELECT — no aggregation at request time.

CLAUDE.md / memory constraints
------------------------------
* NO LLM call — pure SQLite SELECT.
* NO cross-DB ATTACH; autonomath.db read-only handle.
* NO PRAGMA quick_check / integrity_check on the 9.7 GB DB.
* Read budget: ¥3/req (1 ``_billing_unit``).
"""

from __future__ import annotations

import logging
import os
import re
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

logger = logging.getLogger("jpintel.api.industry_sector_175")

router = APIRouter(prefix="/v1/industry", tags=["industry", "sector"])

_JSIC_CODE_RE = re.compile(r"^[0-9]{3}$")
_MAJOR_CODE_RE = re.compile(r"^[A-T]$")

_SECTOR_DISCLAIMER = (
    "本レスポンスは jpcite が JSIC (日本標準産業分類, 令和5年改定 / 総務省) 175 中分類 "
    "を機械的に programs / adoption / enforcement にマッピングした結果を返却するもので、"
    "業種判定・士業役務 (税理士 §52 / 社労士 §27 / 行政書士 §1) のいずれにも該当しません。"
    "中分類への対応は keyword + 大分類 fallback の rule-based 推定で、各制度の正式な業種 "
    "適用は所管省庁 公式 募集要項 で必ず確認してください。"
)


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


@router.get(
    "/sector/175",
    summary="JSIC 175 中分類 sector list",
    description=(
        "Returns the full ``am_industry_jsic_175`` table — 175 JSIC 中分類 "
        "rows with programs / adoption / enforcement counts. Refreshed "
        "weekly by ``scripts/cron/aggregate_industry_sector_175_weekly.py``."
        "\n\n**Pricing**: ¥3 / call (``_billing_unit: 1``)."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {"description": "Sector list envelope."},
    },
)
def list_industry_sector_175(
    conn: DbDep,
    ctx: ApiContextDep,
    major_code: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=1,
            description="Filter by 大分類 code (1-char A-T).",
        ),
    ] = None,
    min_programs: Annotated[
        int,
        Query(ge=0, le=10000, description="Filter sectors with at least N programs."),
    ] = 0,
) -> JSONResponse:
    """List the 175 中分類 sector dimension."""
    t0 = time.perf_counter()
    if major_code is not None and not _MAJOR_CODE_RE.match(major_code):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"major_code must be 1 char A-T; got {major_code!r}.",
        )

    rows: list[dict[str, Any]] = []
    am = _open_am_ro()
    if am is not None:
        try:
            if _table_exists(am, "am_industry_jsic_175"):
                base_sql = (
                    "SELECT jsic_code, major_code, parent_major, name, "
                    "       programs_count, programs_avg_amount, adoption_count, "
                    "       enforcement_count, refreshed_at "
                    "FROM am_industry_jsic_175 WHERE programs_count >= ? "
                )
                params: list[Any] = [int(min_programs)]
                if major_code:
                    base_sql += "AND major_code = ? "
                    params.append(major_code)
                base_sql += (
                    "ORDER BY programs_count DESC, adoption_count DESC, jsic_code ASC "
                    "LIMIT 200"
                )
                for r in am.execute(base_sql, params).fetchall():
                    rows.append(
                        {
                            "jsic_code": r["jsic_code"],
                            "major_code": r["major_code"],
                            "parent_major": r["parent_major"],
                            "name": r["name"],
                            "programs_count": r["programs_count"],
                            "programs_avg_amount": r["programs_avg_amount"],
                            "adoption_count": r["adoption_count"],
                            "enforcement_count": r["enforcement_count"],
                            "refreshed_at": r["refreshed_at"],
                        }
                    )
        except sqlite3.OperationalError as exc:
            logger.warning("industry_sector_175 list failed: %s", exc)
        finally:
            with suppress(Exception):
                am.close()

    result = {
        "rows": rows,
        "row_count": len(rows),
        "filters": {"major_code": major_code, "min_programs": min_programs},
        "_billing_unit": 1,
        "_disclaimer": _SECTOR_DISCLAIMER,
        "precompute_source": "am_industry_jsic_175 (mig 247)",
    }
    latency_ms = int((time.perf_counter() - t0) * 1000)
    log_usage(
        conn,
        ctx,
        "industry_sector_175.list",
        latency_ms=latency_ms,
        result_count=len(rows),
        params={"major_code": major_code, "min_programs": min_programs},
        strict_metering=True,
    )
    return JSONResponse(content=result, status_code=200)


@router.get(
    "/sector/175/{jsic_code}",
    summary="JSIC 中分類 sector detail (one row + top programs)",
    description=(
        "Returns one ``am_industry_jsic_175`` row plus its top mapped "
        "programs via ``am_program_sector_175_map``. NO LLM, pure SELECT."
        "\n\n**Pricing**: ¥3 / call (``_billing_unit: 1``)."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {"description": "Sector detail envelope."},
        404: {"description": "jsic_code not present."},
    },
)
def get_industry_sector_175_detail(
    conn: DbDep,
    ctx: ApiContextDep,
    jsic_code: Annotated[
        str,
        FastPath(
            min_length=3,
            max_length=3,
            description="3-digit JSIC 中分類 code (e.g. '060').",
        ),
    ],
    max_programs: Annotated[
        int,
        Query(ge=1, le=50, description="Cap on top mapped programs (default 10)."),
    ] = 10,
) -> JSONResponse:
    """Return one 中分類 + its top mapped programs."""
    t0 = time.perf_counter()
    if not _JSIC_CODE_RE.match(jsic_code):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"jsic_code must be 3 digits; got {jsic_code!r}.",
        )

    sector: dict[str, Any] | None = None
    programs: list[dict[str, Any]] = []
    am = _open_am_ro()
    if am is not None:
        try:
            if _table_exists(am, "am_industry_jsic_175"):
                row = am.execute(
                    "SELECT jsic_code, major_code, parent_major, name, "
                    "       programs_count, programs_avg_amount, adoption_count, "
                    "       enforcement_count, refreshed_at "
                    "FROM am_industry_jsic_175 WHERE jsic_code = ? LIMIT 1",
                    (jsic_code,),
                ).fetchone()
                if row:
                    sector = {
                        "jsic_code": row["jsic_code"],
                        "major_code": row["major_code"],
                        "parent_major": row["parent_major"],
                        "name": row["name"],
                        "programs_count": row["programs_count"],
                        "programs_avg_amount": row["programs_avg_amount"],
                        "adoption_count": row["adoption_count"],
                        "enforcement_count": row["enforcement_count"],
                        "refreshed_at": row["refreshed_at"],
                    }
            if _table_exists(am, "am_program_sector_175_map"):
                for r in am.execute(
                    "SELECT program_id, score, match_kind, refreshed_at "
                    "FROM am_program_sector_175_map "
                    "WHERE jsic_code = ? "
                    "ORDER BY score DESC, program_id ASC "
                    "LIMIT ?",
                    (jsic_code, int(max_programs)),
                ).fetchall():
                    programs.append(
                        {
                            "program_id": r["program_id"],
                            "score": r["score"],
                            "match_kind": r["match_kind"],
                            "refreshed_at": r["refreshed_at"],
                        }
                    )
        except sqlite3.OperationalError as exc:
            logger.warning("industry_sector_175 detail failed: %s", exc)
        finally:
            with suppress(Exception):
                am.close()

    if sector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"jsic_code={jsic_code} not present in am_industry_jsic_175.",
        )

    result = {
        "sector": sector,
        "programs": programs,
        "programs_returned": len(programs),
        "_billing_unit": 1,
        "_disclaimer": _SECTOR_DISCLAIMER,
        "precompute_source": "am_industry_jsic_175 / am_program_sector_175_map (mig 247)",
    }
    latency_ms = int((time.perf_counter() - t0) * 1000)
    log_usage(
        conn,
        ctx,
        "industry_sector_175.detail",
        latency_ms=latency_ms,
        result_count=len(programs),
        params={"jsic_code": jsic_code, "max_programs": max_programs},
        strict_metering=True,
    )
    return JSONResponse(content=result, status_code=200)


__all__ = ["router"]
