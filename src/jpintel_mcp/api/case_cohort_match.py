"""REST handler for the R8 cohort matcher (POST /v1/cases/cohort_match).

Thin FastAPI wrapper over
``jpintel_mcp.mcp.autonomath_tools.cohort_match_tools.case_cohort_match_impl``.

This is the central matcher endpoint that answers the canonical jpcite
question: 「私と同業同規模同地域の採択企業はどの制度に通ったか?」 —
i.e. "what programs do similar businesses (same JSIC industry × same
employee/revenue band × same prefecture) actually get awarded?".

Design
------
- POST so the caller can send arrays for the two range bands without
  having to URL-encode them. The request body is a Pydantic model with
  loose, NULL-tolerant fields — every axis is optional so the caller
  can drop any one of them.
- Response is the same shape the MCP tool returns: matched_case_studies,
  matched_adoption_records, program_rollup, summary, axes_applied,
  sparsity_notes, plus the canonical
  ``{total, limit, offset, results}`` envelope.
- Billing: 1 metered request via ``log_usage`` with the
  ``case_cohort_match`` short name. Anonymous IPs route through the
  shared 3/day rate limit.

NO LLM. NO destructive write. NO new migration. Pure read-only over
existing case_studies + jpi_adoption_records corpora.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.mcp.autonomath_tools import cohort_match_tools

router = APIRouter(prefix="/v1/cases", tags=["case-studies"])


class CohortMatchBody(BaseModel):
    """Request body for POST /v1/cases/cohort_match."""

    model_config = ConfigDict(extra="ignore")

    industry_jsic: str | None = Field(
        default=None,
        max_length=10,
        description=(
            "JSIC industry code prefix (e.g. 'A' for 農林水産業 大分類, 'E29' "
            "for 食料品製造業 中分類). Prefix-matches against both jpintel "
            "case_studies.industry_jsic and the public adoption dataset "
            "industry_jsic_medium. Pass null to span "
            "all industries."
        ),
    )
    employee_count_range: list[int] | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        description=(
            "[low, high] inclusive employee-count band. Either bound may be "
            "null to leave it open. Filters case_studies.employees only — "
            "jpi_adoption_records does not carry employee count."
        ),
    )
    revenue_yen_range: list[int] | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        description=(
            "[low, high] yen revenue band. Approximated via capital_yen on "
            "case_studies (no explicit revenue column). NULL-tolerant — "
            "rows without capital_yen still pass when other axes match."
        ),
    )
    prefecture: str | None = Field(
        default=None,
        max_length=80,
        description=(
            "都道府県 exact match (e.g. '東京都', '群馬県'). Filters both "
            "sides. Pass null to span nationwide."
        ),
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Max rows per side. Clamped to [1, 100]. Default 20.",
    )


@router.post(
    "/cohort_match",
    summary="Cohort matcher (採択事例 × 業種 × 規模 × 地域)",
    description=(
        "Returns the 採択 cohort that matches the caller's 4-axis profile "
        "(industry / employees / revenue / prefecture), pulling case_studies "
        "(jpintel.db, 2,286 採択事例) **and** jpi_adoption_records "
        "(autonomath.db, 201,845 V4-absorbed METI/MAFF 採択結果). The "
        "response includes:\n\n"
        "- ``matched_case_studies`` — up to ``limit`` rich case rows.\n"
        "- ``matched_adoption_records`` — up to ``limit`` thin V4 rows.\n"
        "- ``program_rollup`` — per-program count + average amount + cohort "
        "share + example case_ids.\n"
        "- ``summary`` — total cohort rows, distinct programs, mean / median "
        "amount.\n"
        "- ``axes_applied`` — which filters were honored on each side "
        "(adoption_records side does not carry employee / revenue).\n"
        "- ``sparsity_notes`` — honest disclosure of which fields are thin "
        "(amount populated on ~1.9% of case_studies, 0% of adoption_records).\n\n"
        "**Single ¥3/req billing event.** No LLM call, no destructive write. "
        "§52 / §47条の2 / 行政書士法 §1 disclaimer envelope on every result — "
        "output is information retrieval, not 申請代理 / 税務助言 / 経営判断."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {
            "description": (
                "Cohort match envelope. ``total`` = combined row count, "
                "``program_rollup`` is sorted by appearance_count DESC."
            ),
        },
    },
)
def cohort_match(
    conn: DbDep,
    ctx: ApiContextDep,
    body: Annotated[
        CohortMatchBody,
        Body(
            description=(
                "Cohort filter body. All four axes are optional — pass any "
                "subset; null fields are treated as 'span everything'."
            ),
        ),
    ],
) -> JSONResponse:
    """POST /v1/cases/cohort_match — cohort matcher REST entry point."""
    _t0 = time.perf_counter()
    result: dict[str, Any] = cohort_match_tools.case_cohort_match_impl(
        industry_jsic=body.industry_jsic,
        employee_count_range=body.employee_count_range,
        revenue_yen_range=body.revenue_yen_range,
        prefecture=body.prefecture,
        limit=body.limit,
    )
    _latency_ms = int((time.perf_counter() - _t0) * 1000)

    result_count = len(result.get("results", [])) if isinstance(result.get("results"), list) else 0
    log_usage(
        conn,
        ctx,
        "case_cohort_match",
        latency_ms=_latency_ms,
        result_count=result_count,
        params={
            "industry_jsic": body.industry_jsic,
            "prefecture": body.prefecture,
            "limit": body.limit,
        },
        strict_metering=True,
    )
    status_code = 400 if isinstance(result, dict) and result.get("error") else 200
    return JSONResponse(content=result, status_code=status_code)


__all__ = ["router", "CohortMatchBody"]
