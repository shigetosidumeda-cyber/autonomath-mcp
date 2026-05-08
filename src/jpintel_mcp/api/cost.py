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
jpcite is pure metered ¥3/req 税別 (税込 ¥3.30) per
`project_autonomath_business_model`. There are NO tier SKUs, NO bulk
discounts, NO seat fees. The math is therefore trivial: predicted cost =
billing_units * ¥3 where billing_units = sum-over-calls(weight) * iterations.

Most discovery tools count as 1 billing unit. Fan-out tools use their
argument shape to predict the same `quantity` that the handler records in
`usage_events`: batch program reads count deduped IDs, DD batch counts
deduped corporate numbers, and DD export counts corporate numbers plus the
bundle-class quantity multiplier.

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

import contextlib
import hashlib
import logging
import sqlite3
import threading
import time
import unicodedata
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.api._corpus_snapshot import compute_corpus_snapshot
from jpintel_mcp.api.deps import (  # noqa: TC001 (runtime for FastAPI Depends resolution)
    DbDep,
    hash_api_key,
)

logger = logging.getLogger("jpintel.cost")

router = APIRouter(prefix="/v1/cost", tags=["cost"])

# ---------------------------------------------------------------------------
# Pricing constants
# ---------------------------------------------------------------------------

# Pure metered ¥3/req 税別 (memory: project_autonomath_business_model).
# 税込 ¥3.30 — but the preview returns 税別 to mirror the
# Stripe usage_records line item; JCT is added at invoice render.
_UNIT_PRICE_YEN: int = 3

# Per-tool billing weight. 1.0 = single billing unit (=¥3) per call. The
# weights ladder by output size: most discovery tools stay at 1.0, while
# composite/bulk tools (`am.dd_export`, `bulk_evaluate`) consume weights ≥1
# in proportion to artifact size. Customer is always charged
# `weight × ¥3` per unit of work — no tier SKU. The customer-cap middleware
# and Stripe usage_records reporter both read off the same
# `billing_units * _UNIT_PRICE_YEN` formula, so updating a weight here
# automatically propagates everywhere.
_TOOL_WEIGHTS: dict[str, float] = {
    # Discovery — flat per-call.
    "search_programs": 1.0,
    "get_program": 1.0,
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

# Default weight for any tool not in the table (forward compatibility). Unknown
# single-call tools still preview as 1 unit, but known fan-out tools fail
# closed when required args are missing so the preview cannot understate a bill.
_DEFAULT_TOOL_WEIGHT: float = 1.0

_BATCH_PROGRAM_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "batch_get_programs",
        "batch_get_programs_v1_programs_batch_post",
        "programs.batch",
        "v1.programs.batch",
        "/v1/programs/batch",
    }
)
_DD_BATCH_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "dd_batch",
        "post_dd_batch_v1_am_dd_batch_post",
        "am.dd_batch",
        "v1.am.dd_batch",
        "/v1/am/dd_batch",
    }
)
_DD_EXPORT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "dd_export",
        "post_dd_export_v1_am_dd_export_post",
        "am.dd_export",
        "v1.am.dd_export",
        "/v1/am/dd_export",
    }
)
_GROUP_GRAPH_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "group_graph",
        "get_group_graph_v1_am_group_graph_get",
        "am.group_graph",
        "v1.am.group_graph",
        "/v1/am/group_graph",
    }
)
_AUDIT_WORKPAPER_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "audit.workpaper",
        "render_workpaper_v1_audit_workpaper_post",
        "compose_audit_workpaper",
        "v1.audit.workpaper",
        "/v1/audit/workpaper",
    }
)
_AUDIT_BATCH_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "audit.batch_evaluate",
        "batch_evaluate_v1_audit_batch_evaluate_post",
        "audit_batch_evaluate",
        "v1.audit.batch_evaluate",
        "/v1/audit/batch_evaluate",
    }
)
_AUDIT_SNAPSHOT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "audit.snapshot_attestation",
        "snapshot_attestation_v1_audit_snapshot_attestation_get",
        "v1.audit.snapshot_attestation",
        "/v1/audit/snapshot_attestation",
    }
)
_FUNDING_STACK_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "funding_stack.check",
        "check_funding_stack_v1_funding_stack_check_post",
        "v1.funding_stack.check",
        "/v1/funding_stack/check",
    }
)
_COMPATIBILITY_TABLE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "artifacts.compatibility_table",
        "compatibility_table",
        "createCompatibilityTable",
        "create_compatibility_table",
        "create_compatibility_table_v1_artifacts_compatibility_table_post",
        "v1.artifacts.compatibility_table",
        "/v1/artifacts/compatibility_table",
    }
)
_BULK_EVALUATE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "clients.bulk_evaluate",
        "bulk_evaluate",
        "bulk_evaluate_clients",
        "bulk_evaluate_clients_v1_me_clients_bulk_evaluate_post",
        "v1.me.clients.bulk_evaluate",
        "/v1/me/clients/bulk_evaluate",
    }
)

_AUDIT_BATCH_K = 10
_WORKPAPER_EXPORT_UNITS = 10
_SNAPSHOT_ATTESTATION_UNITS = 10_000

# Bundle-class quantity multipliers for `POST /v1/am/dd_export` (mirrors
# `api/ma_dd.py::_BUNDLE_CLASS_UNITS`). The export endpoint accepts a
# `bundle_class` parameter that maps to a fixed unit multiplier — customer
# is charged `(N houjin + bundle_units) × ¥3`. NOT a tier SKU; this is an
# artifact-size selector analogous to `row_count` in `bulk_evaluate`.
#
#     standard → 333 units (¥999 ≈ ¥1,000)
#     deal     → 1,000 units (¥3,000)
#     case     → 3,333 units (¥9,999 ≈ ¥10,000)
#
# Surfaced here so the cost-preview endpoint and downstream callers can
# resolve the weight without importing `ma_dd`.
_BUNDLE_CLASS_UNITS: dict[str, int] = {
    "standard": 333,
    "deal": 1_000,
    "case": 3_333,
}

# Tax-relevant tools that must surface the §52 fence in the preview response
# even though the preview itself is non-metered. An LLM agent that previews
# a tax-judgment call sequence must still know the surfaced advice carries
# the fence.
_TAX_RELEVANT_TOOLS: frozenset[str] = frozenset(
    {
        "search_tax_rulesets",
        "get_tax_ruleset",
        "evaluate_tax_ruleset",
        "/v1/tax_rulesets/evaluate",
        "search_tax_incentives",
        "/v1/am/tax_incentives",
        "list_tax_sunset_alerts",
        "/v1/am/tax_sunset_alerts",
    }
)

_TAX_DISCLAIMER = (
    "本情報は税務助言ではありません。jpcite は公的機関が公表する税制・補助金・"
    "法令情報を検索・整理して提供するサービスで、税理士法 §52 に基づき個別具体的な"
    "税務判断・申告書作成代行は行いません。個別案件は資格を有する税理士に必ずご相談"
    "ください。本サービスの情報利用により生じた損害について、当社は一切の責任を負いません。"
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CostPreviewCall(BaseModel):
    """A single planned tool invocation inside a stack.

    The preview does not execute the target tool or read from the DB. For
    known fan-out tools it reads only the list arguments needed to mirror the
    billed `quantity`.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "Tool name as it appears in MCP / REST. Example: search_programs, "
            "batch_get_programs, am.dd_export, evaluate_tax_ruleset. Known "
            "fan-out tools require their list args so preview can match the "
            "actual billed quantity."
        ),
    )
    args: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Tool arguments. For fan-out tools, the preview reads only the "
            "ID list and bundle_class needed to calculate billed quantity."
        ),
    )


class CostPreviewRequest(BaseModel):
    """`POST /v1/cost/preview` request body.

    Either `stack_or_calls` is the planned sequence of tool calls (one row
    per call). `iterations` multiplies the entire stack — handy for agent
    loops that fan out the same stack across N inputs.
    """

    model_config = ConfigDict(extra="forbid")

    stack_or_calls: list[CostPreviewCall] = Field(
        min_length=1,
        max_length=500,
        description=(
            "Planned tool-call stack. Each entry counts toward "
            "billing_units. The 500-entry cap protects service availability "
            "for large preview payloads."
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


def _ip_identity_for(request: Request) -> str:
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


def _identity_for(request: Request, conn: sqlite3.Connection | None = None) -> str:
    """Return a stable identity string for rate-limit bucketing.

    Prefer a validated active API-key hash over the IP bucket. Invalid or
    revoked key-shaped strings intentionally fall back to IP, otherwise an
    anonymous caller could rotate bogus keys and bypass the free preview
    throttle.
    """
    raw = (request.headers.get("x-api-key") or "").strip()
    auth = request.headers.get("authorization", "")
    parts = auth.split(None, 1)
    if not raw and len(parts) == 2 and parts[0].lower() == "bearer":
        raw = parts[1].strip()
    if raw and conn is not None:
        key_hash = hash_api_key(raw)
        with contextlib.suppress(sqlite3.Error):
            row = conn.execute(
                "SELECT 1 FROM api_keys WHERE key_hash = ? "
                "AND (revoked_at IS NULL OR revoked_at = '') "
                "LIMIT 1",
                (key_hash,),
            ).fetchone()
            if row is not None:
                return "k:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return _ip_identity_for(request)


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


class CostPreviewArgsError(ValueError):
    """Raised when a known fan-out tool cannot be previewed safely."""

    def __init__(self, tool: str, message: str) -> None:
        self.tool = tool
        super().__init__(message)


def _canonical_tool_name(tool: str) -> str:
    name = tool.strip()
    parts = name.split(maxsplit=1)
    if len(parts) == 2 and parts[0].upper() in {
        "DELETE",
        "GET",
        "PATCH",
        "POST",
        "PUT",
    }:
        name = parts[1].strip()
    parsed = urlsplit(name)
    if parsed.scheme and parsed.netloc:
        return parsed.path or "/"
    if name.startswith("/") or parsed.query or parsed.fragment:
        return parsed.path or name.split("?", 1)[0].split("#", 1)[0]
    return name


def _dedupe_count(values: Any, *, arg_name: str, tool: str) -> int:
    if not isinstance(values, list):
        raise CostPreviewArgsError(tool, f"{arg_name} list is required")
    seen: set[str] = set()
    for value in values:
        key = str(value).strip()
        if key:
            seen.add(key)
    if not seen:
        raise CostPreviewArgsError(tool, f"{arg_name} must contain at least one value")
    return len(seen)


def _normalize_houjin_for_preview(raw: Any) -> str | None:
    if raw is None:
        return None
    s = unicodedata.normalize("NFKC", str(raw)).strip().lstrip("Tt")
    for ch in "- ,　":
        s = s.replace(ch, "")
    if not s.isdigit() or len(s) != 13:
        return None
    return s


def _dedupe_houjin_count(values: Any, *, tool: str) -> int:
    if not isinstance(values, list):
        raise CostPreviewArgsError(tool, "houjin_bangous list is required")
    normalized: set[str] = set()
    invalid = 0
    for value in values:
        n = _normalize_houjin_for_preview(value)
        if n is None:
            invalid += 1
            continue
        normalized.add(n)
    if invalid:
        raise CostPreviewArgsError(tool, "houjin_bangous contains invalid corporate numbers")
    if not normalized:
        raise CostPreviewArgsError(tool, "houjin_bangous must contain at least one value")
    return len(normalized)


def _list_count(values: Any, *, arg_name: str, tool: str) -> int:
    if not isinstance(values, list):
        raise CostPreviewArgsError(tool, f"{arg_name} list is required")
    if not values:
        raise CostPreviewArgsError(tool, f"{arg_name} must contain at least one value")
    return len(values)


def _row_count_arg(args: dict[str, Any], *, tool: str) -> int:
    raw = args.get("row_count")
    if raw is None:
        rows = args.get("rows")
        if isinstance(rows, list):
            return _list_count(rows, arg_name="rows", tool=tool)
        raise CostPreviewArgsError(tool, "row_count is required")
    try:
        row_count = int(raw)
    except (TypeError, ValueError) as exc:
        raise CostPreviewArgsError(tool, "row_count must be an integer") from exc
    if row_count < 1:
        raise CostPreviewArgsError(tool, "row_count must be at least 1")
    return row_count


def _billing_units_for_call(call: CostPreviewCall) -> float:
    tool = _canonical_tool_name(call.tool)
    args = call.args or {}
    if tool in _BATCH_PROGRAM_TOOL_NAMES:
        return float(_dedupe_count(args.get("unified_ids"), arg_name="unified_ids", tool=tool))
    if tool in _DD_BATCH_TOOL_NAMES:
        return float(_dedupe_houjin_count(args.get("houjin_bangous"), tool=tool))
    if tool in _DD_EXPORT_TOOL_NAMES:
        n_houjin = _dedupe_houjin_count(args.get("houjin_bangous"), tool=tool)
        bundle_class = str(args.get("bundle_class") or "standard")
        if bundle_class not in _BUNDLE_CLASS_UNITS:
            raise CostPreviewArgsError(tool, "bundle_class must be standard, deal, or case")
        return float(n_houjin + _BUNDLE_CLASS_UNITS[bundle_class])
    if tool in _GROUP_GRAPH_TOOL_NAMES:
        return 1.0
    if tool in _AUDIT_WORKPAPER_TOOL_NAMES:
        n_rulesets = _dedupe_count(
            args.get("target_ruleset_ids"),
            arg_name="target_ruleset_ids",
            tool=tool,
        )
        return float(n_rulesets + _WORKPAPER_EXPORT_UNITS)
    if tool in _AUDIT_BATCH_TOOL_NAMES:
        n_profiles = _list_count(args.get("profiles"), arg_name="profiles", tool=tool)
        n_rulesets = _dedupe_count(
            args.get("target_ruleset_ids"),
            arg_name="target_ruleset_ids",
            tool=tool,
        )
        return float(max(1, (n_profiles * n_rulesets + _AUDIT_BATCH_K - 1) // _AUDIT_BATCH_K))
    if tool in _AUDIT_SNAPSHOT_TOOL_NAMES:
        return float(_SNAPSHOT_ATTESTATION_UNITS)
    if tool in _FUNDING_STACK_TOOL_NAMES or tool in _COMPATIBILITY_TABLE_TOOL_NAMES:
        n_programs = _dedupe_count(
            args.get("program_ids"),
            arg_name="program_ids",
            tool=tool,
        )
        if n_programs < 2:
            raise CostPreviewArgsError(
                tool,
                "program_ids must contain at least two unique values",
            )
        return float(n_programs * (n_programs - 1) // 2)
    if tool in _BULK_EVALUATE_TOOL_NAMES:
        commit = args.get("commit")
        if isinstance(commit, str):
            commit = commit.strip().lower() not in {"0", "false", "no", "off"}
        if commit is False:
            return 0.0
        return float(_row_count_arg(args, tool=tool))
    if tool not in _TOOL_WEIGHTS and any(
        marker in tool for marker in ("batch", "bulk", "export", "workpaper", "attestation")
    ):
        raise CostPreviewArgsError(
            tool,
            "unknown high-fanout tool; pass a supported tool name so the preview can fail closed",
        )
    return _TOOL_WEIGHTS.get(tool, _DEFAULT_TOOL_WEIGHT)


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
        weight = _billing_units_for_call(c)
        units_per_iter += weight
        if _canonical_tool_name(c.tool) in _TAX_RELEVANT_TOOLS:
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
        "Returns a no-charge cost estimate for planned jpcite tool calls "
        "without executing them.\n\n"
        "**Pricing**: metered calls are ¥3/billable unit (税別; 税込 ¥3.30). The preview "
        "itself is not metered and is rate-limited 50/min per IP/key.\n\n"
        "**Tax-related previews**: when the stack touches tax-relevant tools "
        "(`evaluate_tax_ruleset`, `search_tax_incentives`, etc.) the response "
        "includes a disclaimer for downstream display."
    ),
)
def post_cost_preview(
    payload: CostPreviewRequest,
    conn: DbDep,
    request: Request,
) -> JSONResponse:
    identity = _identity_for(request, conn)
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
                        f"Cost preview rate limit exceeded ({_PREVIEW_RATE_MAX}/min per IP/key)."
                    ),
                    "retry_after": retry_after_s,
                    "bucket": "cost_preview",
                }
            },
            headers={"Retry-After": str(retry_after_s)},
        )

    try:
        predicted_total_yen, billing_units, breakdown, has_tax_tool = compute_predicted_cost(
            payload.stack_or_calls, payload.iterations
        )
    except CostPreviewArgsError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "cost_preview_requires_args",
                    "tool": exc.tool,
                    "message": str(exc),
                }
            },
        ) from exc
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
    "CostPreviewArgsError",
    "CostPreviewRequest",
    "CostPreviewResponse",
    "compute_predicted_cost",
    "router",
    "_reset_preview_rate_state",
    "_TOOL_WEIGHTS",
    "_UNIT_PRICE_YEN",
    "_BUNDLE_CLASS_UNITS",
]
