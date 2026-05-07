"""S7 finding (2026-04-25): uniform `_disclaimer` envelope on sensitive tools.

Covers
------
1. Each sensitive tool surfaces a non-empty `_disclaimer` string in the
   envelope merge path. Sensitive set = {dd_profile_am, regulatory_prep_pack,
   combined_compliance_check, rule_engine_check, predict_subsidy_outcome,
   score_dd_risk, intent_of, reason_answer, search_tax_incentives,
   get_am_tax_rule, list_tax_sunset_alerts}. Tax tools were promoted on
   2026-04-29 (税理士法 §52 fence — jpcite.com brand sits in 税務会計
   territory; every tax surface MUST decline 税務助言).

2. `disclaimer_level="minimal"` shortens the disclaimer (less than the
   "standard" form) — for token-sensitive surfaces.

3. Non-sensitive tools (`get_meta`, `search_programs`, ...) do NOT carry a
   `_disclaimer` field — adding it everywhere would dilute the warning and
   waste tokens.

This guards against the J9-style regression where a wired field exists in
envelope_wrapper but no caller actually surfaces it on the tool response.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is on path for direct test runs.
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_envelope_merge():
    """Lazy import of the server.py merge helper (mirrors test_envelope_wiring)."""
    from jpintel_mcp.mcp.server import _envelope_merge

    return _envelope_merge


def _import_build_envelope():
    from jpintel_mcp.mcp.autonomath_tools.envelope_wrapper import (
        SENSITIVE_TOOLS,
        build_envelope,
        disclaimer_for,
    )

    return build_envelope, disclaimer_for, SENSITIVE_TOOLS


# ---------------------------------------------------------------------------
# 1. Every sensitive tool surfaces `_disclaimer` on the merged envelope.
# ---------------------------------------------------------------------------


def test_sensitive_tools_carry_disclaimer():
    """All sensitive tools yield a non-empty `_disclaimer` via _envelope_merge.

    Set includes the original 6 (DD / compliance / scoring) plus intent_of /
    reason_answer (added 2026-04-25) plus tax tools search_tax_incentives /
    get_am_tax_rule / list_tax_sunset_alerts (added 2026-04-29 for 税理士法
    §52 fence — jpcite.com brand).
    """
    _envelope_merge = _import_envelope_merge()
    _, _, sensitive = _import_build_envelope()

    expected = {
        "dd_profile_am",
        "regulatory_prep_pack",
        "combined_compliance_check",
        "rule_engine_check",
        "predict_subsidy_outcome",
        "score_dd_risk",
        "intent_of",
        "reason_answer",
        "search_tax_incentives",
        "get_am_tax_rule",
        "list_tax_sunset_alerts",
    }
    assert expected.issubset(sensitive), f"SENSITIVE_TOOLS missing entries: {expected - sensitive}"

    for tool_name in expected:
        result = {
            "results": [{"id": "x"}],
            "total": 1,
            "limit": 20,
            "offset": 0,
        }
        merged = _envelope_merge(
            tool_name=tool_name,
            result=result,
            kwargs={},
            latency_ms=1.0,
        )
        assert isinstance(merged, dict)
        d = merged.get("_disclaimer")
        assert isinstance(d, str), f"{tool_name}: missing _disclaimer"
        assert len(d) >= 20, f"{tool_name}: _disclaimer too short ({len(d)} chars)"


# ---------------------------------------------------------------------------
# 2. `disclaimer_level="minimal"` produces a shorter string than "standard".
# ---------------------------------------------------------------------------


def test_disclaimer_level_minimal_is_shorter():
    """minimal must produce a shorter string than standard for the same tool."""
    build_envelope, disclaimer_for, _ = _import_build_envelope()

    for tool_name in (
        "dd_profile_am",
        "regulatory_prep_pack",
        "combined_compliance_check",
        "rule_engine_check",
        "predict_subsidy_outcome",
        "score_dd_risk",
        "intent_of",
        "reason_answer",
        "search_tax_incentives",
        "get_am_tax_rule",
        "list_tax_sunset_alerts",
    ):
        std = disclaimer_for(tool_name, "standard")
        mini = disclaimer_for(tool_name, "minimal")
        strict = disclaimer_for(tool_name, "strict")
        assert std and mini and strict
        assert len(mini) < len(std), f"{tool_name}: minimal ({len(mini)}) >= standard ({len(std)})"
        assert len(strict) > len(std), (
            f"{tool_name}: strict ({len(strict)}) <= standard ({len(std)})"
        )

    # End-to-end via build_envelope: minimal level reaches the envelope
    # field intact.
    env_min = build_envelope(
        tool_name="dd_profile_am",
        results=[{"id": "x"}],
        disclaimer_level="minimal",
    )
    env_std = build_envelope(
        tool_name="dd_profile_am",
        results=[{"id": "x"}],
        disclaimer_level="standard",
    )
    assert env_min["_disclaimer"] != env_std["_disclaimer"]
    assert len(env_min["_disclaimer"]) < len(env_std["_disclaimer"])


# ---------------------------------------------------------------------------
# 3. Non-sensitive tools do NOT carry `_disclaimer`.
# ---------------------------------------------------------------------------


def test_non_sensitive_tools_omit_disclaimer():
    """get_meta / search_programs / search_certifications must NOT have `_disclaimer`.

    Note: search_tax_incentives, get_am_tax_rule, list_tax_sunset_alerts were
    REMOVED from this set on 2026-04-29 — they are now sensitive (税理士法 §52
    fence). See test_sensitive_tools_carry_disclaimer.
    """
    _envelope_merge = _import_envelope_merge()
    build_envelope, disclaimer_for, _ = _import_build_envelope()

    for tool_name in (
        "get_meta",
        "search_programs",
        "search_certifications",
    ):
        # disclaimer_for returns None directly.
        assert disclaimer_for(tool_name) is None

        # build_envelope omits the field entirely (vs. setting it to None).
        env = build_envelope(
            tool_name=tool_name,
            results=[{"id": "x"}],
        )
        assert "_disclaimer" not in env, (
            f"{tool_name}: unexpected _disclaimer={env.get('_disclaimer')!r}"
        )

        # _envelope_merge must not inject one either.
        merged = _envelope_merge(
            tool_name=tool_name,
            result={
                "results": [{"id": "x"}],
                "total": 1,
                "limit": 20,
                "offset": 0,
            },
            kwargs={},
            latency_ms=1.0,
        )
        assert "_disclaimer" not in merged, (
            f"{tool_name}: leaked _disclaimer={merged.get('_disclaimer')!r}"
        )


# ---------------------------------------------------------------------------
# 4. REST `_apply_envelope` surfaces `_disclaimer` for the 4 sensitive REST
#    routes — R8_DISCLAIMER_LIVE_VERIFY (2026-05-07).
#
# Pre-fix bug: `src/jpintel_mcp/api/autonomath.py:_apply_envelope` additive
# tuple omitted the `_disclaimer` key, so /v1/am/{acceptance_stats,
# enforcement, loans, mutual_plans} dropped the disclaimer on the way back
# to REST clients. MCP path (`mcp/server.py:_envelope_merge`) carried it
# correctly — but Custom GPT-style consumers do not transit MCP, so the
# 業法 fence (行政書士法 §1 / 貸金業法 §3 / 弁護士法 §72 / 保険業法 §3)
# was bypassed silently.
#
# These tests guard the additive tuple AND the tool_name string the route
# actually hands to `_apply_envelope` (acceptance_stats was passing
# "search_acceptance_stats" without the `_am` suffix, which falls outside
# SENSITIVE_TOOLS — so even with the additive fix the disclaimer never
# resolves until the name is corrected).
# ---------------------------------------------------------------------------


def _import_apply_envelope():
    from jpintel_mcp.api.autonomath import _apply_envelope

    return _apply_envelope


def test_rest_apply_envelope_surfaces_disclaimer_on_4_sensitive_routes():
    """REST `_apply_envelope` must surface `_disclaimer` for the 4 sensitive routes.

    The 4 routes (acceptance_stats / enforcement / loans / mutual_plans) sit
    in distinct 業法 fences and MUST emit a non-empty `_disclaimer` so that
    REST AI consumers (Custom GPT, OpenAPI plugin clients) receive the same
    fence text MCP clients already do.
    """
    _apply_envelope = _import_apply_envelope()

    # Tool name strings exactly as the route passes them today (post-fix).
    # Any drift here means a REST route stopped resolving the disclaimer.
    sensitive_tool_names = (
        "search_acceptance_stats_am",
        "search_loans_am",
        "check_enforcement_am",
        "search_mutual_plans_am",
    )

    for tool_name in sensitive_tool_names:
        raw_result: dict = {
            "results": [{"id": "x"}],
            "total": 1,
            "limit": 20,
            "offset": 0,
        }
        merged = _apply_envelope(tool_name, raw_result, query="probe")
        assert isinstance(merged, dict), f"{tool_name}: _apply_envelope dropped dict shape"
        d = merged.get("_disclaimer")
        assert isinstance(d, str), (
            f"{tool_name}: REST `_apply_envelope` did not surface `_disclaimer` "
            f"(business-law fence breach). merged keys = {sorted(merged.keys())}"
        )
        assert len(d) >= 20, f"{tool_name}: `_disclaimer` too short ({len(d)} chars)"


def test_rest_apply_envelope_route_callsite_uses_canonical_tool_names():
    """The 4 routes must call `_apply_envelope` with the canonical `_am`-suffixed
    tool name so the SENSITIVE_TOOLS lookup hits.

    Reads `src/jpintel_mcp/api/autonomath.py` source and asserts each route's
    `_apply_envelope(...)` invocation hands one of the four canonical names.
    A drop back to the un-suffixed form (e.g. "search_acceptance_stats")
    would silently re-introduce the pre-fix bug.
    """
    src = (
        Path(__file__).resolve().parent.parent / "src" / "jpintel_mcp" / "api" / "autonomath.py"
    ).read_text(encoding="utf-8")

    # Each canonical name MUST appear at least once as the first positional
    # argument of an `_apply_envelope(` callsite. We assert presence rather
    # than parse the AST so the test is resilient to formatting churn.
    for canonical in (
        '"search_acceptance_stats_am"',
        '"search_loans_am"',
        '"check_enforcement_am"',
        '"search_mutual_plans_am"',
    ):
        assert canonical in src, (
            f"REST autonomath.py lost canonical tool name {canonical} — "
            "_apply_envelope callsite likely reverted to a non-_am form, "
            "which would break the SENSITIVE_TOOLS lookup."
        )

    # Anti-regression: the un-suffixed form must NOT be passed as a tool name
    # in any `_apply_envelope(...)` call.
    assert '_apply_envelope(\n            "search_acceptance_stats"' not in src, (
        "REST acceptance_stats route is calling _apply_envelope with the "
        "un-suffixed tool name — disclaimer envelope will silently drop."
    )


def test_rest_apply_envelope_disclaimer_matches_mcp_envelope_merge():
    """REST `_apply_envelope` and MCP `_envelope_merge` MUST produce the same
    `_disclaimer` string for the 4 sensitive routes.

    Drift between the two transports is itself a 業法-fence regression — the
    AI consumer should not get a different warning depending on which API
    surface they hit.
    """
    _apply_envelope = _import_apply_envelope()
    _envelope_merge = _import_envelope_merge()

    for tool_name in (
        "search_acceptance_stats_am",
        "search_loans_am",
        "check_enforcement_am",
        "search_mutual_plans_am",
    ):
        raw_result: dict = {
            "results": [{"id": "x"}],
            "total": 1,
            "limit": 20,
            "offset": 0,
        }
        rest_merged = _apply_envelope(tool_name, dict(raw_result), query="probe")
        mcp_merged = _envelope_merge(
            tool_name=tool_name,
            result=dict(raw_result),
            kwargs={},
            latency_ms=1.0,
        )
        assert isinstance(rest_merged, dict) and isinstance(mcp_merged, dict)
        assert rest_merged.get("_disclaimer") == mcp_merged.get("_disclaimer"), (
            f"{tool_name}: REST vs MCP disclaimer drift "
            f"(REST={rest_merged.get('_disclaimer')!r}, "
            f"MCP={mcp_merged.get('_disclaimer')!r})"
        )
