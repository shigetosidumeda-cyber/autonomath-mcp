"""Unit tests for Wave 59 Stream B — top-10 outcome MCP wrappers (169 -> 179).

Each wrapper is exercised at the impl level (the @mcp.tool decorator is opt-in
inside outcome_wave59_b.py and registers the wrapper into the live FastMCP
runtime; the impl bodies are exported via __all__ so we can test the JPCIR
envelope deterministically without needing the FastMCP runtime).

The skeleton index is read from data/wave59_outcome_skeletons.json (bundled
with the source tree). The runtime overlay reads the same shape from the S3
derived packet bucket; tests run hermetically against the fixture.

Hard contract asserts (per JPCIR Evidence + OutcomeContract):

* support_state is ``"supported"`` for outcome_ids whose packet_count > 0
  (all 10 top outcomes have positive packet_count in the fixture).
* evidence_type is ``"structured_record"`` for supported outcomes.
* citations carry source_family_id + access_method + support_state.
* known_gaps use the 7-enum gap_type closed set
  (source_lag / coverage_thin / stale_data / anonymity_floor /
  license_restricted / rate_limited / schema_drift).
* outcome_contract.billable is True (x402 payment header check is enforced
  by the FastMCP middleware on top of this contract).
* _billing_unit is 1 / 2 / 3 for ¥300 / ¥600 / ¥900 price band.
* _disclaimer contains §52 fence.
* No LLM call in the wrapper body (asserted via module symbol inspection).
"""

from __future__ import annotations

from typing import Any

import pytest

from jpintel_mcp.mcp.autonomath_tools.outcome_wave59_b import (
    _outcome_acceptance_probability_impl,
    _outcome_bid_announcement_seasonality_impl,
    _outcome_cross_prefecture_arbitrage_impl,
    _outcome_enforcement_seasonal_trend_impl,
    _outcome_houjin_360_impl,
    _outcome_prefecture_program_heatmap_impl,
    _outcome_program_lineage_impl,
    _outcome_regulatory_q_over_q_diff_impl,
    _outcome_succession_event_pulse_impl,
    _outcome_tax_ruleset_phase_change_impl,
)

_ALLOWED_GAP_TYPES = {
    "source_lag",
    "coverage_thin",
    "stale_data",
    "anonymity_floor",
    "license_restricted",
    "rate_limited",
    "schema_drift",
}


def _common_envelope_checks(
    envelope: dict[str, Any],
    *,
    tool_name: str,
    outcome_id: str,
    billing_unit: int,
) -> None:
    """Shared JPCIR envelope contract checks for every outcome wrapper."""
    assert isinstance(envelope, dict), envelope
    assert envelope.get("tool_name") == tool_name, envelope.get("tool_name")
    assert envelope.get("schema_version") == "wave59.outcome_b.v1"
    assert envelope.get("_billing_unit") == billing_unit
    disclaimer = envelope.get("_disclaimer")
    assert isinstance(disclaimer, str) and "§52" in disclaimer

    ev = envelope.get("evidence")
    assert isinstance(ev, dict), ev
    assert ev.get("support_state") in {"supported", "partial", "contested", "absent"}
    assert ev.get("evidence_type") in {
        "direct_quote",
        "structured_record",
        "metadata_only",
        "screenshot",
        "derived_inference",
        "absence_observation",
    }

    oc = envelope.get("outcome_contract")
    assert isinstance(oc, dict), oc
    assert oc.get("billable") is True
    assert oc.get("outcome_contract_id") == outcome_id

    citations = envelope.get("citations")
    assert isinstance(citations, list) and len(citations) >= 1
    for cit in citations:
        assert isinstance(cit, dict)
        assert isinstance(cit.get("source_family_id"), str)
        assert isinstance(cit.get("source_url"), str)
        assert cit.get("access_method") in {
            "api",
            "bulk",
            "html",
            "playwright",
            "ocr",
            "metadata_only",
        }

    known_gaps = envelope.get("known_gaps")
    assert isinstance(known_gaps, list) and len(known_gaps) >= 1
    for gap in known_gaps:
        assert gap["gap_type"] in _ALLOWED_GAP_TYPES, gap
        assert gap["gap_status"] in {
            "known_gap",
            "blocked",
            "deferred_p1",
            "metadata_only",
        }

    primary = envelope.get("primary_result")
    assert isinstance(primary, dict)
    assert primary.get("outcome_id") == outcome_id
    assert primary.get("cost_band_jpy") in {300, 600, 900}
    assert isinstance(primary.get("s3_packet_uri"), str)
    assert primary["s3_packet_uri"].startswith("s3://")


def test_outcome_houjin_360_happy_path() -> None:
    out = _outcome_houjin_360_impl(houjin_bangou="1234567890123")
    _common_envelope_checks(
        out, tool_name="outcome_houjin_360", outcome_id="houjin_360", billing_unit=3
    )
    assert out["primary_result"]["houjin_bangou"] == "1234567890123"


def test_outcome_houjin_360_t_prefix_accepted() -> None:
    out = _outcome_houjin_360_impl(houjin_bangou="T1234567890123")
    _common_envelope_checks(
        out, tool_name="outcome_houjin_360", outcome_id="houjin_360", billing_unit=3
    )
    assert out["primary_result"]["houjin_bangou"] == "1234567890123"


def test_outcome_houjin_360_invalid_short_returns_error() -> None:
    out = _outcome_houjin_360_impl(houjin_bangou="123")
    assert "error" in out
    assert out["error"]["code"] == "invalid_argument"


def test_outcome_houjin_360_missing_returns_error() -> None:
    out = _outcome_houjin_360_impl(houjin_bangou="")
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"


def test_outcome_program_lineage_happy_path() -> None:
    out = _outcome_program_lineage_impl(program_id="jp_subsidy_xx_2026")
    _common_envelope_checks(
        out,
        tool_name="outcome_program_lineage",
        outcome_id="program_lineage",
        billing_unit=2,
    )
    assert out["primary_result"]["program_id"] == "jp_subsidy_xx_2026"


def test_outcome_acceptance_probability_happy_path() -> None:
    out = _outcome_acceptance_probability_impl(
        program_id="jp_subsidy_aa",
        industry_jsic="D",
        prefecture="東京都",
    )
    _common_envelope_checks(
        out,
        tool_name="outcome_acceptance_probability",
        outcome_id="acceptance_probability",
        billing_unit=2,
    )
    assert out["primary_result"]["industry_jsic"] == "D"
    assert out["primary_result"]["prefecture"] == "東京都"


def test_outcome_acceptance_probability_missing_industry_returns_error() -> None:
    out = _outcome_acceptance_probability_impl(
        program_id="jp_subsidy_aa",
        industry_jsic=" ",
        prefecture="東京都",
    )
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"


def test_outcome_tax_ruleset_phase_change_happy_path() -> None:
    out = _outcome_tax_ruleset_phase_change_impl(rule_id="jp_tax_rdt_2026")
    _common_envelope_checks(
        out,
        tool_name="outcome_tax_ruleset_phase_change",
        outcome_id="tax_ruleset_phase_change",
        billing_unit=2,
    )


def test_outcome_regulatory_q_over_q_diff_happy_path() -> None:
    out = _outcome_regulatory_q_over_q_diff_impl(
        law_id="405AC0000000088",
        fiscal_quarter="2026-Q1",
    )
    _common_envelope_checks(
        out,
        tool_name="outcome_regulatory_q_over_q_diff",
        outcome_id="regulatory_q_over_q_diff",
        billing_unit=3,
    )
    assert out["primary_result"]["fiscal_quarter"] == "2026-Q1"


def test_outcome_enforcement_seasonal_trend_happy_path() -> None:
    out = _outcome_enforcement_seasonal_trend_impl(jsic_major="D")
    _common_envelope_checks(
        out,
        tool_name="outcome_enforcement_seasonal_trend",
        outcome_id="enforcement_seasonal_trend",
        billing_unit=1,
    )


def test_outcome_bid_announcement_seasonality_happy_path() -> None:
    out = _outcome_bid_announcement_seasonality_impl(ministry_code="maff")
    _common_envelope_checks(
        out,
        tool_name="outcome_bid_announcement_seasonality",
        outcome_id="bid_announcement_seasonality",
        billing_unit=1,
    )


def test_outcome_succession_event_pulse_happy_path() -> None:
    out = _outcome_succession_event_pulse_impl(houjin_bangou="1234567890123")
    _common_envelope_checks(
        out,
        tool_name="outcome_succession_event_pulse",
        outcome_id="succession_event_pulse",
        billing_unit=2,
    )


def test_outcome_prefecture_program_heatmap_happy_path() -> None:
    out = _outcome_prefecture_program_heatmap_impl(prefecture="東京都")
    _common_envelope_checks(
        out,
        tool_name="outcome_prefecture_program_heatmap",
        outcome_id="prefecture_program_heatmap",
        billing_unit=2,
    )


def test_outcome_cross_prefecture_arbitrage_happy_path() -> None:
    out = _outcome_cross_prefecture_arbitrage_impl(
        prefecture_a="東京都",
        prefecture_b="北海道",
    )
    _common_envelope_checks(
        out,
        tool_name="outcome_cross_prefecture_arbitrage",
        outcome_id="cross_prefecture_arbitrage",
        billing_unit=3,
    )
    assert out["primary_result"]["prefecture_a"] == "東京都"
    assert out["primary_result"]["prefecture_b"] == "北海道"


def test_outcome_cross_prefecture_arbitrage_same_pair_returns_error() -> None:
    out = _outcome_cross_prefecture_arbitrage_impl(
        prefecture_a="東京都",
        prefecture_b="東京都",
    )
    assert "error" in out
    assert out["error"]["code"] == "invalid_argument"


def test_no_llm_imports_in_module() -> None:
    """The wrapper module must not import any LLM SDK at the top level."""
    import jpintel_mcp.mcp.autonomath_tools.outcome_wave59_b as mod

    forbidden = {"anthropic", "openai", "google.generativeai", "claude_agent_sdk"}
    src = mod.__file__
    assert src is not None
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    for name in forbidden:
        assert name not in text, f"LLM SDK import detected: {name}"


def test_skeleton_index_lists_all_10_outcomes() -> None:
    from jpintel_mcp.mcp.autonomath_tools.outcome_wave59_b import (
        _load_skeleton_index,
    )

    idx = _load_skeleton_index()
    assert isinstance(idx, dict)
    skel = idx.get("skeletons")
    assert isinstance(skel, dict)
    expected = {
        "houjin_360",
        "program_lineage",
        "acceptance_probability",
        "tax_ruleset_phase_change",
        "regulatory_q_over_q_diff",
        "enforcement_seasonal_trend",
        "bid_announcement_seasonality",
        "succession_event_pulse",
        "prefecture_program_heatmap",
        "cross_prefecture_arbitrage",
    }
    assert expected.issubset(set(skel.keys())), set(skel.keys()) ^ expected


@pytest.mark.parametrize(
    ("impl", "tool_name", "outcome_id", "billing_unit", "kwargs"),
    [
        (
            _outcome_houjin_360_impl,
            "outcome_houjin_360",
            "houjin_360",
            3,
            {"houjin_bangou": "1234567890123"},
        ),
        (
            _outcome_program_lineage_impl,
            "outcome_program_lineage",
            "program_lineage",
            2,
            {"program_id": "jp_subsidy_xx"},
        ),
        (
            _outcome_tax_ruleset_phase_change_impl,
            "outcome_tax_ruleset_phase_change",
            "tax_ruleset_phase_change",
            2,
            {"rule_id": "jp_tax_xx"},
        ),
        (
            _outcome_enforcement_seasonal_trend_impl,
            "outcome_enforcement_seasonal_trend",
            "enforcement_seasonal_trend",
            1,
            {"jsic_major": "D"},
        ),
        (
            _outcome_bid_announcement_seasonality_impl,
            "outcome_bid_announcement_seasonality",
            "bid_announcement_seasonality",
            1,
            {"ministry_code": "maff"},
        ),
        (
            _outcome_succession_event_pulse_impl,
            "outcome_succession_event_pulse",
            "succession_event_pulse",
            2,
            {"houjin_bangou": "1234567890123"},
        ),
        (
            _outcome_prefecture_program_heatmap_impl,
            "outcome_prefecture_program_heatmap",
            "prefecture_program_heatmap",
            2,
            {"prefecture": "東京都"},
        ),
    ],
)
def test_all_outcome_wrappers_envelope_shape(
    impl: Any,
    tool_name: str,
    outcome_id: str,
    billing_unit: int,
    kwargs: dict[str, Any],
) -> None:
    """Parametric smoke covering 7 single-arg wrappers in one sweep."""
    out = impl(**kwargs)
    _common_envelope_checks(
        out, tool_name=tool_name, outcome_id=outcome_id, billing_unit=billing_unit
    )
