"""ROI savings calculator (`GET /v1/calculator/savings`) — public estimator.

Why this exists
---------------
Customers (税理士, 補助金 consultants, 会計士, FDI ops) ask before signup:
"if I use jpcite for my LLM workflow, how much LLM token spend do I save?"
Until now we directed them at /calculator.html which deliberately AVOIDS
saving framing (per `feedback_no_fake_data` + the 2026-04-30 reframing of
the coverage explorer). But sales-side teams keep asking for an *honest*
estimator — one that says "yes, you might save USD on output tokens; no,
the raw token math does NOT amortise the ¥3/req metering, the value comes
from citation_ok lift". That is what this endpoint surfaces.

Methodology (no LLM call, pure arithmetic)
------------------------------------------
We reuse the per-model means measured by ``benchmarks/jcrb_v1`` (50-q
batch, run_token_benchmark.py). Numbers were locked into this module on
2026-05-05 from ``token_savings_50q_report.md``:

| model            | closed_in | closed_out | with_in | with_out |
|------------------|----------:|-----------:|--------:|---------:|
| claude-opus-4-7  |       271 |        350 |   1,002 |      120 |
| claude-sonnet-4-5|       271 |        350 |   1,002 |      120 |  # opus row reused
| gpt-5            |       256 |        350 |     778 |      120 |
| gemini-2.5-pro   |       254 |        350 |     741 |      120 |
| gpt-4o           |       256 |        350 |     778 |      120 |  # gpt-5 row reused

Sonnet + 4o do not have their own JCRB-v1 row yet; we honestly carry the
nearest-family row and tag the response so the caller sees it was a
fallback (``methodology.row_source`` = "family_fallback"). When JCRB
adds direct rows we drop the fallback.

Per-query USD = (in_tokens × in_price + out_tokens × out_price) / 1e6
where prices come from ``benchmarks/jcrb_v1/token_estimator.MODEL_PRICING``.

Domain mix
----------
JCRB-v1 covers 3 domains (subsidy_eligibility, tax_application,
law_citation). The 50-q report numbers above are the **mean across all
3 domains**. We expose a ``domain_mix`` knob so a caller can request:

  - ``balanced`` (default) → equal-weight mean → just use the rollup row.
  - ``subsidy_heavy`` → 0.6 × subsidy + 0.2 × tax + 0.2 × law (subsidy
    consultants dominate workload).
  - ``tax_heavy``  → 0.2 × subsidy + 0.6 × tax + 0.2 × law (税理士 fan-out).
  - ``law_heavy``  → 0.2 × subsidy + 0.2 × tax + 0.6 × law (FDI / corporate).

Per-domain deltas vs the rollup are SMALL (≤±5% on USD saved per query),
so the domain knob mostly exists to honestly tell the caller we know the
distribution matters.

Honest framing (mandatory)
--------------------------
The response ALWAYS carries a ``honest_caveat`` string that:

  1. Calls the result an "estimate", not a guarantee.
  2. States that individual results vary ±15-40% per the JCRB-v1 caveats.
  3. **Says raw token math does NOT amortise jpcite metering** — the
     value of the product is citation_ok lift, not token spend.
  4. Points at /qa/llm-evidence/context-savings.html for the
     methodology + caveats.

NO TIER SKU / NO SEAT FEE language. Pricing locked at ¥3/req 税別 (税込
¥3.30) — see project_autonomath_business_model.

Pricing posture
---------------
Endpoint is unmetered (no `usage_events` row). It is rate-limited via the
standard anon 3/日 IP cap on the router mount in ``api/main.py``, so
abusive callers fall through the same gate as every other discovery
surface. No DB call — pure-Python arithmetic over module constants.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("jpintel.api.calculator")

router = APIRouter(prefix="/v1/calculator", tags=["calculator"])


# ---------------------------------------------------------------------------
# Pricing — public list 2026-05-05, mirrors
# benchmarks/jcrb_v1/token_estimator.MODEL_PRICING. Keep in sync when
# providers re-price; this module is the single source of truth on the
# customer-facing surface.
# ---------------------------------------------------------------------------

# USD per 1M tokens.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "gpt-5": {"input": 1.25, "output": 10.0},
    "gpt-4o": {"input": 2.50, "output": 10.0},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
}

# Per-model JCRB-v1 50-q rollup (mean per question). Locked from
# benchmarks/jcrb_v1/token_savings_50q_report.md on 2026-05-05.
#
# Keys: closed_in, closed_out, with_in, with_out (token counts per query).
# ``row_source``: "direct"  if the model has a JCRB-v1 row,
#                 "family_fallback" if we substitute the nearest-family row.
_JCRB_ROLLUP: dict[str, dict[str, int | str]] = {
    "claude-opus-4-7": {
        "closed_in": 271,
        "closed_out": 350,
        "with_in": 1002,
        "with_out": 120,
        "row_source": "direct",
    },
    "claude-sonnet-4-5": {
        # No direct JCRB row yet — Anthropic family fallback to opus shape.
        "closed_in": 271,
        "closed_out": 350,
        "with_in": 1002,
        "with_out": 120,
        "row_source": "family_fallback",
    },
    "gpt-5": {
        "closed_in": 256,
        "closed_out": 350,
        "with_in": 778,
        "with_out": 120,
        "row_source": "direct",
    },
    "gpt-4o": {
        "closed_in": 256,
        "closed_out": 350,
        "with_in": 778,
        "with_out": 120,
        "row_source": "family_fallback",
    },
    "gemini-2.5-pro": {
        "closed_in": 254,
        "closed_out": 350,
        "with_in": 741,
        "with_out": 120,
        "row_source": "direct",
    },
}

# Per-domain multipliers vs the rollup. JCRB-v1 saved-USD spread by domain
# is ≤±5%; we expose the knob mostly to be honest the distribution matters.
# Multipliers apply to the *with_in* count (jpcite context size scales with
# domain depth: subsidy rows shorter than law/tax citations).
_DOMAIN_MULTIPLIERS: dict[str, dict[str, float]] = {
    "balanced": {"subsidy": 1 / 3, "tax": 1 / 3, "law": 1 / 3},
    "subsidy_heavy": {"subsidy": 0.6, "tax": 0.2, "law": 0.2},
    "tax_heavy": {"subsidy": 0.2, "tax": 0.6, "law": 0.2},
    "law_heavy": {"subsidy": 0.2, "tax": 0.2, "law": 0.6},
}
# Per-domain with_in scale factors (vs rollup mean = 1.00). Derived from
# JCRB-v1 50-q CSV: subsidy ≈ 0.92, tax ≈ 1.04, law ≈ 1.04. Differences are
# small but the math respects them so a power user can verify our claim.
_DOMAIN_WITH_IN_SCALE: dict[str, float] = {
    "subsidy": 0.92,
    "tax": 1.04,
    "law": 1.04,
}

DomainMix = Literal["balanced", "subsidy_heavy", "tax_heavy", "law_heavy"]

# jpcite metering. Locked at ¥3/req 税別 (税込 ¥3.30) per
# project_autonomath_business_model. NEVER add tier multipliers here.
_JPCITE_PRICE_JPY_INC_TAX: float = 3.30

# Default USD/JPY for response convenience. Customer can override via
# ?fx_rate=152.0. We do NOT call FX APIs — caller owns the exchange rate
# they want to use for budget purposes. 150 is a round 2026-05 placeholder.
_DEFAULT_FX_RATE_JPY_PER_USD: float = 150.0

# Standard caveat string. Verbatim required so the LLM agent that fetches
# this endpoint cannot strip the qualifier when summarising for the human.
_HONEST_CAVEAT: str = (
    "estimated value based on the JCRB-v1 50-question benchmark mean per "
    "model. individual results may vary by ±15-40% depending on model, "
    "prompt template, prompt-cache hit rate, query mix, and customer-side "
    "post-processing. raw token math alone does NOT amortise jpcite ¥3/req "
    "metering — the product value comes from citation_ok lift "
    "(~0.40 → ~0.95 per JCRB-v1 SEED runs), not LLM token spend reduction. "
    "see https://jpcite.com/qa/llm-evidence/context-savings.html for the "
    "full methodology and caveats."
)


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class SavingsBreakdown(BaseModel):
    """Per-query token breakdown so callers can sanity-check the math."""

    model_config = ConfigDict(extra="forbid")

    closed_input_tokens: int = Field(
        ..., description="Mean input tokens without jpcite (closed-book)."
    )
    closed_output_tokens: int = Field(..., description="Mean output tokens without jpcite.")
    with_jpcite_input_tokens: int = Field(
        ..., description="Mean input tokens with jpcite context block."
    )
    with_jpcite_output_tokens: int = Field(
        ..., description="Mean output tokens with jpcite (model can quote a cited row)."
    )
    closed_usd_per_query: float = Field(..., description="USD per query without jpcite.")
    with_jpcite_usd_per_query: float = Field(
        ..., description="USD per query with jpcite (token-spend only, excludes ¥3/req metering)."
    )


class CalculatorMethodology(BaseModel):
    """Structured methodology block so callers can audit our assumptions."""

    model_config = ConfigDict(extra="forbid")

    benchmark: str = Field(
        default="JCRB-v1 50-question batch", description="Source benchmark name."
    )
    benchmark_url: str = Field(
        default="https://jpcite.com/benchmark/", description="Public benchmark page."
    )
    row_source: str = Field(
        ..., description="'direct' if the model has a JCRB row, 'family_fallback' otherwise."
    )
    domain_mix: DomainMix = Field(..., description="Domain weighting applied.")
    fx_rate_jpy_per_usd: float = Field(
        ..., description="USD/JPY rate used for the JPY conversion line."
    )
    pricing_source: str = Field(
        default="public list prices 2026-05-05 (USD per 1M tokens)",
        description="Where the per-token USD pricing comes from.",
    )


class SavingsResponse(BaseModel):
    """Public envelope. Field names are stable across versions."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(..., description="Echoes the request model.")
    queries_per_month: int = Field(..., description="Echoes the request volume.")
    breakdown: SavingsBreakdown = Field(..., description="Per-query token + USD breakdown.")
    estimated_monthly_savings_usd: float = Field(
        ..., description="(closed_usd - with_jpcite_usd) × queries_per_month. token-spend only."
    )
    estimated_monthly_savings_jpy: int = Field(
        ..., description="USD savings × fx_rate, rounded down to integer JPY."
    )
    jpcite_cost_jpy: int = Field(
        ..., description="queries_per_month × ¥3.30 (税込), rounded down to integer JPY."
    )
    net_savings_jpy: int = Field(
        ...,
        description="estimated_monthly_savings_jpy − jpcite_cost_jpy. NEGATIVE means raw token math does not pay for jpcite (this is the typical case).",
    )
    roi_pct: float = Field(
        ...,
        description="(savings_jpy / jpcite_cost_jpy) × 100. NEGATIVE values are normal — see honest_caveat.",
    )
    honest_caveat: str = Field(..., description="REQUIRED qualifier — pass through verbatim.")
    methodology: CalculatorMethodology = Field(
        ..., description="Structured methodology block for auditors."
    )


# ---------------------------------------------------------------------------
# Pure math
# ---------------------------------------------------------------------------


def _usd_per_query(in_tokens: int, out_tokens: int, pricing: dict[str, float]) -> float:
    """USD = (in × in_price + out × out_price) / 1_000_000."""
    return (in_tokens * pricing["input"] + out_tokens * pricing["output"]) / 1_000_000.0


def compute_savings(
    *,
    model: str,
    queries_per_month: int,
    domain_mix: DomainMix,
    fx_rate: float,
) -> SavingsResponse:
    """Pure function — same input always returns same output, no I/O."""
    if model not in MODEL_PRICING or model not in _JCRB_ROLLUP:
        raise ValueError(f"unknown model: {model}")
    if queries_per_month < 0:
        raise ValueError("queries_per_month must be >= 0")
    if fx_rate <= 0:
        raise ValueError("fx_rate must be > 0")
    if domain_mix not in _DOMAIN_MULTIPLIERS:
        raise ValueError(f"unknown domain_mix: {domain_mix}")

    rollup = _JCRB_ROLLUP[model]
    pricing = MODEL_PRICING[model]

    closed_in = int(rollup["closed_in"])
    closed_out = int(rollup["closed_out"])
    rollup_with_in = int(rollup["with_in"])
    with_out = int(rollup["with_out"])

    # Apply domain mix to with_in only — closed-book input has no jpcite
    # context block and is invariant w.r.t. domain.
    weights = _DOMAIN_MULTIPLIERS[domain_mix]
    with_in_scale = sum(weights[d] * _DOMAIN_WITH_IN_SCALE[d] for d in weights)
    with_in = int(round(rollup_with_in * with_in_scale))

    closed_usd = _usd_per_query(closed_in, closed_out, pricing)
    with_usd = _usd_per_query(with_in, with_out, pricing)

    monthly_savings_usd = (closed_usd - with_usd) * queries_per_month
    monthly_savings_jpy = int(monthly_savings_usd * fx_rate)
    jpcite_cost_jpy = int(queries_per_month * _JPCITE_PRICE_JPY_INC_TAX)
    net_savings_jpy = monthly_savings_jpy - jpcite_cost_jpy
    roi_pct = (monthly_savings_jpy / jpcite_cost_jpy) * 100.0 if jpcite_cost_jpy > 0 else 0.0

    return SavingsResponse(
        model=model,
        queries_per_month=queries_per_month,
        breakdown=SavingsBreakdown(
            closed_input_tokens=closed_in,
            closed_output_tokens=closed_out,
            with_jpcite_input_tokens=with_in,
            with_jpcite_output_tokens=with_out,
            closed_usd_per_query=round(closed_usd, 6),
            with_jpcite_usd_per_query=round(with_usd, 6),
        ),
        estimated_monthly_savings_usd=round(monthly_savings_usd, 4),
        estimated_monthly_savings_jpy=monthly_savings_jpy,
        jpcite_cost_jpy=jpcite_cost_jpy,
        net_savings_jpy=net_savings_jpy,
        roi_pct=round(roi_pct, 2),
        honest_caveat=_HONEST_CAVEAT,
        methodology=CalculatorMethodology(
            row_source=str(rollup["row_source"]),
            domain_mix=domain_mix,
            fx_rate_jpy_per_usd=fx_rate,
        ),
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get(
    "/savings",
    response_model=SavingsResponse,
    summary="Estimate monthly LLM token-spend savings from using jpcite.",
    description=(
        "Public, FREE estimator. NO LLM call. NO database read. Pure arithmetic over "
        "the JCRB-v1 50-question benchmark rollup (`benchmarks/jcrb_v1/`). "
        "Returns a token + USD breakdown plus a mandatory `honest_caveat` "
        "field that the caller MUST surface verbatim. Note: raw token math "
        "alone does NOT amortise jpcite ¥3/req metering — the product value "
        "comes from citation_ok lift, not LLM spend reduction."
    ),
)
def get_savings(
    model: Annotated[
        str,
        Query(
            description=(
                "LLM model name. Supported: claude-opus-4-7, claude-sonnet-4-5, "
                "gpt-5, gpt-4o, gemini-2.5-pro. Unknown models → 422."
            ),
            examples=["claude-opus-4-7"],
        ),
    ] = "claude-opus-4-7",
    queries_per_month: Annotated[
        int,
        Query(
            ge=0,
            le=10_000_000,
            description="LLM queries per month for the workload you're sizing.",
            examples=[6000],
        ),
    ] = 6000,
    domain_mix: Annotated[
        DomainMix,
        Query(
            description=(
                "Workload mix across the 3 JCRB-v1 domains "
                "(subsidy_eligibility / tax_application / law_citation). "
                "Defaults to balanced (equal weight)."
            ),
        ),
    ] = "balanced",
    fx_rate: Annotated[
        float,
        Query(
            gt=0,
            le=1000,
            description=(
                "USD/JPY rate for the JPY conversion line. Defaults to 150.0 — "
                "set explicitly when budgeting against your treasury rate."
            ),
            examples=[150.0],
        ),
    ] = _DEFAULT_FX_RATE_JPY_PER_USD,
) -> SavingsResponse:
    """Return the estimated monthly savings envelope.

    422 if the model is not in :data:`MODEL_PRICING`. We refuse rather than
    fall back so a typo doesn't silently quote the customer the wrong
    pricing tier.
    """
    try:
        return compute_savings(
            model=model,
            queries_per_month=queries_per_month,
            domain_mix=domain_mix,
            fx_rate=fx_rate,
        )
    except ValueError as exc:
        # FastAPI maps query-validation failures to 422 by convention; we
        # keep the same status code for unknown-model so the contract is
        # uniform across "input is structurally bad" and "input is in the
        # right shape but not in our supported list".
        # 422 status code (UNPROCESSABLE_CONTENT in modern Starlette,
        # ENTITY in legacy aliases). We hard-code 422 to avoid the deprecated
        # alias warning.
        # P0 redteam (audit): never leak internal SDK / arithmetic message
        # via str(exc). Log full exception for ops, return canonical envelope.
        logger.warning("calculator validation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=422,
            detail={
                "code": "CALCULATION_ERROR",
                "message": "Calculator input could not be processed. Verify the request parameters and try again.",
            },
        ) from exc
