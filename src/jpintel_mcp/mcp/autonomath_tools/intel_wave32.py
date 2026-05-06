"""intel_wave32 — Wave 32 REST intelligence MCP wrappers.

This module intentionally depends on the REST endpoint modules lazily. The
REST files are produced by a separate worker, so importing this MCP module
must succeed even while those modules do not exist yet.

Env gates:
  * AUTONOMATH_INTEL_COMPOSITE_ENABLED (shared composite-intel rollback)
  * AUTONOMATH_INTEL_WAVE32_ENABLED (Wave 32 specific rollback)
  * settings.autonomath_enabled (global AutonoMath gate)
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
from collections.abc import Callable
from typing import Annotated, Any

from pydantic import BaseModel, Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.autonomath_tools.error_envelope import make_error
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

_ENABLED = (
    os.environ.get("AUTONOMATH_INTEL_COMPOSITE_ENABLED", "1") == "1"
    and os.environ.get("AUTONOMATH_INTEL_WAVE32_ENABLED", "1") == "1"
)

_TOOL_SUFFIXES = {
    "intel_scenario_simulate": "scenario_simulate",
    "intel_competitor_landscape": "competitor_landscape",
    "intel_portfolio_heatmap": "portfolio_heatmap",
    "intel_news_brief": "news_brief",
    "intel_onboarding_brief": "onboarding_brief",
    "intel_refund_risk": "refund_risk",
    "intel_cross_jurisdiction": "cross_jurisdiction",
}


def _module_candidates(suffix: str) -> tuple[str, ...]:
    return (
        f"jpintel_mcp.api.intel_{suffix}",
        "jpintel_mcp.api.intel_wave32",
        "jpintel_mcp.api.intel",
    )


def _import_first_available(suffix: str) -> Any | None:
    for module_name in _module_candidates(suffix):
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                continue
            raise
    return None


def _callable_candidates(suffix: str) -> tuple[str, ...]:
    return (
        f"_build_{suffix}",
        f"build_{suffix}",
        f"_{suffix}_impl",
        f"{suffix}_impl",
        f"_intel_{suffix}_impl",
        f"intel_{suffix}_impl",
        suffix,
        f"intel_{suffix}",
        f"post_{suffix}",
        f"create_{suffix}",
    )


def _model_candidates(suffix: str) -> tuple[str, ...]:
    camel = "".join(part.capitalize() for part in suffix.split("_"))
    return (
        f"Intel{camel}Request",
        f"{camel}Request",
        f"Intel{camel}Input",
        f"{camel}Input",
    )


def _find_callable(module: Any, suffix: str) -> Callable[..., Any] | None:
    for name in _callable_candidates(suffix):
        fn = getattr(module, name, None)
        if callable(fn):
            return fn
    return None


def _find_model(module: Any, suffix: str) -> type[BaseModel] | None:
    for name in _model_candidates(suffix):
        model = getattr(module, name, None)
        if inspect.isclass(model) and issubclass(model, BaseModel):
            return model
    return None


def _run_awaitable(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    return make_error(
        code="internal",
        message=(
            "Wave 32 REST endpoint returned an awaitable while an event loop "
            "is already running; expose a pure helper for MCP in-process use."
        ),
    )


def _call_with_payload(fn: Callable[..., Any], payload: dict[str, Any]) -> Any:
    signature = inspect.signature(fn)
    params = list(signature.parameters.values())
    required = [
        p
        for p in params
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    has_var_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params)

    if has_var_kwargs or all(key in signature.parameters for key in payload):
        return _run_awaitable(fn(**payload))
    if len(required) <= 1:
        return _run_awaitable(fn(payload))
    return make_error(
        code="internal",
        message=(
            f"Cannot map MCP payload to REST helper {fn.__module__}.{fn.__name__}; "
            "provide a pure helper accepting **payload or one request object."
        ),
    )


def _is_helper(fn: Callable[..., Any]) -> bool:
    name = getattr(fn, "__name__", "")
    return name.startswith(("build_", "_build_", "_intel_")) or name.endswith("_impl")


def _delegate(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    suffix = _TOOL_SUFFIXES[tool_name]
    module = _import_first_available(suffix)
    if module is None:
        return make_error(
            code="subsystem_unavailable",
            message=(
                f"REST module for {tool_name} is not available yet. "
                f"Tried: {', '.join(_module_candidates(suffix))}."
            ),
            retry_with=["search_programs", "get_program"],
        )

    fn = _find_callable(module, suffix)
    if fn is None:
        return make_error(
            code="subsystem_unavailable",
            message=(
                f"No callable REST helper/endpoint found for {tool_name} in {module.__name__}."
            ),
        )

    model = None if _is_helper(fn) else _find_model(module, suffix)
    if model is not None:
        try:
            request = model(**payload)
        except Exception as exc:
            return make_error(
                code="invalid_input",
                message=f"{model.__name__} validation failed: {exc}",
            )
        result = _run_awaitable(fn(request))
    else:
        result = _call_with_payload(fn, payload)

    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    if isinstance(result, dict):
        return result
    return {"result": result}


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def intel_scenario_simulate(
        payload: Annotated[
            dict[str, Any],
            Field(description="Request body for POST /v1/intel/scenario_simulate."),
        ],
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W32] Scenario simulation wrapper. Delegates lazily to the REST pure helper or endpoint module when present. Pure in-process call; no HTTP roundtrip."""
        return _delegate("intel_scenario_simulate", payload)

    @mcp.tool(annotations=_READ_ONLY)
    def intel_competitor_landscape(
        payload: Annotated[
            dict[str, Any],
            Field(description="Request body for POST /v1/intel/competitor_landscape."),
        ],
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W32] Competitor landscape wrapper. Delegates lazily to the REST pure helper or endpoint module when present. Pure in-process call; no HTTP roundtrip."""
        return _delegate("intel_competitor_landscape", payload)

    @mcp.tool(annotations=_READ_ONLY)
    def intel_portfolio_heatmap(
        payload: Annotated[
            dict[str, Any],
            Field(description="Request body for POST /v1/intel/portfolio_heatmap."),
        ],
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W32] Portfolio heatmap wrapper. Delegates lazily to the REST pure helper or endpoint module when present. Pure in-process call; no HTTP roundtrip."""
        return _delegate("intel_portfolio_heatmap", payload)

    @mcp.tool(annotations=_READ_ONLY)
    def intel_news_brief(
        payload: Annotated[
            dict[str, Any],
            Field(description="Request body for POST /v1/intel/news_brief."),
        ],
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W32] News brief wrapper. Delegates lazily to the REST pure helper or endpoint module when present. Pure in-process call; no HTTP roundtrip."""
        return _delegate("intel_news_brief", payload)

    @mcp.tool(annotations=_READ_ONLY)
    def intel_onboarding_brief(
        payload: Annotated[
            dict[str, Any],
            Field(description="Request body for POST /v1/intel/onboarding_brief."),
        ],
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W32] Onboarding brief wrapper. Delegates lazily to the REST pure helper or endpoint module when present. Pure in-process call; no HTTP roundtrip."""
        return _delegate("intel_onboarding_brief", payload)

    @mcp.tool(annotations=_READ_ONLY)
    def intel_refund_risk(
        payload: Annotated[
            dict[str, Any],
            Field(description="Request body for POST /v1/intel/refund_risk."),
        ],
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W32] Refund risk wrapper. Delegates lazily to the REST pure helper or endpoint module when present. Pure in-process call; no HTTP roundtrip."""
        return _delegate("intel_refund_risk", payload)

    @mcp.tool(annotations=_READ_ONLY)
    def intel_cross_jurisdiction(
        payload: Annotated[
            dict[str, Any],
            Field(description="Request body for POST /v1/intel/cross_jurisdiction."),
        ],
    ) -> dict[str, Any]:
        """[INTEL-COMPOSITE W32] Cross-jurisdiction wrapper. Delegates lazily to the REST pure helper or endpoint module when present. Pure in-process call; no HTTP roundtrip."""
        return _delegate("intel_cross_jurisdiction", payload)
