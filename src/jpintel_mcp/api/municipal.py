"""Wave 31 Axis 1a — 自治体 (市区町村 + 政令市 + 中核市 + 特別区) 補助金 REST surface.

Endpoints
---------
* ``GET /v1/municipal/subsidies`` — paginated lookup over the 1,794-自治体
  rollup. Filters: ``pref`` (47 都道府県), ``muni_name`` (partial match),
  ``page_status`` (active/404/redirect). 1 ¥3/req unit.
* ``GET /v1/municipal/by_prefecture`` — counts grouped by ``pref``. Cheap
  rollup over the same table. 1 ¥3/req unit.

Backed by ``municipality_subsidy`` (migration ``wave24_191_municipality_subsidy``,
target_db=jpintel; UNIQUE(muni_code, subsidy_url)). NO LLM API call.
NO destructive write. NO full-scan op against multi-GB DBs.

Sensitive surface: §47条の2 / §52 / §1 / §72 disclaimer mirrored on every
2xx envelope — output is information retrieval, not 申請書面作成 / 補助金
申請代行 / 個別税務助言.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

router = APIRouter(prefix="/v1/municipal", tags=["municipal", "subsidies"])


_DISCLAIMER = (
    "本レスポンスは jpcite が自治体 web の公開情報を機械的に収集・整理した結果を"
    "返却するものであり、税理士法 §52 / 公認会計士法 §47条の2 / 行政書士法 §1の2 / "
    "弁護士法 §72 に基づく個別具体的な税務助言・監査意見・申請書面作成・法律相談の"
    "代替ではありません。掲載情報は ``retrieved_at`` 時点の snapshot です — 最新の"
    "募集要項は必ず一次資料 (各自治体公式 web) で確認してください。"
)


def _wrap(payload: dict[str, Any]) -> dict[str, Any]:
    payload.setdefault("_disclaimer", _DISCLAIMER)
    return payload


@router.get(
    "/subsidies",
    summary="自治体補助金リスト (Wave 31 Axis 1a)",
    responses=COMMON_ERROR_RESPONSES,
)
async def list_municipal_subsidies(
    ctx: ApiContextDep,
    db: DbDep,
    pref: Annotated[str | None, Query(description="都道府県 (e.g. 東京都)")] = None,
    muni_name: Annotated[str | None, Query(description="市区町村名 partial match")] = None,
    page_status: Annotated[str | None, Query(description="active / 404 / redirect")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    started_ns = time.monotonic_ns()
    where: list[str] = []
    params: list[Any] = []
    if pref:
        where.append("pref = ?")
        params.append(pref)
    if muni_name:
        where.append("muni_name LIKE ?")
        params.append(f"%{muni_name}%")
    if page_status:
        where.append("page_status = ?")
        params.append(page_status)
    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    items: list[dict[str, Any]] = []
    total = 0
    try:
        cur = db.execute(
            "SELECT pref, muni_code, muni_name, muni_type, subsidy_url, "
            "subsidy_name, eligibility_text, amount_text, deadline_text, "
            "retrieved_at, page_status "
            "FROM municipality_subsidy"
            + where_clause
            + " ORDER BY pref, muni_name, subsidy_url LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        items = [dict(row) for row in cur.fetchall()]
        cnt = db.execute(
            "SELECT COUNT(*) AS c FROM municipality_subsidy" + where_clause,
            params,
        ).fetchone()
        total = int(cnt["c"]) if cnt else 0
    except sqlite3.OperationalError:
        # Table may not be hydrated on dev box; honest empty + count=0.
        items = []
        total = 0
    latency_ms = int((time.monotonic_ns() - started_ns) / 1_000_000)
    log_usage(
        db,
        ctx,
        endpoint="municipal_list_subsidies",
        quantity=1,
        latency_ms=latency_ms,
        result_count=len(items),
        strict_metering=True,
    )
    return JSONResponse(
        _wrap(
            {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
                "filters": {"pref": pref, "muni_name": muni_name, "page_status": page_status},
            }
        )
    )


@router.get(
    "/by_prefecture",
    summary="都道府県別 補助金ページ数 (Wave 31 Axis 1a)",
    responses=COMMON_ERROR_RESPONSES,
)
async def by_prefecture(
    ctx: ApiContextDep,
    db: DbDep,
) -> JSONResponse:
    started_ns = time.monotonic_ns()
    rollup: list[dict[str, Any]] = []
    try:
        cur = db.execute(
            "SELECT pref, COUNT(*) AS subsidies, "
            "SUM(CASE WHEN page_status='active' THEN 1 ELSE 0 END) AS active_pages "
            "FROM municipality_subsidy GROUP BY pref ORDER BY subsidies DESC"
        )
        rollup = [dict(row) for row in cur.fetchall()]
    except sqlite3.OperationalError:
        rollup = []
    latency_ms = int((time.monotonic_ns() - started_ns) / 1_000_000)
    log_usage(
        db,
        ctx,
        endpoint="municipal_by_prefecture",
        quantity=1,
        latency_ms=latency_ms,
        result_count=len(rollup),
        strict_metering=True,
    )
    return JSONResponse(_wrap({"by_prefecture": rollup, "count": len(rollup)}))
