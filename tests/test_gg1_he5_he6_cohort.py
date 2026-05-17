"""Tests for GG1 — HE-5 + HE-6 cohort-differentiated heavy endpoints.

Covers the 10 cohort-specific endpoints (HE-5 × 5 + HE-6 × 5).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from jpintel_mcp.mcp.moat_lane_tools._shared_cohort import (
    COHORT_IDS,
    COHORT_LABELS_JA,
    COHORT_VOCAB,
    cohort_terminology_hydrate,
    he5_cost_saving_footer,
    he6_cost_saving_footer,
)
from jpintel_mcp.mcp.moat_lane_tools.he5_cohort_deep._core import (
    HE5_LANE_ID,
    HE5_SCHEMA_VERSION,
    HE5_SECTIONS,
    HE5_UNITS,
    HE5_YEN,
    build_he5_payload,
)
from jpintel_mcp.mcp.moat_lane_tools.he6_cohort_ultra._core import (
    HE6_LANE_ID,
    HE6_SCHEMA_VERSION,
    HE6_SECTIONS,
    HE6_UNITS,
    HE6_YEN,
    build_he6_payload,
)

_PER_COHORT_QUERY: dict[str, str] = {
    "zeirishi": "損金算入",
    "kaikeishi": "監査調書",
    "gyouseishoshi": "建設業許可",
    "shihoshoshi": "商業登記",
    "chusho_keieisha": "事業承継",
}


@pytest.mark.parametrize("cohort", list(COHORT_IDS))
def test_he5_returns_canonical_eight_sections(cohort: str) -> None:
    out = build_he5_payload(
        cohort=cohort,
        query=_PER_COHORT_QUERY[cohort],
        entity_id=None,
        context_token=None,
    )
    assert out["primary_result"]["status"] == "ok"
    assert out["primary_result"]["cohort"] == cohort
    assert out["primary_result"]["cohort_label_ja"] == COHORT_LABELS_JA[cohort]
    sections = tuple(s["section"] for s in out["sections"])
    assert sections == HE5_SECTIONS
    assert len(out["sections"]) == 8


@pytest.mark.parametrize("cohort", list(COHORT_IDS))
def test_he6_returns_canonical_fifteen_sections(cohort: str) -> None:
    out = build_he6_payload(
        cohort=cohort,
        query=_PER_COHORT_QUERY[cohort],
        entity_id=None,
        context_token=None,
    )
    assert out["primary_result"]["status"] == "ok"
    assert out["primary_result"]["cohort"] == cohort
    sections = tuple(s["section"] for s in out["sections"])
    assert sections == HE6_SECTIONS
    assert len(out["sections"]) == 15


@pytest.mark.parametrize(
    ("cohort", "expected_terms"),
    [
        ("zeirishi", ("損金算入", "別表", "別表4")),
        ("kaikeishi", ("監査調書", "内部統制", "関連当事者取引")),
        ("gyouseishoshi", ("許認可", "添付書類", "建設業許可")),
        ("shihoshoshi", ("商業登記", "登記識別情報", "申請順序")),
        ("chusho_keieisha", ("補助金併用", "資金繰り", "事業承継税制")),
    ],
)
def test_he5_cohort_vocab_present_in_response(cohort: str, expected_terms: tuple[str, ...]) -> None:
    out = build_he5_payload(
        cohort=cohort,
        query=_PER_COHORT_QUERY[cohort],
        entity_id=None,
        context_token=None,
    )
    body = "\n".join(s["content"] for s in out["sections"])
    for term in expected_terms:
        assert term in body, f"Cohort '{cohort}' response missing canonical term '{term}'."


@pytest.mark.parametrize(
    ("cohort", "expected_terms"),
    [
        ("zeirishi", ("損金算入", "2割特例", "電子帳簿保存法")),
        ("kaikeishi", ("J-SOX", "PBC list", "監査調書")),
        ("gyouseishoshi", ("許認可", "添付書類", "受付印")),
        ("shihoshoshi", ("登記原因証明情報", "司法書士法 §3", "オンライン申請")),
        ("chusho_keieisha", ("排他ルール", "経営承継円滑化法", "事業承継税制")),
    ],
)
def test_he6_cohort_vocab_present_in_response(cohort: str, expected_terms: tuple[str, ...]) -> None:
    out = build_he6_payload(
        cohort=cohort,
        query=_PER_COHORT_QUERY[cohort],
        entity_id=None,
        context_token=None,
    )
    body = "\n".join(s["content"] for s in out["sections"])
    for term in expected_terms:
        assert term in body, f"Cohort '{cohort}' HE-6 response missing canonical term '{term}'."


def test_he5_pricing_is_d_tier_ten_units_thirty_yen() -> None:
    assert HE5_UNITS == 10
    assert HE5_YEN == 30
    out = build_he5_payload(
        cohort="zeirishi",
        query="法人税申告",
        entity_id=None,
        context_token=None,
    )
    bill = out["billing"]
    assert bill["billable_units"] == 10
    assert bill["unit_price_jpy"] == 3
    assert bill["total_jpy"] == 30
    assert bill["unit_price_jpy_taxed"] == pytest.approx(3.30)
    assert bill["model"] == "per_call_d_tier"
    assert out["_billing_unit"] == 10


def test_he6_pricing_is_d_plus_tier_thirty_three_units_hundred_yen() -> None:
    assert HE6_UNITS == 33
    assert HE6_YEN == 100
    out = build_he6_payload(
        cohort="kaikeishi",
        query="監査計画",
        entity_id=None,
        context_token=None,
    )
    bill = out["billing"]
    assert bill["billable_units"] == 33
    assert bill["unit_price_jpy"] == 3
    assert bill["total_jpy"] == 100
    assert bill["model"] == "per_call_d_plus_tier"
    assert out["_billing_unit"] == 33


def test_he5_cost_saving_footer_present_with_cohort_label() -> None:
    out = build_he5_payload(
        cohort="zeirishi",
        query="役員報酬",
        entity_id=None,
        context_token=None,
    )
    narrative = out["cost_saving_narrative"]
    assert "7-turn Opus 4.7" in narrative
    assert "¥30" in narrative
    assert "1/17-1/24" in narrative
    assert "税理士" in narrative


def test_he6_cost_saving_footer_present_with_cohort_label() -> None:
    out = build_he6_payload(
        cohort="chusho_keieisha",
        query="事業承継",
        entity_id=None,
        context_token=None,
    )
    narrative = out["cost_saving_narrative"]
    assert "21-turn Opus 4.7" in narrative
    assert "¥100" in narrative
    assert "1/15" in narrative
    assert "中小経営者" in narrative


def test_he5_unknown_cohort_returns_error_envelope() -> None:
    out = build_he5_payload(
        cohort="not_a_real_cohort",
        query="test",
        entity_id=None,
        context_token=None,
    )
    assert out["primary_result"]["status"] == "error"
    assert "not_a_real_cohort" in out["primary_result"]["rationale"]


def test_he6_unknown_cohort_returns_error_envelope() -> None:
    out = build_he6_payload(
        cohort="not_a_real_cohort",
        query="test",
        entity_id=None,
        context_token=None,
    )
    assert out["primary_result"]["status"] == "error"
    assert "not_a_real_cohort" in out["primary_result"]["rationale"]


def test_he5_entity_id_appears_in_context_section() -> None:
    out = build_he5_payload(
        cohort="zeirishi",
        query="法人税申告",
        entity_id="1234567890123",
        context_token=None,
    )
    ctx = next(s for s in out["sections"] if s["section"] == "context")
    assert "1234567890123" in ctx["content"]


def test_he6_context_token_appears_in_handoff_schema() -> None:
    out = build_he6_payload(
        cohort="kaikeishi",
        query="監査計画",
        entity_id="9876543210987",
        context_token="session_abc_token_xyz",
    )
    handoff = out["structured_payload"]["handoff_schema"]
    assert handoff["entity_id"] == "9876543210987"
    assert handoff["context_token_present"] is True
    assert handoff["context_token_ttl_seconds"] == 86400


def test_he5_envelope_contains_lane_id_and_disclaimer() -> None:
    out = build_he5_payload(
        cohort="gyouseishoshi",
        query="建設業許可",
        entity_id=None,
        context_token=None,
    )
    assert out["primary_result"]["lane_id"] == HE5_LANE_ID == "HE5"
    assert out["schema_version"] == HE5_SCHEMA_VERSION == "moat.he5.v1"
    assert "_disclaimer" in out
    assert out["_provenance"]["lane_id"] == "HE5"
    assert out["_provenance"]["cohort"] == "gyouseishoshi"
    assert out["_provenance"]["no_llm"] is True


def test_he6_envelope_contains_lane_id_and_disclaimer() -> None:
    out = build_he6_payload(
        cohort="shihoshoshi",
        query="商業登記",
        entity_id=None,
        context_token=None,
    )
    assert out["primary_result"]["lane_id"] == HE6_LANE_ID == "HE6"
    assert out["schema_version"] == HE6_SCHEMA_VERSION == "moat.he6.v1"
    assert "_disclaimer" in out
    assert out["_provenance"]["lane_id"] == "HE6"
    assert out["_provenance"]["cohort"] == "shihoshoshi"
    assert out["_provenance"]["no_llm"] is True


def test_he6_structured_payload_has_checkpoints_and_risk_register() -> None:
    out = build_he6_payload(
        cohort="zeirishi",
        query="法人税",
        entity_id="1111111111111",
        context_token=None,
    )
    sp = out["structured_payload"]
    cps = sp["intermediate_checkpoints"]
    risks = sp["risk_register"]
    assert isinstance(cps, list) and len(cps) == 5
    assert isinstance(risks, list) and len(risks) == 4
    for cp in cps:
        assert set(cp.keys()) >= {
            "checkpoint_id",
            "stage",
            "objective",
            "status",
            "review_cadence",
            "evidence_required",
        }
        assert cp["status"] == "pending"
    for r in risks:
        assert set(r.keys()) >= {"id", "risk", "mitigation"}


@pytest.mark.parametrize(
    ("cohort", "body", "must_find"),
    [
        ("zeirishi", "別表4 + 損金算入 の確認", ("別表4", "損金算入")),
        ("kaikeishi", "監査調書 と J-SOX 評価", ("監査調書", "J-SOX")),
        ("gyouseishoshi", "許認可 + 添付書類 一覧", ("許認可", "添付書類")),
        ("shihoshoshi", "商業登記 と 申請順序", ("商業登記", "申請順序")),
        ("chusho_keieisha", "事業承継税制 と 補助金併用", ("事業承継税制", "補助金併用")),
    ],
)
def test_cohort_terminology_hydrate(cohort: str, body: str, must_find: tuple[str, ...]) -> None:
    h = cohort_terminology_hydrate(cohort, body)
    for term in must_find:
        assert term in h["terms_found"]
    assert h["total_lexicon"] == len(COHORT_VOCAB[cohort])
    assert 0.0 <= h["coverage_ratio"] <= 1.0


@pytest.mark.parametrize("cohort", list(COHORT_IDS))
def test_he5_footer_unique_per_cohort(cohort: str) -> None:
    msg = he5_cost_saving_footer(cohort)
    assert COHORT_LABELS_JA[cohort] in msg
    assert "¥30" in msg
    assert "1/17-1/24" in msg


@pytest.mark.parametrize("cohort", list(COHORT_IDS))
def test_he6_footer_unique_per_cohort(cohort: str) -> None:
    msg = he6_cost_saving_footer(cohort)
    assert COHORT_LABELS_JA[cohort] in msg
    assert "¥100" in msg
    assert "1/15" in msg


def test_fragment_yaml_parse_extracts_two_packages() -> None:
    from jpintel_mcp.mcp.moat_lane_tools._he_cohort_bootstrap import (
        _parse_fragment_packages,
    )

    text = """
fragments:
  - package: he5_cohort_deep
    description: foo
  - package: he6_cohort_ultra
    description: bar
"""
    pkgs = _parse_fragment_packages(text)
    assert pkgs == ["he5_cohort_deep", "he6_cohort_ultra"]


def test_fragment_bootstrap_registers_10_cohort_tools() -> None:
    """Booting the moat_lane_tools package must register all 10 cohort tools."""
    import jpintel_mcp.mcp.moat_lane_tools  # noqa: F401
    from jpintel_mcp.mcp.server import mcp

    async def _collect() -> list[str]:
        tools = await mcp.list_tools()
        return sorted(t.name for t in tools if t.name.startswith("agent_cohort_"))

    names = asyncio.run(_collect())
    expected = sorted(
        [
            "agent_cohort_deep_zeirishi",
            "agent_cohort_deep_kaikeishi",
            "agent_cohort_deep_gyouseishoshi",
            "agent_cohort_deep_shihoshoshi",
            "agent_cohort_deep_chusho_keieisha",
            "agent_cohort_ultra_zeirishi",
            "agent_cohort_ultra_kaikeishi",
            "agent_cohort_ultra_gyouseishoshi",
            "agent_cohort_ultra_shihoshoshi",
            "agent_cohort_ultra_chusho_keieisha",
        ]
    )
    assert names == expected


@pytest.mark.parametrize("cohort", list(COHORT_IDS))
def test_he5_hydration_coverage_nonzero(cohort: str) -> None:
    out = build_he5_payload(
        cohort=cohort,
        query=_PER_COHORT_QUERY[cohort],
        entity_id=None,
        context_token=None,
    )
    hyd: dict[str, Any] = out["cohort_terminology_hydration"]
    assert hyd["total_lexicon"] > 0
    assert hyd["coverage_ratio"] > 0.0
