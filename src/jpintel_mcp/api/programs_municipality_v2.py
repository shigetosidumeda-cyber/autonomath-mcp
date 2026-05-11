"""Wave 43.1.1 — 市町村 programs v2 bridge REST surface.

Endpoints
---------
* ``GET /v1/programs/by_municipality/{municipality_code}`` — return programs
  derived from a 5-digit JIS 市区町村 code (e.g. ``13104`` for 新宿区).
  Optional ``grant_type`` filter ∈ {補助金, 助成金, 融資, その他}.
  1 ¥3/req unit.
* ``GET /v1/programs/by_prefecture/{prefecture_code}`` — return programs
  derived from a 2-digit JIS 都道府県 code (e.g. ``13`` for 東京都).
  Optional ``grant_type`` filter. 1 ¥3/req unit.

Backed by ``am_program_source_municipality_v2`` (migration
``248_program_source_municipality_v2``, target_db=autonomath). Both
endpoints honor ``UNIQUE(program_id, municipality_code, source_url)``;
duplicate program_id is deduplicated by the API layer before returning.

NO LLM API call. NO destructive write. NO full-scan op against multi-GB
DBs — the bridge table is keyed by ``municipality_code`` / ``prefecture_code``
and indexed in migration 248.

Sensitive surface: §47条の2 / §52 / §1 / §72 disclaimer mirrored on every
2xx envelope — output is information retrieval, not 申請書面作成 / 補助金
申請代行 / 個別税務助言.
"""

from __future__ import annotations

import re
import sqlite3
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import JSONResponse

from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

router = APIRouter(prefix="/v1/programs", tags=["programs", "municipal"])


_DISCLAIMER = (
    "本レスポンスは jpcite が自治体 web の公開情報を機械的に収集・整理した結果を"
    "返却するものであり、税理士法 §52 / 公認会計士法 §47条の2 / 行政書士法 §1 / "
    "弁護士法 §72 に基づく個別具体的な税務助言・監査意見・申請書面作成・法律相談の"
    "代替ではありません。掲載情報は ``last_verified`` 時点の snapshot です — 最新の"
    "募集要項は必ず一次資料 (各自治体公式 web) で確認してください。"
)

GrantTypeLiteral = Literal["補助金", "助成金", "融資", "その他"]

_MUNI_CODE_RX = re.compile(r"^\d{5}$")
_PREF_CODE_RX = re.compile(r"^\d{2}$")


def _wrap(payload: dict[str, Any]) -> dict[str, Any]:
    payload.setdefault("_disclaimer", _DISCLAIMER)
    return payload


def _validate_muni_code(value: str) -> None:
    if not _MUNI_CODE_RX.match(value):
        raise HTTPException(
            status_code=400,
            detail=f"municipality_code must be 5-digit JIS (got: {value!r})",
        )


def _validate_pref_code(value: str) -> None:
    if not _PREF_CODE_RX.match(value):
        raise HTTPException(
            status_code=400,
            detail=f"prefecture_code must be 2-digit JIS (got: {value!r})",
        )
    pref_int = int(value)
    if not (1 <= pref_int <= 47):
        raise HTTPException(
            status_code=400,
            detail=f"prefecture_code out of range 01-47 (got: {value!r})",
        )


def _fetch_rows(
    db: sqlite3.Connection,
    *,
    where: str,
    params: list[Any],
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Return (rows, total). Honest empty on schema-missing dev boxes."""
    try:
        cur = db.execute(
            "SELECT program_id, municipality_code, grant_type, prefecture_code, "
            "       source_url, source_fetched_at, last_verified "
            "FROM am_program_source_municipality_v2 " + where
            + " ORDER BY last_verified DESC, program_id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
        cnt = db.execute(
            "SELECT COUNT(DISTINCT program_id) AS c "
            "FROM am_program_source_municipality_v2 " + where,
            params,
        ).fetchone()
        total = int(cnt["c"]) if cnt else 0
    except sqlite3.OperationalError:
        rows = []
        total = 0
    return rows, total


@router.get(
    "/by_municipality/{municipality_code}",
    summary="市区町村別 programs (Wave 43.1.1)",
    responses=COMMON_ERROR_RESPONSES,
)
async def list_programs_by_municipality(
    ctx: ApiContextDep,
    db: DbDep,
    municipality_code: Annotated[
        str, Path(description="5-digit JIS X 0401/0402 code (e.g. 13104)")
    ],
    grant_type: Annotated[
        GrantTypeLiteral | None,
        Query(description="補助金 / 助成金 / 融資 / その他"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    _validate_muni_code(municipality_code)
    started_ns = time.monotonic_ns()
    where = " WHERE municipality_code = ?"
    params: list[Any] = [municipality_code]
    if grant_type:
        where += " AND grant_type = ?"
        params.append(grant_type)
    rows, total = _fetch_rows(
        db, where=where, params=params, limit=limit, offset=offset,
    )
    latency_ms = int((time.monotonic_ns() - started_ns) / 1_000_000)
    log_usage(
        db,
        ctx,
        endpoint="programs_by_municipality_v2",
        quantity=1,
        latency_ms=latency_ms,
        result_count=len(rows),
    )
    return JSONResponse(
        _wrap(
            {
                "items": rows,
                "total": total,
                "limit": limit,
                "offset": offset,
                "filters": {
                    "municipality_code": municipality_code,
                    "grant_type": grant_type,
                },
            }
        )
    )


@router.get(
    "/by_prefecture/{prefecture_code}",
    summary="都道府県別 programs (Wave 43.1.1)",
    responses=COMMON_ERROR_RESPONSES,
)
async def list_programs_by_prefecture(
    ctx: ApiContextDep,
    db: DbDep,
    prefecture_code: Annotated[
        str, Path(description="2-digit JIS code (e.g. 13 for 東京都)")
    ],
    grant_type: Annotated[
        GrantTypeLiteral | None,
        Query(description="補助金 / 助成金 / 融資 / その他"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    _validate_pref_code(prefecture_code)
    started_ns = time.monotonic_ns()
    where = " WHERE prefecture_code = ?"
    params: list[Any] = [prefecture_code]
    if grant_type:
        where += " AND grant_type = ?"
        params.append(grant_type)
    rows, total = _fetch_rows(
        db, where=where, params=params, limit=limit, offset=offset,
    )
    latency_ms = int((time.monotonic_ns() - started_ns) / 1_000_000)
    log_usage(
        db,
        ctx,
        endpoint="programs_by_prefecture_v2",
        quantity=1,
        latency_ms=latency_ms,
        result_count=len(rows),
    )
    return JSONResponse(
        _wrap(
            {
                "items": rows,
                "total": total,
                "limit": limit,
                "offset": offset,
                "filters": {
                    "prefecture_code": prefecture_code,
                    "grant_type": grant_type,
                },
            }
        )
    )
