"""REST handlers for the R8 industry-benchmark surface.

Two endpoints:

* ``POST /v1/benchmark/cohort_average``
  Body: { industry_jsic, size_band, prefecture }
  Public (anon-quota gated). Single ¥3/req. NO LLM.

* ``GET /v1/me/benchmark_vs_industry``
  Query: ?industry_jsic&size_band&prefecture&window_days=90
  Authenticated only — frames the caller's recent usage against the same
  cohort baseline + emits a ``leakage_programs`` list so a downstream
  LLM can immediately ask "which 取りこぼし 制度 should I look at next?".

Both wrap the pure implementation in
``jpintel_mcp.mcp.autonomath_tools.benchmark_tools`` so the REST and MCP
surfaces share the same ranking, sparsity disclosure, and §52 / §47条の2
/ §1 disclaimer envelope.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.mcp.autonomath_tools import benchmark_tools

router = APIRouter(tags=["benchmark"])


class CohortAverageBody(BaseModel):
    """Request body for POST /v1/benchmark/cohort_average."""

    model_config = ConfigDict(extra="ignore")

    industry_jsic: str | None = Field(
        default=None,
        max_length=10,
        description=(
            "JSIC industry code prefix (e.g. 'D' for 建設業, 'E29' for "
            "中分類 食料品製造業). Prefix-matches both jpintel "
            "case_studies.industry_jsic and autonomath "
            "jpi_adoption_records.industry_jsic_medium. NULL spans all majors."
        ),
    )
    size_band: str | None = Field(
        default=None,
        max_length=16,
        description=(
            "Size band — 'small' (capital ≤ ¥50M) / 'medium' (¥50M–¥300M) / "
            "'large' (> ¥300M) / 'all'. NULL-tolerant: rows missing "
            "capital_yen still pass."
        ),
    )
    prefecture: str | None = Field(
        default=None,
        max_length=80,
        description=(
            "都道府県 exact match (e.g. '東京都', '群馬県'). Filters both sides. "
            "NULL spans nationwide."
        ),
    )


@router.post(
    "/v1/benchmark/cohort_average",
    summary="業界 cohort average + outlier 法人 (top 10%)",
    description=(
        "業種 (JSIC 大分類 / 中分類) × 規模 (small / medium / large) × 地域 "
        "(都道府県) のコホートに対し、平均採択額 / 採択件数 / 制度hit数 "
        "(distinct_programs) / outlier 法人 (top 10% by populated 交付額) を "
        "返します。case_studies (jpintel.db, 2,286 採択事例) と "
        "jpi_adoption_records (autonomath.db, 201,845 V4-absorbed METI/MAFF "
        "採択結果) を Python merge し、ATTACH/cross-DB JOIN は使いません。\n\n"
        "**¥3/req single billing unit.** NO LLM. §52 / §47条の2 / 行政書士法 §1 "
        "disclaimer envelope on every result — output is information retrieval, "
        "not 申請代理 / 税務助言 / 経営判断."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": (
                "Cohort benchmark envelope. ``outlier_top_decile`` is sorted by "
                "amount_yen DESC; rows missing 交付額 are excluded from outlier "
                "ranking but still counted in cohort_size."
            ),
        },
    },
)
def cohort_average(
    conn: DbDep,
    ctx: ApiContextDep,
    body: Annotated[
        CohortAverageBody,
        Body(
            description=(
                "Cohort filter body. All three axes are optional; NULL fields "
                "are treated as 'span everything'."
            ),
        ),
    ],
) -> JSONResponse:
    """POST /v1/benchmark/cohort_average — 業界 cohort average + outliers."""
    _t0 = time.perf_counter()
    result: dict[str, Any] = benchmark_tools.benchmark_cohort_average_impl(
        industry_jsic=body.industry_jsic,
        size_band=body.size_band,
        prefecture=body.prefecture,
    )
    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    result_count = result.get("cohort_size") if isinstance(result, dict) else None
    log_usage(
        conn,
        ctx,
        "benchmark.cohort_average",
        latency_ms=_latency_ms,
        result_count=result_count if isinstance(result_count, int) else None,
        params={
            "industry_jsic": body.industry_jsic,
            "size_band": body.size_band,
            "prefecture": body.prefecture,
        },
        strict_metering=True,
    )
    status_code = 400 if isinstance(result, dict) and result.get("error") else 200
    return JSONResponse(content=result, status_code=status_code)


@router.get(
    "/v1/me/benchmark_vs_industry",
    summary="My usage vs same-cohort 平均 + 取りこぼし制度",
    description=(
        "認証された API キーの直近 ``window_days`` (default 90) 日の usage_events "
        "を引き、同じ業種 × 規模 × 地域 cohort の平均採択額・distinct programs "
        "と並べて返します。``leakage_programs`` は cohort が利用している program "
        "ラベル集合のうち、呼び出し元が program touch endpoint を踏んでいない "
        "もの — 取りこぼし制度の候補です。\n\n"
        "認証は X-API-Key / Bearer のみ。匿名は 401。usage_events は呼び出し元の "
        "key_hash + parent/child tree (migration 086) のみを参照し、他顧客の "
        "usage を露出しません。"
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": (
                "{ cohort, me, leakage_programs, axes_applied, sparsity_notes, "
                "_disclaimer }. ``me.my_program_touches_known`` is False because "
                "usage_events stores params_digest (hashed) — endpoint-level "
                "touches only."
            ),
        },
    },
)
def me_benchmark_vs_industry(
    conn: DbDep,
    ctx: ApiContextDep,
    industry_jsic: Annotated[
        str | None,
        Query(
            max_length=10,
            description=("JSIC industry code prefix (e.g. 'D', 'E29'). NULL spans all majors."),
        ),
    ] = None,
    size_band: Annotated[
        str | None,
        Query(
            max_length=16,
            description="'small' / 'medium' / 'large' / 'all'. NULL → 'all'.",
        ),
    ] = None,
    prefecture: Annotated[
        str | None,
        Query(
            max_length=80,
            description="都道府県 exact match. NULL spans nationwide.",
        ),
    ] = None,
    window_days: Annotated[
        int,
        Query(
            ge=1,
            le=365,
            description="usage_events lookback (clamped 1..365, default 90).",
        ),
    ] = 90,
) -> JSONResponse:
    """GET /v1/me/benchmark_vs_industry — caller usage framed against cohort."""
    if ctx.key_hash is None:
        return JSONResponse(
            content={
                "error": {
                    "code": "auth_required",
                    "message": "/v1/me/benchmark_vs_industry requires an API key.",
                }
            },
            status_code=401,
        )
    _t0 = time.perf_counter()
    result: dict[str, Any] = benchmark_tools.benchmark_me_vs_industry_impl(
        conn=conn,
        key_hash=ctx.key_hash,
        industry_jsic=industry_jsic,
        size_band=size_band,
        prefecture=prefecture,
        window_days=window_days,
    )
    _latency_ms = int((time.perf_counter() - _t0) * 1000)
    cohort_size = result.get("cohort", {}).get("cohort_size") if isinstance(result, dict) else None
    log_usage(
        conn,
        ctx,
        "me.benchmark_vs_industry",
        latency_ms=_latency_ms,
        result_count=cohort_size if isinstance(cohort_size, int) else None,
        params={
            "industry_jsic": industry_jsic,
            "size_band": size_band,
            "prefecture": prefecture,
            "window_days": window_days,
        },
        strict_metering=True,
    )
    status_code = 400 if isinstance(result, dict) and result.get("error") else 200
    return JSONResponse(content=result, status_code=status_code)


__all__ = ["router", "CohortAverageBody"]
