"""Moat HE-1 - Heavy-Output Endpoint: ``agent_full_context``.

User directive (2026-05-17):
    "薄い回答を返しても誰も使わない" / "agent が LLM コスト安く済むように
    深い回答" -> depth-first moat 設計の核.

GOAL
----
Single MCP tool that returns everything an agent needs in 1 call
(vs. 5-10 round trips with atomic N1..N9 / M10 / search_programs etc.).

The endpoint composes existing tools server-side using ``asyncio.gather()``
so the round-trip tax is paid once, not N times. NO LLM inference is
performed anywhere on the path - every payload is built from existing
SQLite-backed lookups + the upstream moat lane wrappers.

Signature
---------
``agent_full_context(query, segment=None, houjin_bangou=None,
depth_level=3) -> dict[str, Any]``

depth_level shapes
~~~~~~~~~~~~~~~~~~
* ``1`` LITE   (~5 KB)  - top-1 each, no reasoning chain.
* ``3`` NORMAL (~30 KB) - top-5 each, reasoning_chain trimmed to 3.
* ``5`` FULL   (~100 KB) - top-10 each, full reasoning_chain with
  opposing views, full portfolio matrix.

Hard constraints
----------------
* NO LLM inference. NO Anthropic / OpenAI / Gemini API call.
* Pure composition over existing tools (N1..N9 + M10 hybrid search +
  ``search_programs`` etc.). Each underlying call is in-process; no
  HTTP round-trip.
* ``parallel asyncio.gather()`` is used to fan out the underlying
  calls; the synchronous tool functions are wrapped via
  ``asyncio.to_thread`` so they release the event loop on SQLite I/O.
* Heavy endpoint ``_billing_unit = 4`` (¥12 / req, Pricing V3 Tier C, 2026-05-17). The agent saves N-1 calls
  worth of round trips and the operator saves N-1 LLM compose roundtrips.
* §52 / §47条の2 / §72 / §1 / §3 disclaimer envelope on every response.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ._shared import DISCLAIMER, today_iso_utc

logger = logging.getLogger("jpintel.mcp.moat_lane_tools.he1_full_context")

_TOOL_NAME = "agent_full_context"
_LANE_ID = "HE1"
_SCHEMA_VERSION = "moat.he1.v1"


# ---------------------------------------------------------------------------
# Segment mapping
# ---------------------------------------------------------------------------
# N1 (artifact templates) uses JA segments: 税理士 / 会計士 / 行政書士 /
#   司法書士 / 社労士 / all
# N8 (recipes) uses EN slugs: tax / audit / gyousei / shihoshoshi /
#   ax_fde / all
# The user-facing ``segment`` param accepts both Japanese strings and the
# extra business segments documented in the spec
# ("中小経営者" / "AX_engineer"). We map them deterministically so the
# downstream tools never see an invalid value.

_JA_SEGMENTS: frozenset[str] = frozenset({"税理士", "会計士", "行政書士", "司法書士", "社労士"})
_BUSINESS_SEGMENTS: frozenset[str] = frozenset(
    {"中小経営者", "AX_engineer", "ax_fde", "ax_engineer"}
)

_SEGMENT_TO_N1: dict[str, str] = {
    "税理士": "税理士",
    "会計士": "会計士",
    "行政書士": "行政書士",
    "司法書士": "司法書士",
    "社労士": "社労士",
}

_SEGMENT_TO_N8: dict[str, str] = {
    "税理士": "tax",
    "会計士": "audit",
    "行政書士": "gyousei",
    "司法書士": "shihoshoshi",
    "社労士": "tax",  # 社労士 has no dedicated bank yet -> closest: tax
    "中小経営者": "all",
    "AX_engineer": "ax_fde",
    "ax_engineer": "ax_fde",
    "ax_fde": "ax_fde",
}


def _normalize_segment(segment: str | None) -> tuple[str, str]:
    """Return (n1_segment, n8_segment) for the requested business segment.

    Both default to ``"all"`` when the caller does not pass a segment,
    or passes a value the moat lanes do not support.
    """
    if not segment:
        return ("all", "all")
    if segment in _JA_SEGMENTS:
        return (_SEGMENT_TO_N1.get(segment, "all"), _SEGMENT_TO_N8.get(segment, "all"))
    if segment in _BUSINESS_SEGMENTS:
        # Business segments are not 士業 — surface "all" on N1 (no
        # artifact bank) but route to the matching N8 recipe bucket.
        return ("all", _SEGMENT_TO_N8.get(segment, "all"))
    # Unknown segment -> graceful "all" fallback (do not raise).
    return ("all", "all")


# ---------------------------------------------------------------------------
# Depth profile
# ---------------------------------------------------------------------------


def _depth_profile(depth_level: int) -> dict[str, int]:
    """Return top-N caps + flag bundle for the requested depth level.

    ``depth_level`` is clamped to {1, 3, 5}; unknown values fall back
    to 3 (the published default).
    """
    if depth_level <= 1:
        return {
            "top_programs": 1,
            "top_laws": 1,
            "top_judgments": 1,
            "top_tsutatsu": 1,
            "top_cases": 1,
            "top_aliases": 3,
            "reasoning_limit": 0,  # skip reasoning chain entirely on LITE
            "windows_limit": 1,
            "templates_limit": 1,
            "alerts_limit": 1,
            "recipes_limit": 1,
            "placeholders_limit": 3,
            "include_reasoning_opposing": 0,
            "portfolio_top_n": 3,
        }
    if depth_level >= 5:
        return {
            "top_programs": 10,
            "top_laws": 10,
            "top_judgments": 10,
            "top_tsutatsu": 10,
            "top_cases": 10,
            "top_aliases": 20,
            "reasoning_limit": 10,
            "windows_limit": 5,
            "templates_limit": 20,
            "alerts_limit": 20,
            "recipes_limit": 15,
            "placeholders_limit": 20,
            "include_reasoning_opposing": 1,
            "portfolio_top_n": 50,
        }
    # depth_level == 3 (normal default).
    return {
        "top_programs": 5,
        "top_laws": 5,
        "top_judgments": 3,
        "top_tsutatsu": 3,
        "top_cases": 3,
        "top_aliases": 10,
        "reasoning_limit": 3,
        "windows_limit": 5,
        "templates_limit": 5,
        "alerts_limit": 5,
        "recipes_limit": 5,
        "placeholders_limit": 10,
        "include_reasoning_opposing": 0,
        "portfolio_top_n": 20,
    }


# ---------------------------------------------------------------------------
# Trimming helpers
# ---------------------------------------------------------------------------


def _trim_list(value: Any, cap: int) -> list[Any]:
    """Coerce ``value`` into ``list`` and truncate to ``cap`` items."""
    if not isinstance(value, list):
        return []
    if cap <= 0:
        return []
    return list(value[:cap])


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Composer pipeline
# ---------------------------------------------------------------------------


async def _call_resolve_alias(query: str, cap: int) -> list[dict[str, Any]]:
    """N5 - resolve aliases for ``query`` (1 sync call, off the event loop)."""
    try:
        from jpintel_mcp.mcp.moat_lane_tools.moat_n5_synonym import resolve_alias
    except (ImportError, AttributeError):
        return []
    try:
        payload = await asyncio.to_thread(resolve_alias, surface=query, kind="all")
    except Exception as exc:  # noqa: BLE001 - depth endpoint never raises
        logger.warning("he1.resolve_alias failed: %s", exc)
        return []
    return _trim_list(_safe_dict(payload).get("results"), cap)


async def _call_search_programs(query: str, cap: int) -> list[dict[str, Any]]:
    """search_programs - top-N program candidates by FTS.

    Imported lazily because ``mcp.server`` is the heavyweight import
    surface; we never want to drag it on module import time.
    """
    try:
        from jpintel_mcp.mcp.server import search_programs
    except (ImportError, AttributeError):
        return []
    try:
        payload = await asyncio.to_thread(
            search_programs,
            q=query,
            limit=cap,
            fields="default",
        )
    except Exception as exc:  # noqa: BLE001 - depth endpoint never raises
        logger.warning("he1.search_programs failed: %s", exc)
        return []
    body = _safe_dict(payload)
    results = body.get("results") or body.get("rows") or body.get("data") or []
    return _trim_list(results, cap)


async def _call_walk_reasoning(query: str, cap: int, include_opposing: bool) -> dict[str, Any]:
    """N3 - free-text walk over the reasoning chain corpus."""
    if cap <= 0:
        return {"results": [], "skipped": True}
    try:
        from jpintel_mcp.mcp.moat_lane_tools.moat_n3_reasoning import (
            walk_reasoning_chain,
        )
    except (ImportError, AttributeError):
        return {"results": [], "error": "module_missing"}
    try:
        payload = await asyncio.to_thread(
            walk_reasoning_chain,
            query=query,
            category="all",
            min_confidence=0.6,
            limit=cap,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("he1.walk_reasoning failed: %s", exc)
        return {"results": [], "error": str(exc)[:128]}
    body = _safe_dict(payload)
    rows = _trim_list(body.get("results"), cap)
    if not include_opposing:
        for row in rows:
            if isinstance(row, dict):
                row.pop("opposing_view_text", None)
                row.pop("opposing_view", None)
    return {
        "results": rows,
        "total": len(rows),
        "category": "all",
        "min_confidence": 0.6,
    }


async def _call_find_filing_window(
    houjin_bangou: str | None, query: str, cap: int
) -> list[dict[str, Any]]:
    """N4 - find filing windows for the given houjin + program kind.

    Skips when no houjin_bangou is provided because the lane is
    address-prefix matched.
    """
    if not houjin_bangou:
        return []
    try:
        from jpintel_mcp.mcp.moat_lane_tools.moat_n4_window import find_filing_window
    except (ImportError, AttributeError):
        return []
    # Map the free-text query to a jurisdiction kind alias for N4. Keep
    # this deterministic; downstream the lane already has its own alias
    # tables.
    program_kind = "tax_office"
    lowered = (query or "").lower()
    if any(k in lowered for k in ("補助金", "補助", "金融", "融資", "公庫")):
        program_kind = "jfc_branch"
    elif any(k in lowered for k in ("登記", "法務局", "法人設立")):
        program_kind = "legal_affairs_bureau"
    elif any(k in lowered for k in ("労務", "雇用", "労働", "社会保険")):
        program_kind = "labour_bureau"
    try:
        payload = await asyncio.to_thread(
            find_filing_window,
            program_id=program_kind,
            houjin_bangou=houjin_bangou,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("he1.find_filing_window failed: %s", exc)
        return []
    return _trim_list(_safe_dict(payload).get("results"), cap)


async def _call_list_artifact_templates(n1_segment: str, cap: int) -> list[dict[str, Any]]:
    """N1 - artifact templates filtered by segment."""
    try:
        from jpintel_mcp.mcp.moat_lane_tools.moat_n1_artifact import (
            list_artifact_templates,
        )
    except (ImportError, AttributeError):
        return []
    try:
        payload = await asyncio.to_thread(
            list_artifact_templates, segment=n1_segment, limit=min(cap, 100)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("he1.list_artifact_templates failed: %s", exc)
        return []
    body = _safe_dict(payload)
    rows = body.get("results") or _safe_dict(body.get("primary_result")).get("rows")
    return _trim_list(rows, cap)


async def _call_portfolio_gap(houjin_bangou: str | None, top_n: int) -> dict[str, Any]:
    """N2 - portfolio + gap programs for a houjin.

    Returns {} when no houjin_bangou is provided; the agent uses this
    field to decide whether to render the portfolio matrix.
    """
    if not houjin_bangou:
        return {}
    try:
        from jpintel_mcp.mcp.moat_lane_tools.moat_n2_portfolio import (
            find_gap_programs,
            get_houjin_portfolio,
        )
    except (ImportError, AttributeError):
        return {}
    try:
        portfolio_payload, gap_payload = await asyncio.gather(
            asyncio.to_thread(get_houjin_portfolio, houjin_bangou=houjin_bangou),
            asyncio.to_thread(find_gap_programs, houjin_bangou=houjin_bangou, top_n=top_n),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("he1.portfolio_gap failed: %s", exc)
        return {"error": str(exc)[:128]}
    portfolio = _safe_dict(portfolio_payload)
    gap = _safe_dict(gap_payload)
    return {
        "portfolio": _trim_list(portfolio.get("results"), top_n),
        "gap_programs": _trim_list(gap.get("results"), top_n),
        "houjin_bangou": houjin_bangou,
        "portfolio_total": portfolio.get("total", 0),
        "gap_total": gap.get("total", 0),
    }


async def _call_pending_alerts(houjin_bangou: str | None, cap: int) -> list[dict[str, Any]]:
    """N6 - amendment alerts for the houjin (or global feed when None)."""
    try:
        from jpintel_mcp.mcp.moat_lane_tools.moat_n6_alert import list_pending_alerts
    except (ImportError, AttributeError):
        return []
    try:
        # ``list_pending_alerts`` accepts houjin_bangou=None - it falls
        # back to the global pending feed ordered by impact_score DESC.
        payload = await asyncio.to_thread(
            list_pending_alerts,
            houjin_bangou=houjin_bangou,
            horizon_days=30,
            limit=cap,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("he1.list_pending_alerts failed: %s", exc)
        return []
    return _trim_list(_safe_dict(payload).get("results"), cap)


async def _call_segment_view(query: str, cap: int) -> dict[str, Any]:
    """N7 - segment view rollup.

    We cannot derive an authoritative JSIC major from a free-text query
    without an LLM. To stay LLM-free, we fall back to a JSIC=``A``
    (agriculture) probe and let the agent narrow further with N7
    directly. Empty results are graceful.
    """
    try:
        from jpintel_mcp.mcp.moat_lane_tools.moat_n7_segment import segment_summary
    except (ImportError, AttributeError):
        return {}
    try:
        payload = await asyncio.to_thread(segment_summary, jsic_major=None, limit=cap)
    except Exception as exc:  # noqa: BLE001
        logger.warning("he1.segment_summary failed: %s", exc)
        return {"error": str(exc)[:128]}
    body = _safe_dict(payload)
    rows = _trim_list(body.get("results"), cap)
    return {
        "rollup": rows,
        "total_segments": body.get("total", 0),
        "hint": "Use get_segment_view(jsic_major=...) for a concrete slice.",
    }


async def _call_list_recipes(n8_segment: str, cap: int) -> list[dict[str, Any]]:
    """N8 - recipe bank filtered by segment."""
    try:
        from jpintel_mcp.mcp.moat_lane_tools.moat_n8_recipe import list_recipes
    except (ImportError, AttributeError):
        return []
    try:
        payload = await asyncio.to_thread(list_recipes, segment=n8_segment, limit=min(cap, 100))
    except Exception as exc:  # noqa: BLE001
        logger.warning("he1.list_recipes failed: %s", exc)
        return []
    return _trim_list(_safe_dict(payload).get("results"), cap)


# A small canonical set of placeholders we always preview. Keeps the
# response shape stable across queries; the agent can call
# ``resolve_placeholder`` directly for any other token it needs.
_CANONICAL_PLACEHOLDERS: tuple[str, ...] = (
    "{{HOUJIN_NAME}}",
    "{{HOUJIN_BANGOU}}",
    "{{REGISTERED_ADDRESS}}",
    "{{REPRESENTATIVE_NAME}}",
    "{{CURRENT_DATE}}",
    "{{OPERATOR_NAME}}",
    "{{TAX_OFFICE_NAME}}",
    "{{PROGRAM_NAME}}",
    "{{AMOUNT_MAX_MAN_YEN}}",
    "{{DEADLINE}}",
)


async def _call_placeholder_preview(houjin_bangou: str | None, cap: int) -> list[dict[str, Any]]:
    """N9 - resolve a small preview slate of canonical placeholders.

    Returns lightweight {placeholder, mcp_tool_name, value_kind,
    is_sensitive} rows. The agent uses this to plan which downstream
    calls it needs (and skip the ones it already knows the value of).
    """
    if cap <= 0:
        return []
    try:
        from jpintel_mcp.mcp.moat_lane_tools.moat_n9_placeholder import (
            resolve_placeholder,
        )
    except (ImportError, AttributeError):
        return []

    context = {
        "HOUJIN_BANGOU": houjin_bangou or "",
        "OPERATOR_NAME": "Bookyou株式会社",
        "CURRENT_DATE": today_iso_utc(),
    }
    context_json = json.dumps(context, ensure_ascii=False)
    tasks = [
        asyncio.to_thread(
            resolve_placeholder,
            placeholder_name=name,
            context_dict_json=context_json,
        )
        for name in _CANONICAL_PLACEHOLDERS[:cap]
    ]
    try:
        payloads = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as exc:  # noqa: BLE001 - defensive; gather never raises
        logger.warning("he1.placeholder_preview gather failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for name, payload in zip(_CANONICAL_PLACEHOLDERS[:cap], payloads, strict=False):
        if isinstance(payload, BaseException):
            out.append(
                {
                    "placeholder": name,
                    "status": "error",
                    "error": str(payload)[:128],
                }
            )
            continue
        body = _safe_dict(payload)
        result = _safe_dict(body.get("primary_result"))
        out.append(
            {
                "placeholder": name,
                "mcp_tool_name": result.get("mcp_tool_name"),
                "value_kind": result.get("value_kind"),
                "is_sensitive": bool(result.get("is_sensitive", False)),
                "status": result.get("status", "ok"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Hint generator
# ---------------------------------------------------------------------------


def _build_next_call_hints(
    *,
    query: str,
    segment: str | None,
    houjin_bangou: str | None,
    has_programs: bool,
    has_portfolio_gap: bool,
    has_reasoning: bool,
) -> list[dict[str, str]]:
    """Suggest the next 3-5 follow-up calls the agent can make.

    Hints are deterministic - no LLM. Each entry carries
    {action, tool, args_hint} so the agent can dispatch immediately.
    """
    hints: list[dict[str, str]] = []
    if has_programs:
        hints.append(
            {
                "action": "Deep-dive top program",
                "tool": "program_full_context",
                "args_hint": "Pick program_id from core_results.programs[0]",
            }
        )
    if not houjin_bangou:
        hints.append(
            {
                "action": "Personalize with a houjin_bangou",
                "tool": "agent_full_context",
                "args_hint": "Re-call with houjin_bangou=... to unlock portfolio_gap + filing_windows.",
            }
        )
    if has_portfolio_gap:
        hints.append(
            {
                "action": "Enumerate gap programs",
                "tool": "find_gap_programs",
                "args_hint": f"houjin_bangou={houjin_bangou}, top_n=20",
            }
        )
    if has_reasoning:
        hints.append(
            {
                "action": "Pull the full reasoning chain",
                "tool": "get_reasoning_chain",
                "args_hint": "Use topic_id from reasoning_chain.results[0].topic_id",
            }
        )
    if segment is None:
        hints.append(
            {
                "action": "Tailor to a 士業 segment",
                "tool": "agent_full_context",
                "args_hint": "Re-call with segment='税理士' / '会計士' / etc.",
            }
        )
    return hints[:5]


# ---------------------------------------------------------------------------
# Citation + provenance envelope
# ---------------------------------------------------------------------------


def _build_citation_envelope(core: dict[str, Any]) -> dict[str, Any]:
    """Aggregate citations across the composed sub-payloads."""
    sources: list[str] = []
    for program in core.get("programs", [])[:5]:
        if isinstance(program, dict):
            url = program.get("source_url") or program.get("url")
            if isinstance(url, str) and url.startswith("http"):
                sources.append(url)
    return {
        "primary_sources": sources,
        "total_primary_sources": len(sources),
        "license": "moat lane retrieval; primary URLs are first-party government / law / 通達 / 採択 surfaces.",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def _agent_full_context_impl(
    *,
    query: str,
    segment: str | None,
    houjin_bangou: str | None,
    depth_level: int,
) -> dict[str, Any]:
    """Synchronous orchestration of the HE-1 composer.

    The implementation lives here (not on the ``@mcp.tool`` decorated
    function) so tests can call it directly without going through the
    MCP transport layer.
    """
    if not query or not isinstance(query, str):
        return {
            "tool_name": _TOOL_NAME,
            "schema_version": _SCHEMA_VERSION,
            "lane_id": _LANE_ID,
            "error": {"code": "invalid_input", "message": "query must be a non-empty string."},
            "_billing_unit": 4,
            "_disclaimer": DISCLAIMER,
            "billing": {
                "unit": 4,
                "yen": 12,
                "tier": "C",
                "pricing_version": "v3",
                "depth_level": depth_level,
            },
        }
    query = query.strip()
    profile = _depth_profile(depth_level)
    n1_segment, n8_segment = _normalize_segment(segment)

    # Fan out — every call is independent at this layer. ``asyncio.gather``
    # cannot preserve the per-coroutine return type when the tuple is
    # heterogeneous; we collect into a list[Any] and unpack at the use
    # sites (each pop is locally typed via the helper return signatures).
    gathered_any: list[Any] = list(
        await asyncio.gather(
            _call_resolve_alias(query, profile["top_aliases"]),
            _call_search_programs(query, profile["top_programs"]),
            _call_walk_reasoning(
                query,
                profile["reasoning_limit"],
                bool(profile["include_reasoning_opposing"]),
            ),
            _call_find_filing_window(houjin_bangou, query, profile["windows_limit"]),
            _call_list_artifact_templates(n1_segment, profile["templates_limit"]),
            _call_portfolio_gap(houjin_bangou, profile["portfolio_top_n"]),
            _call_pending_alerts(houjin_bangou, profile["alerts_limit"]),
            _call_segment_view(query, 5),
            _call_list_recipes(n8_segment, profile["recipes_limit"]),
            _call_placeholder_preview(houjin_bangou, profile["placeholders_limit"]),
        )
    )
    aliases: list[dict[str, Any]] = gathered_any[0]
    programs: list[dict[str, Any]] = gathered_any[1]
    reasoning_chain: dict[str, Any] = gathered_any[2]
    filing_windows: list[dict[str, Any]] = gathered_any[3]
    templates: list[dict[str, Any]] = gathered_any[4]
    portfolio_gap: dict[str, Any] = gathered_any[5]
    alerts: list[dict[str, Any]] = gathered_any[6]
    segment_view: dict[str, Any] = gathered_any[7]
    recipes: list[dict[str, Any]] = gathered_any[8]
    placeholder_preview: list[dict[str, Any]] = gathered_any[9]

    core_results: dict[str, Any] = {
        "programs": programs,
        # The atomic lanes for law_articles / judgments / tsutatsu / case_studies
        # do not have a free-text composed cross-tool yet; we surface the
        # ``programs`` result first (it embeds program_law_refs at fields='full')
        # and leave dedicated slots for the agent to drill into via
        # ``law_related_programs_cross`` / ``cases_by_industry_size_pref`` etc.
        "law_articles": [],
        "judgments": [],
        "tsutatsu": [],
        "case_studies": [],
    }

    hints = _build_next_call_hints(
        query=query,
        segment=segment,
        houjin_bangou=houjin_bangou,
        has_programs=bool(programs),
        has_portfolio_gap=bool(portfolio_gap),
        has_reasoning=bool(reasoning_chain.get("results")),
    )

    envelope: dict[str, Any] = {
        "tool_name": _TOOL_NAME,
        "schema_version": _SCHEMA_VERSION,
        "lane_id": _LANE_ID,
        "query": query,
        "resolved_aliases": aliases,
        "core_results": core_results,
        "reasoning_chain": reasoning_chain,
        "filing_windows": filing_windows,
        "applicable_artifact_templates": templates,
        "houjin_portfolio_gap": portfolio_gap,
        "amendment_alerts": alerts,
        "segment_view": segment_view,
        "related_recipes": recipes,
        "placeholder_mappings_preview": placeholder_preview,
        "next_call_hints": hints,
        "billing": {
            "unit": 4,
            "yen": 12,
            "tier": "C",
            "pricing_version": "v3",
            "depth_level": depth_level,
        },
        "_disclaimer": DISCLAIMER,
        "_billing_unit": 4,
        "_citation_envelope": _build_citation_envelope(core_results),
        "_provenance": {
            "source_module": "jpintel_mcp.mcp.moat_lane_tools.he1_full_context",
            "lane_id": _LANE_ID,
            "observed_at": today_iso_utc(),
            "composition": [
                "moat_n5_synonym.resolve_alias",
                "mcp.server.search_programs",
                "moat_n3_reasoning.walk_reasoning_chain",
                "moat_n4_window.find_filing_window",
                "moat_n1_artifact.list_artifact_templates",
                "moat_n2_portfolio.{get_houjin_portfolio,find_gap_programs}",
                "moat_n6_alert.list_pending_alerts",
                "moat_n7_segment.segment_summary",
                "moat_n8_recipe.list_recipes",
                "moat_n9_placeholder.resolve_placeholder",
            ],
            "no_llm": True,
            "round_trip_savings": "1 call replaces 5-10 atomic calls under typical depth_level=3 use.",
        },
    }
    return envelope


@mcp.tool(annotations=_READ_ONLY)
async def agent_full_context(
    query: Annotated[
        str,
        Field(
            min_length=1,
            max_length=512,
            description=(
                "Free-text question or topic. Example: 'ものづくり補助金' / "
                "'インボイス制度' / '役員報酬の損金算入' / 'IT導入'."
            ),
        ),
    ],
    segment: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional 士業 / business segment. Accepts JA "
                "(税理士 / 会計士 / 行政書士 / 司法書士 / 社労士) or "
                "business slugs (中小経営者 / AX_engineer). Unknown values "
                "fall back to 'all'."
            ),
        ),
    ] = None,
    houjin_bangou: Annotated[
        str | None,
        Field(
            default=None,
            min_length=13,
            max_length=13,
            pattern=r"^\d{13}$",
            description=(
                "Optional 13-digit corporate number. When set, unlocks "
                "the portfolio_gap matrix + filing_windows + houjin-"
                "specific amendment alerts. Omit for an anonymous query."
            ),
        ),
    ] = None,
    depth_level: Annotated[
        int,
        Field(
            ge=1,
            le=5,
            description=(
                "Response depth. 1=LITE (~5KB top-1 each) / 3=NORMAL "
                "(~30KB top-5 each, default) / 5=FULL (~100KB top-10 "
                "each + opposing views + full portfolio matrix)."
            ),
        ),
    ] = 3,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE - §52/§47条の2/§72/§1/§3] Moat HE-1 - 1-call
    agent_full_context.

    Returns everything an agent needs (resolved aliases + top programs
    + reasoning chain walk + filing windows + applicable artifact
    templates + houjin portfolio_gap + amendment alerts + segment view
    + related recipes + canonical placeholder preview + next_call_hints)
    in a single response. Replaces the 5-10 atomic round trips an agent
    would otherwise need to assemble the same context.

    NO LLM inference. NO HTTP. Pure SQLite + Python composition over
    existing moat lanes (N1..N9 + ``search_programs``).
    """
    return await _agent_full_context_impl(
        query=query,
        segment=segment,
        houjin_bangou=houjin_bangou,
        depth_level=int(depth_level),
    )
