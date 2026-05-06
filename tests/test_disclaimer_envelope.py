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
