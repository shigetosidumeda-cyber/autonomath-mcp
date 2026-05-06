"""Wave 24 REST wrappers for the 24 new MCP tools (#97-#120).

Each endpoint is a thin wrapper around the matching MCP tool function defined
in `mcp.autonomath_tools.wave24_tools_first_half` (W1-15) and
`mcp.autonomath_tools.wave24_tools_second_half` (W1-16). Surface contract:

  * Path = `MASTER_PLAN_v1.md §10.7.0 TOOL_TO_REST_PATH` (do not edit here).
  * Each call goes through `_dispatch_wave24_tool(<tool_name>, **kwargs)`,
    which lazily resolves the tool callable from the wave24 packages so that
    this module imports cleanly even when W1-15/W1-16 have not yet shipped
    their tool modules. A missing tool returns a 503 with an explicit
    `error: "tool_not_yet_implemented"` envelope rather than a 500.
  * `_dispatch_wave24_tool` filters its kwargs against the resolved tool's
    signature (`_filter_kwargs_for_tool`). Any key not in the signature, or
    any key starting with `_`, is dropped and logged as
    `wave24_kwargs_rejected`. **Convention** for every wave24 tool body:
    underscore-prefixed parameters (e.g. `_internal_audit`, `_skip_disclaimer`)
    are internal-only and are NEVER exposed via REST — even if the tool's
    Python signature lists them, callers cannot set them through the HTTP
    surface (W2-9 M-1 hardening).
  * NO LLM call inside any wrapper — `feedback_no_operator_llm_api` plus
    `feedback_autonomath_no_api_use`. The MCP tool body is pure SQLite; we
    just adapt the FastAPI request shape to its kwargs.
  * Mounted in `api/main.py` under `app.include_router(wave24_router,
    dependencies=[AnonIpLimitDep])` so the anonymous 3 req/日 quota applies.

Sensitive-tool disclaimers are emitted by the tool body itself (envelope
wrapper in `mcp/autonomath_tools/envelope_wrapper.py`); this layer does not
re-derive them — it returns the body verbatim.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Path, Query

logger = logging.getLogger("jpintel.api.wave24")

router = APIRouter(prefix="/v1/am", tags=["wave24"])

# --------------------------------------------------------------------------- #
# Tool resolver — lazy import so this module loads even when wave24 tool
# packages are not yet present (cross-agent landing window).
# --------------------------------------------------------------------------- #
_WAVE24_TOOL_MODULES: tuple[str, ...] = (
    "jpintel_mcp.mcp.autonomath_tools.wave24_tools_first_half",
    "jpintel_mcp.mcp.autonomath_tools.wave24_tools_second_half",
)

# Cache of tool_name -> callable. Populated on first lookup; cleared by
# `_reset_wave24_tool_cache()` in tests when a fixture monkeypatches the
# tool modules.
_TOOL_CACHE: dict[str, Any] = {}


def _reset_wave24_tool_cache() -> None:
    """Test hook — clear the resolver cache."""
    _TOOL_CACHE.clear()


def _resolve_wave24_tool(tool_name: str) -> Any | None:
    """Return the callable for a wave24 tool, or None if unavailable.

    Looks up `tool_name` (sans `_impl` suffix) in either wave24 module.
    The wave24 tool modules export tool functions either as `<name>` or
    `<name>_impl` (the _impl pattern matches industry_packs.py); we try
    both. Module-not-found is treated as "tool not yet implemented".
    """
    if tool_name in _TOOL_CACHE:
        return _TOOL_CACHE[tool_name]
    for module_path in _WAVE24_TOOL_MODULES:
        try:
            mod = importlib.import_module(module_path)
        except ImportError:
            continue
        for attr in (tool_name, f"{tool_name}_impl", f"_{tool_name}_impl"):
            fn = getattr(mod, attr, None)
            if callable(fn):
                _TOOL_CACHE[tool_name] = fn
                return fn
        # Some wave24 modules may expose tools through a registry list.
        for registry_name in (
            "WAVE24_TOOLS_FIRST_HALF",
            "WAVE24_TOOLS_SECOND_HALF",
            "WAVE24_TOOLS",
        ):
            registry = getattr(mod, registry_name, None)
            if not registry:
                continue
            for fn in registry:
                if getattr(fn, "__name__", "") == tool_name:
                    _TOOL_CACHE[tool_name] = fn
                    return fn
    return None


def _filter_kwargs_for_tool(tool_name: str, fn: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return only the kwargs that the wave24 tool's signature accepts.

    Security gate (W2-9 M-1): the REST surface accepts arbitrary POST body
    JSON via `**payload` spread on four endpoints (recommend, enforcement_risk,
    match/capital, tax_change_impact). Without filtering, a caller could
    inject internal-only kwargs (e.g. `_internal_audit=True`, `_skip_disclaimer=True`)
    that the tool body did not intend to expose via REST.

    Convention: any parameter whose name starts with `_` is **internal**
    and must NOT be settable via REST. Tools that need REST-callable params
    must keep them underscore-free. See docstring on each `_<tool>_impl` body.

    Behaviour:
    * Drops any key not in the tool's signature (unless the tool declares
      `**kwargs` — but for wave24 we explicitly do NOT, by convention).
    * Drops any key starting with `_` regardless.
    * Logs a structured warning naming the rejected keys so a probing
      caller is observable in production logs.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        # Defensive: can't introspect — pass through (back to legacy behaviour
        # for the rare case of C-implemented or wrapped callables).
        return kwargs
    allowed: set[str] = set()
    accepts_var_kw = False
    for name, param in sig.parameters.items():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            accepts_var_kw = True
            continue
        if name.startswith("_"):
            # Underscore-prefixed parameters are internal-only by convention
            # and never exposed via REST. Even if the tool declares them, we
            # refuse to honour caller-supplied values.
            continue
        allowed.add(name)
    if accepts_var_kw:
        # Tool opts in to arbitrary kwargs — still strip underscore-prefixed
        # keys (caller cannot inject internal-only flags).
        filtered = {k: v for k, v in kwargs.items() if not k.startswith("_")}
        rejected = sorted(k for k in kwargs if k.startswith("_"))
    else:
        filtered = {k: v for k, v in kwargs.items() if k in allowed}
        rejected = sorted(set(kwargs) - set(filtered))
    if rejected:
        logger.warning(
            "wave24_kwargs_rejected",
            extra={"tool": tool_name, "keys": rejected},
        )
    return filtered


def _dispatch_wave24_tool(tool_name: str, **kwargs: Any) -> dict[str, Any]:
    """Resolve and call a wave24 tool. Raise 503 if not yet wired."""
    fn = _resolve_wave24_tool(tool_name)
    if fn is None:
        # Honest 503 — the W1-15/W1-16 modules have not yet landed. Caller
        # sees a structured envelope, not a generic 500.
        raise HTTPException(
            status_code=503,
            detail={
                "error": "tool_not_yet_implemented",
                "tool": tool_name,
                "message": (
                    "Wave 24 tool registration pending. Check "
                    "JPINTEL_AUTONOMATH_WAVE24_ENABLED and the W1-15 / W1-16 "
                    "tool module landings."
                ),
            },
        )
    # Drop None values FIRST (legacy behaviour — Query(None) defaults must
    # not be forwarded), THEN filter against the tool signature so caller-
    # supplied internal-only kwargs are stripped before the call.
    explicit = {k: v for k, v in kwargs.items() if v is not None}
    safe = _filter_kwargs_for_tool(tool_name, fn, explicit)
    try:
        result = fn(**safe)
    except TypeError as exc:
        # Argument-shape mismatch between this REST wrapper and the wave24
        # tool signature. Surface as 422 so the integrator can fix the call,
        # not 500 (which would alarm Sentry and pollute the SLA budget).
        logger.warning("wave24 dispatch arg mismatch tool=%s err=%s", tool_name, exc)
        raise HTTPException(
            status_code=422,
            detail={
                "error": "tool_arg_mismatch",
                "tool": tool_name,
                "message": str(exc),
            },
        ) from exc
    if not isinstance(result, dict):
        # Defensive — every wave24 tool returns a dict envelope.
        return {"results": result}
    return result


# --------------------------------------------------------------------------- #
# 24 endpoint definitions — TOOL_TO_REST_PATH per MASTER_PLAN_v1 §10.7.0
# --------------------------------------------------------------------------- #


# #97 — recommend_programs_for_houjin
@router.post("/recommend")
def rest_recommend_programs_for_houjin(
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return _dispatch_wave24_tool("recommend_programs_for_houjin", **payload)


# #98 — find_combinable_programs
@router.get("/combinations/{program_id}")
def rest_find_combinable_programs(
    program_id: str = Path(..., min_length=1),
    visibility: str = Query("public", pattern="^(public|internal|all)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "find_combinable_programs",
        program_id=program_id,
        visibility=visibility,
        limit=limit,
        offset=offset,
    )


# #99 — get_program_calendar_12mo
@router.get("/calendar_12mo/{program_id}")
def rest_get_program_calendar_12mo(
    program_id: str = Path(..., min_length=1),
    limit: int = Query(12, ge=1, le=24),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "get_program_calendar_12mo",
        program_id=program_id,
        limit=limit,
        offset=offset,
    )


# #100 — forecast_enforcement_risk
@router.post("/enforcement_risk")
def rest_forecast_enforcement_risk(
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return _dispatch_wave24_tool("forecast_enforcement_risk", **payload)


# #101 — find_similar_case_studies
@router.get("/case_studies/similar/{case_id}")
def rest_find_similar_case_studies(
    case_id: str = Path(..., min_length=1),
    limit: int = Query(5, ge=1, le=20),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "find_similar_case_studies",
        case_id=case_id,
        limit=limit,
        offset=offset,
    )


# #102 — get_houjin_360_snapshot_history
@router.get("/houjin/{houjin_bangou}/360_history")
def rest_get_houjin_360_snapshot_history(
    houjin_bangou: str = Path(..., min_length=13, max_length=13),
    months: int = Query(12, ge=1, le=60),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "get_houjin_360_snapshot_history",
        houjin_bangou=houjin_bangou,
        months=months,
    )


# #103 — get_tax_amendment_cycle
@router.get("/tax/{tax_ruleset_id}/amendment_cycle")
def rest_get_tax_amendment_cycle(
    tax_ruleset_id: str = Path(..., min_length=1),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "get_tax_amendment_cycle",
        tax_ruleset_id=tax_ruleset_id,
        limit=limit,
        offset=offset,
    )


# #104 — infer_invoice_buyer_seller
@router.get("/houjin/{houjin_bangou}/invoice_graph")
def rest_infer_invoice_buyer_seller(
    houjin_bangou: str = Path(..., min_length=13, max_length=13),
    direction: str = Query("both", pattern="^(seller|buyer|both)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "infer_invoice_buyer_seller",
        houjin_bangou=houjin_bangou,
        direction=direction,
        limit=limit,
        offset=offset,
    )


# #105 — match_programs_by_capital
@router.post("/match/capital")
def rest_match_programs_by_capital(
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return _dispatch_wave24_tool("match_programs_by_capital", **payload)


# #106 — get_program_adoption_stats
@router.get("/programs/{program_id}/adoption_stats")
def rest_get_program_adoption_stats(
    program_id: str = Path(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "get_program_adoption_stats",
        program_id=program_id,
        limit=limit,
        offset=offset,
    )


# #107 — get_program_narrative
@router.get("/programs/{program_id}/narrative")
def rest_get_program_narrative(
    program_id: str = Path(..., min_length=1),
    lang: str = Query("ja", pattern="^(ja|en)$"),
    section: str = Query("all"),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "get_program_narrative",
        program_id=program_id,
        lang=lang,
        section=section,
    )


# #108 — predict_rd_tax_credit
@router.get("/houjin/{houjin_bangou}/rd_tax_credit")
def rest_predict_rd_tax_credit(
    houjin_bangou: str = Path(..., min_length=13, max_length=13),
    fy: int | None = Query(None, ge=2000, le=2100),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "predict_rd_tax_credit",
        houjin_bangou=houjin_bangou,
        fiscal_year=fy,
    )


# #109 — find_programs_by_jsic
@router.get("/programs/by_jsic/{jsic_code}")
def rest_find_programs_by_jsic(
    jsic_code: str = Path(...),
    tier: str | None = Query(None, pattern="^(S|A|B|C)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    jsic_kwargs: dict[str, Any] = {"jsic_major": jsic_code}
    if len(jsic_code) == 2:
        jsic_kwargs = {"jsic_middle": jsic_code}
    elif len(jsic_code) >= 3:
        jsic_kwargs = {"jsic_minor": jsic_code}
    return _dispatch_wave24_tool(
        "find_programs_by_jsic",
        **jsic_kwargs,
        tier=tier,
        limit=limit,
        offset=offset,
    )


# #110 — get_program_application_documents
@router.get("/programs/{program_id}/documents")
def rest_get_program_application_documents(
    program_id: str = Path(..., min_length=1),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "get_program_application_documents",
        program_id=program_id,
        limit=limit,
        offset=offset,
    )


# #111 — find_adopted_companies_by_program
@router.get("/programs/{program_id}/adopted_companies")
def rest_find_adopted_companies_by_program(
    program_id: str = Path(..., min_length=1),
    program_name_partial: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "find_adopted_companies_by_program",
        program_id=program_id,
        program_name_partial=program_name_partial,
        limit=limit,
        offset=offset,
    )


# #112 — score_application_probability
@router.get("/programs/{program_id}/houjin/{houjin_bangou}/similarity_score")
def rest_score_application_probability(
    program_id: str = Path(..., min_length=1),
    houjin_bangou: str = Path(..., min_length=13, max_length=13),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "score_application_probability",
        program_id=program_id,
        houjin_bangou=houjin_bangou,
    )


# #113 — get_compliance_risk_score
@router.get("/houjin/{houjin_bangou}/compliance_risk")
def rest_get_compliance_risk_score(
    houjin_bangou: str = Path(..., min_length=13, max_length=13),
) -> dict[str, Any]:
    return _dispatch_wave24_tool("get_compliance_risk_score", houjin_bangou=houjin_bangou)


# #114 — simulate_tax_change_impact
@router.post("/houjin/{houjin_bangou}/tax_change_impact")
def rest_simulate_tax_change_impact(
    houjin_bangou: str = Path(..., min_length=13, max_length=13),
    payload: dict[str, Any] = Body(default_factory=dict),
    fiscal_year: int | None = Query(None, ge=2000, le=2100),
) -> dict[str, Any]:
    if fiscal_year is not None:
        payload = {**payload, "fiscal_year": fiscal_year}
    return _dispatch_wave24_tool(
        "simulate_tax_change_impact",
        houjin_bangou=houjin_bangou,
        **payload,
    )


# #115 — find_complementary_subsidies
@router.get("/programs/{program_id}/complementary")
def rest_find_complementary_subsidies(
    program_id: str = Path(..., min_length=1),
    months_window: int = Query(12, ge=1, le=24),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "find_complementary_subsidies",
        program_id=program_id,
        months_window=months_window,
        limit=limit,
        offset=offset,
    )


# #116 — get_program_keyword_analysis
@router.get("/programs/{program_id}/keywords")
def rest_get_program_keyword_analysis(
    program_id: str = Path(..., min_length=1),
    top_k: int = Query(30, ge=1, le=100),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "get_program_keyword_analysis",
        program_id=program_id,
        top_k=top_k,
    )


# #117 — get_industry_program_density
@router.get("/density/{jsic_major}")
def rest_get_industry_program_density(
    jsic_major: str = Path(..., min_length=1, max_length=2),
    region_code: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "get_industry_program_density",
        jsic_major=jsic_major,
        region_code=region_code,
        limit=limit,
        offset=offset,
    )


# #118 — find_emerging_programs
@router.get("/programs/emerging")
def rest_find_emerging_programs(
    days: int = Query(90, ge=1, le=730),
    tier: str | None = Query(None, pattern="^(S|A|B|C)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "find_emerging_programs",
        days=days,
        tier=tier,
        limit=limit,
        offset=offset,
    )


# #119 — get_program_renewal_probability
@router.get("/programs/{program_id}/renewal_change_forecast")
def rest_get_program_renewal_probability(
    program_id: str = Path(..., min_length=1),
    horizon_months: int = Query(12, ge=1, le=60),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "get_program_renewal_probability",
        program_id=program_id,
        horizon_months=horizon_months,
    )


# #120 — get_houjin_subsidy_history
@router.get("/houjin/{houjin_bangou}/subsidy_history")
def rest_get_houjin_subsidy_history(
    houjin_bangou: str = Path(..., min_length=13, max_length=13),
    since_year: int | None = Query(None, ge=1900, le=2100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return _dispatch_wave24_tool(
        "get_houjin_subsidy_history",
        houjin_bangou=houjin_bangou,
        since_year=since_year,
        limit=limit,
        offset=offset,
    )


__all__ = [
    "router",
    "_dispatch_wave24_tool",
    "_filter_kwargs_for_tool",
    "_resolve_wave24_tool",
    "_reset_wave24_tool_cache",
]
