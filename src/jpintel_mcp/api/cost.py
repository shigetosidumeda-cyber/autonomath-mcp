"""Cost preview endpoint (`POST /v1/cost/preview`) — anti-runaway 三点セット A.

Why this exists
---------------
An LLM agent that loops `search_programs` → `batch_get_programs` → ... can
accidentally rack up ¥10,000+ in a few minutes if the surrounding code path
has a bug. Customers cannot defend against this without first knowing what
a planned call sequence will *cost* — by the time the bill arrives the
spend has already happened. Cost preview gives them a deterministic, FREE
(non-metered, ¥0) prediction so they can:

  1. Refuse to dispatch a stack whose `predicted_total_yen` exceeds their
     internal budget.
  2. Show the user a "this will cost ¥N" confirmation before kicking the
     job off.
  3. Combine with `X-Cost-Cap-JPY` so the cap is set off the previewed
     value, not a hardcoded guess.

Pricing model (immutable)
-------------------------
AutonoMath is pure metered ¥3/req 税別 (税込 ¥3.30) per
`project_autonomath_business_model`. There are NO tier SKUs, NO bulk
discounts, NO seat fees. The math is therefore trivial: predicted cost =
billing_units * ¥3 where billing_units = sum-over-calls(weight) * iterations.

Today every tool counts as 1 billing unit. `batch_*` tools take a list of
ids but still bill as 1 unit per call (parity with the current production
metering posture in `deps.log_usage`). If that ever changes (e.g. N-weighted
batch) the weight table below is the single place to bump.

Free-tier note
--------------
This endpoint is rate-limited per IP/key (50/min via process-local bucket)
but never enters `usage_events` and never reports a Stripe usage_record.
Even at 50/min sustained the worst case is "one paying customer occupies a
process-local cache slot" — no cost path.

§52 disclaimer
--------------
Tax-related cost previews still carry the 税理士法 §52 fence in the
response (LLM agents must relay it verbatim).
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from jpintel_mcp.api._corpus_snapshot import compute_corpus_snapshot
from jpintel_mcp.api.deps import DbDep

logger = logging.getLogger("jpintel.cost")

router = APIRouter(prefix="/v1/cost", tags=["cost"])

# ---------------------------------------------------------------------------
# Pricing constants
# ---------------------------------------------------------------------------

# Pure metered ¥3/req 税別 (memory: project_autonomath_business_model).
# 税込 ¥3.30 — but the preview returns 税別 to mirror the
# Stripe usage_records line item; JCT is added at invoice render.
_UNIT_PRICE_YEN: int = 3

# Per-tool billing weight. 1.0 = single billing unit (=¥3) per call. We keep
# the table even though every entry is currently 1.0 because the moment we
# swap to N-weighted batch billing this table is the ONLY place to update —
# the customer-cap middleware and Stripe usage_records reporter both read
# off the same `billing_units * _UNIT_PRICE_YEN` formula.
_TOOL_WEIGHTS: dict[str, float] = {
    # Discovery — flat per-call.
    "search_programs": 1.0,
    "get_program": 1.0,
    "batch_get_programs": 1.0,  # 1 unit per call (parity w/ current metering).
    "search_case_studies": 1.0,
    "get_case_study": 1.0,
    "search_loan_programs": 1.0,
    "get_loan_program": 1.0,
    "search_enforcement_cases": 1.0,
    "get_enforcement_case": 1.0,
    "search_laws": 1.0,
    "get_law": 1.0,
    "search_court_decisions": 1.0,
    "get_court_decision": 1.0,
    "search_bids": 1.0,
    "get_bid": 1.0,
    "search_invoice_registrants": 1.0,
    "get_invoice_registrant": 1.0,
    "search_tax_rulesets": 1.0,
    "get_tax_ruleset": 1.0,
    "evaluate_tax_ruleset": 1.0,
    "calendar_deadlines": 1.0,
    # AM tools.
    "active_programs_at": 1.0,
    "search_acceptance_stats_am": 1.0,
    "search_tax_incentives": 1.0,
    "search_certifications": 1.0,
    "list_open_programs": 1.0,
    "search_by_law": 1.0,
    "search_loans_am": 1.0,
    "check_enforcement_am": 1.0,
    "search_mutual_plans_am": 1.0,
    "get_law_article_am": 1.0,
    "search_gx_programs_am": 1.0,
    "list_tax_sunset_alerts": 1.0,
    "get_annotations": 1.0,
    "validate": 1.0,
    "get_provenance": 1.0,
    "get_provenance_for_fact": 1.0,
    "graph_traverse": 1.0,
    "unified_lifecycle_calendar": 1.0,
    "program_lifecycle": 1.0,
    "program_abstract_structured": 1.0,
    "prerequisite_chain": 1.0,
    "rule_engine_check": 1.0,
    "related_programs": 1.0,
    "deep_health_am": 1.0,
}

# Default weight for any tool not in the table (forward compatibility).
# Returning 1.0 is the safe overshoot — agents should expect "at most this
# much"; an unknown future tool that turns out to be free is a pleasant
# surprise rather than a billing event.
_DEFAULT_TOOL_WEIGHT: float = 1.0

# Tax-relevant tools that must surface the §52 fence in the preview response
# even though the preview itself is non-metered. An LLM agent that previews
# a tax-judgment call sequence must still know the surfaced advice carries
# the fence.
_TAX_RELEVANT_TOOLS: frozenset[str] = frozenset(
    {
        "search_tax_rulesets",
        "get_tax_ruleset",
        "evaluate_tax_ruleset",
        "search_tax_incentives",
        "list_tax_sunset_alerts",
    }
)

_TAX_DISCLAIMER = (
    "本情報は税務助言ではありません。AutonoMath は公的機関が公表する税制・補助金・"
    "法令情報を検索・整理して提供するサービスで、税理士法 §52 に基づき個別具体的な"
    "税務判断・申告書作成代行は行いません。個別案件は資格を有する税理士に必ずご相談"
    "ください。本サービスの情報利用により生じた損害について、当社は一切の責任を負いません。"
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CostPreviewCall(BaseModel):
    """A single planned tool invocation inside a stack.

    `args` is opaque — we don't validate against the underlying tool schema
    here because the preview is meant to be cheap (no DB read for shape).
    Cost is determined by `tool` only; `args` is round-tripped into the
    `breakdown[]` for caller display only.
    """

    tool: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "Tool name as it appears in MCP / REST. Example: search_programs, "
            "batch_get_programs, evaluate_tax_ruleset. Unknown tools default "
            "to weight=1.0 (¥3) so the prediction is a safe overshoot."
        ),
    )
    args: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Tool arguments. Opaque to the preview engine — passed through "
            "into the per-call breakdown so the caller can display the plan."
        ),
    )


class CostPreviewRequest(BaseModel):
    """`POST /v1/cost/preview` request body.

    Either `stack_or_calls` is the planned sequence of tool calls (one row
    per call). `iterations` multiplies the entire stack — handy for agent
    loops that fan out the same stack across N inputs.
    """

    stack_or_calls: list[CostPreviewCall] = Field(
        min_length=1,
        max_length=500,
        description=(
            "Planned tool-call stack. Each entry counts toward "
            "billing_units. The 500-entry cap is a safety net — preview is "
            "free but a 100k-entry stack would still occupy server memory."
        ),
    )
    iterations: int = Field(
        default=1,
        ge=1,
        le=10_000,
        description=(
            "Multiplier for the whole stack. Use this when an agent loop "
            "fans out the same stack across N inputs. Default 1."
        ),
    )


class CostPreviewBreakdownEntry(BaseModel):
    tool: str
    weight: float
    yen: int  # tool's contribution to predicted_total_yen for ONE iteration


class CostPreviewResponse(BaseModel):
    predicted_total_yen: int
    billing_units: float  # Sum of weights * iterations
    unit_price_yen: int = _UNIT_PRICE_YEN
    iterations: int
    breakdown: list[CostPreviewBreakdownEntry]
    corpus_snapshot_id: str
    corpus_checksum: str
    # 税理士法 §52 fence (only present when the stack touches tax tools).
    # Pydantic's `extra="allow"` is not used here because we want the field
    # in the OpenAPI schema; it's optional and `None` for stacks with no
    # tax-relevant calls.
    disclaimer: str | None = None
    metered: Literal[False] = False  # the preview itself is FREE, ¥0


# ---------------------------------------------------------------------------
# Per-IP rate limit (50/min) — mirrors anon_limit identity extraction
# ---------------------------------------------------------------------------

_PREVIEW_RATE_MAX = 50
_PREVIEW_RATE_WINDOW_S = 60.0
_preview_hits: dict[str, list[float]] = {}
_preview_hits_lock = threading.Lock()


def _identity_for(request: Request) -> str:
    """Return a stable identity string for rate-limit bucketing.

    Prefer X-API-Key hash (16 hex prefix) > Fly-Client-IP > X-Forwarded-For
    first hop > request.client.host. Mirrors `rate_limit.py` priority so a
    paid caller's preview rate budget tracks their other request budget.
    """
    raw = request.headers.get("x-api-key")
    if raw and raw.strip():
        return "k:" + hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()[:16]
    auth = request.headers.get("authorization", "")
    parts = auth.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
        return "k:" + hashlib.sha256(parts[1].strip().encode("utf-8")).hexdigest()[:16]
    fly = request.headers.get("fly-client-ip", "").strip()
    if fly:
        return f"ip:{fly}"
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return f"ip:{first}"
    if request.client:
        return f"ip:{request.client.host}"
    return "ip:unknown"


def _rate_check(identity: str) -> tuple[bool, int]:
    """Sliding-window 50/min check. Returns (allowed, retry_after_s)."""
    now = time.monotonic()
    cutoff = now - _PREVIEW_RATE_WINDOW_S
    with _preview_hits_lock:
        bucket = _preview_hits.setdefault(identity, [])
        # Drop expired hits in-place.
        live = [t for t in bucket if t >= cutoff]
        if len(live) >= _PREVIEW_RATE_MAX:
            # Oldest hit + window = next slot.
            retry = max(1, int(live[0] + _PREVIEW_RATE_WINDOW_S - now + 0.999))
            _preview_hits[identity] = live
            return False, retry
        live.append(now)
        _preview_hits[identity] = live
        return True, 0


def _reset_preview_rate_state() -> None:
    """Test helper: drop the per-IP preview rate-limit bucket."""
    with _preview_hits_lock:
        _preview_hits.clear()


# ---------------------------------------------------------------------------
# Cost computation (deterministic, no DB execution)
# ---------------------------------------------------------------------------


def compute_predicted_cost(
    calls: list[CostPreviewCall], iterations: int
) -> tuple[int, float, list[CostPreviewBreakdownEntry], bool]:
    """Return (predicted_total_yen, billing_units, breakdown, has_tax_tool).

    Deterministic — same input always yields same output. The breakdown
    rows are produced for ONE iteration; the iteration multiplier is
    folded into `predicted_total_yen` and `billing_units` only.
    """
    breakdown: list[CostPreviewBreakdownEntry] = []
    units_per_iter: float = 0.0
    has_tax_tool = False
    for c in calls:
        weight = _TOOL_WEIGHTS.get(c.tool, _DEFAULT_TOOL_WEIGHT)
        units_per_iter += weight
        if c.tool in _TAX_RELEVANT_TOOLS:
            has_tax_tool = True
        breakdown.append(
            CostPreviewBreakdownEntry(
                tool=c.tool,
                weight=weight,
                yen=int(round(weight * _UNIT_PRICE_YEN)),
            )
        )
    billing_units = units_per_iter * iterations
    predicted_total_yen = int(round(billing_units * _UNIT_PRICE_YEN))
    return predicted_total_yen, billing_units, breakdown, has_tax_tool


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/preview",
    response_model=CostPreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Predict the cost of a planned tool-call stack (FREE, ¥0)",
    description=(
        "Returns a deterministic ¥-cost prediction for a planned sequence of "
        "tool calls without executing them. Anti-runaway 三点セット A.\n\n"
        "**Pricing**: ¥3/req metered (税別; 税込 ¥3.30). The preview itself "
        "is FREE — no `usage_events` row, no Stripe usage_record. Rate-"
        "limited 50/min per IP/key.\n\n"
        "**§52 fence**: when the stack touches tax-relevant tools "
        "(`evaluate_tax_ruleset`, `search_tax_incentives`, etc.) the response "
        "carries a `disclaimer` field. LLM agents MUST relay it.\n\n"
        "**Operator**: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708). "
        "Brand: 税務会計AI."
    ),
)
def post_cost_preview(
    payload: CostPreviewRequest,
    conn: DbDep,
    request: Request,
) -> JSONResponse:
    identity = _identity_for(request)
    allowed, retry_after_s = _rate_check(identity)
    if not allowed:
        # 429 with Retry-After. Mirrors the rate-limit middleware shape so an
        # agent that already handles 429 here doesn't need a separate code
        # path for cost preview throttling.
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": {
                    "code": "rate_limited",
                    "message": (
                        "Cost preview rate limit exceeded "
                        f"({_PREVIEW_RATE_MAX}/min per IP/key)."
                    ),
                    "retry_after": retry_after_s,
                    "bucket": "cost_preview",
                }
            },
            headers={"Retry-After": str(retry_after_s)},
        )

    predicted_total_yen, billing_units, breakdown, has_tax_tool = (
        compute_predicted_cost(payload.stack_or_calls, payload.iterations)
    )
    snapshot_id, checksum = compute_corpus_snapshot(conn)
    body: dict[str, Any] = {
        "predicted_total_yen": predicted_total_yen,
        "billing_units": billing_units,
        "unit_price_yen": _UNIT_PRICE_YEN,
        "iterations": payload.iterations,
        "breakdown": [b.model_dump() for b in breakdown],
        "corpus_snapshot_id": snapshot_id,
        "corpus_checksum": checksum,
        "disclaimer": _TAX_DISCLAIMER if has_tax_tool else None,
        "metered": False,
    }
    # Explicit ¥0 metering header so an LLM agent reading response headers
    # alone can confirm this call did not bill the customer.
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=body,
        headers={"X-Metered": "false", "X-Cost-Yen": "0"},
    )


__all__ = [
    "CostPreviewRequest",
    "CostPreviewResponse",
    "compute_predicted_cost",
    "router",
    "_reset_preview_rate_state",
    "_TOOL_WEIGHTS",
    "_UNIT_PRICE_YEN",
]
