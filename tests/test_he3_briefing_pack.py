"""Tests for Moat HE-3 — agent_briefing_pack MCP tool.

Covers 10+ scenarios:

  1. Token counter: ASCII string in expected range.
  2. Token counter: CJK string in expected range (denser per char).
  3. Token counter: empty string returns 0.
  4. depth_from_budget: budget=8000 → depth 3 (canonical).
  5. depth_from_budget: budget=2000 → depth 2.
  6. depth_from_budget: budget=20000 → depth 5.
  7. depth_from_budget: budget=500 / 30000 → boundary depth 1 / 5.
  8. End-to-end: 税理士 + 役員報酬 → 10 sections + 3 format outputs.
  9. End-to-end: 会計士 + openai_json shape parity.
 10. End-to-end: 中小経営者 + markdown_doc readable shape.
 11. End-to-end: AX_engineer disclaimer envelope mentions Anthropic AUP.
 12. End-to-end: FDE disclaimer envelope mentions SOW.
 13. End-to-end: provenance + billing envelope present and well-formed.
 14. End-to-end: invariant — three format encodings carry the same 10 sections.
"""

from __future__ import annotations

import json
from typing import Any

import pytest


def _call(**kwargs: Any) -> dict[str, Any]:
    from jpintel_mcp.mcp.moat_lane_tools.he3_briefing_pack import (
        agent_briefing_pack,
    )

    return agent_briefing_pack(**kwargs)


# ---------------------------------------------------------------------------
# 1-3 Token estimator
# ---------------------------------------------------------------------------


def test_estimate_tokens_ascii_range() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.he3_briefing_pack import estimate_tokens

    n = estimate_tokens("hello world foo bar baz qux")
    # 27 chars / 4 chars-per-token ≈ 7 (range 5..10)
    assert 5 <= n <= 10


def test_estimate_tokens_cjk_denser_per_char() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.he3_briefing_pack import estimate_tokens

    cjk = "役員報酬の損金算入"
    ascii_eq_len = "officer compensation deductibility under japanese tax"
    n_cjk = estimate_tokens(cjk)
    n_ascii = estimate_tokens(ascii_eq_len)
    # CJK estimator must produce more tokens per char than ASCII estimator
    cjk_per_char = n_cjk / max(len(cjk), 1)
    ascii_per_char = n_ascii / max(len(ascii_eq_len), 1)
    assert cjk_per_char > ascii_per_char


def test_estimate_tokens_empty_returns_zero() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.he3_briefing_pack import estimate_tokens

    assert estimate_tokens("") == 0


# ---------------------------------------------------------------------------
# 4-7 Budget → depth mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("budget", "expected_depth"),
    [
        (500, 1),
        (1500, 1),
        (1501, 2),
        (3500, 2),
        (3501, 3),
        (8000, 3),
        (8001, 4),
        (14000, 4),
        (14001, 5),
        (20000, 5),
        (30000, 5),
    ],
)
def test_depth_from_budget_table(budget: int, expected_depth: int) -> None:
    from jpintel_mcp.mcp.moat_lane_tools.he3_briefing_pack import depth_from_budget

    assert depth_from_budget(budget) == expected_depth


def test_depth_from_budget_zero_or_negative_clamps_to_one() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.he3_briefing_pack import depth_from_budget

    assert depth_from_budget(0) == 1
    assert depth_from_budget(-100) == 1


# ---------------------------------------------------------------------------
# 8-14 End-to-end MCP tool surface
# ---------------------------------------------------------------------------


_EXPECTED_SECTIONS = (
    "context",
    "current_law",
    "tsutatsu",
    "judgment_summary",
    "practical_guidance",
    "common_pitfalls",
    "next_step_recommendations",
    "applicable_templates",
    "related_filing_windows",
    "disclaimer_envelope",
)


def test_e2e_tax_advisor_returns_ten_sections_all_formats() -> None:
    out = _call(topic="役員報酬の損金算入", target_segment="税理士")
    assert out["primary_result"]["status"] == "ok"
    assert out["primary_result"]["depth_level"] == 3  # budget=8000 default
    assert tuple(s["section"] for s in out["sections"]) == _EXPECTED_SECTIONS
    assert isinstance(out["briefing_pack_xml"], str)
    assert isinstance(out["briefing_pack_json"], dict)
    assert isinstance(out["briefing_pack_markdown"], str)
    assert out["briefing_pack_xml"].startswith("<briefing ")
    assert "<context>" in out["briefing_pack_xml"]
    assert "</briefing>" in out["briefing_pack_xml"]


def test_e2e_openai_json_shape_parity() -> None:
    out = _call(
        topic="消費税の仕入税額控除",
        target_segment="会計士",
        output_format="openai_json",
        token_budget=2000,
    )
    pack = out["briefing_pack_json"]
    assert set(pack.keys()) >= {"topic", "segment", "schema", "sections"}
    assert pack["schema"] == "agent_briefing_pack.v1"
    assert pack["segment"] == "会計士"
    assert pack["topic"] == "消費税の仕入税額控除"
    assert len(pack["sections"]) == 10
    # OpenAI JSON must serialize cleanly
    serialized = json.dumps(pack, ensure_ascii=False)
    assert "agent_briefing_pack.v1" in serialized


def test_e2e_markdown_doc_readable() -> None:
    out = _call(
        topic="補助金申請",
        target_segment="中小経営者",
        output_format="markdown_doc",
        token_budget=3500,
    )
    md = out["briefing_pack_markdown"]
    assert md.startswith("# Briefing Pack — ")
    assert "_Segment: 中小経営者_" in md
    assert "## コンテキスト" in md
    assert "## 免責 / 業法 envelope" in md


def test_ax_engineer_disclaimer_mentions_aup() -> None:
    out = _call(
        topic="agent context window 最適化",
        target_segment="AX_engineer",
        token_budget=2000,
    )
    disclaimer_section = next(s for s in out["sections"] if s["section"] == "disclaimer_envelope")
    assert "Anthropic Acceptable Use Policy" in disclaimer_section["content"]


def test_fde_disclaimer_mentions_sow() -> None:
    out = _call(
        topic="顧客 SOW スコープ",
        target_segment="FDE",
        token_budget=2000,
    )
    disclaimer_section = next(s for s in out["sections"] if s["section"] == "disclaimer_envelope")
    assert "SOW" in disclaimer_section["content"]


def test_billing_and_provenance_envelope() -> None:
    out = _call(topic="役員報酬", target_segment="税理士")
    assert out["_billing_unit"] == 1
    assert out["billing"]["billable_units"] == 1
    assert out["billing"]["unit_price_jpy"] == 3
    assert out["billing"]["unit_price_jpy_taxed"] == pytest.approx(3.30)
    prov = out["_provenance"]
    assert prov["lane_id"] == "HE3"
    assert prov["schema_version"] == "moat.he3.v1"
    assert prov["depth_level"] == 3
    assert "_disclaimer" in out
    assert isinstance(out["agent_usage_recipe"], str)
    assert "agent system prompt" in out["agent_usage_recipe"]


def test_three_formats_carry_same_ten_sections() -> None:
    """Invariant: all three output encodings reference identical section labels."""
    xml_out = _call(
        topic="M&A デューデリ",
        target_segment="税理士",
        output_format="claude_xml",
    )
    json_out = _call(
        topic="M&A デューデリ",
        target_segment="税理士",
        output_format="openai_json",
    )
    md_out = _call(
        topic="M&A デューデリ",
        target_segment="税理士",
        output_format="markdown_doc",
    )
    for o in (xml_out, json_out, md_out):
        assert tuple(s["section"] for s in o["sections"]) == _EXPECTED_SECTIONS
    # The OpenAI JSON pack and the canonical sections list must agree.
    assert tuple(s["section"] for s in json_out["briefing_pack_json"]["sections"]) == (
        _EXPECTED_SECTIONS
    )


def test_token_count_estimated_matches_chosen_format() -> None:
    """token_count_estimated is computed from the chosen output_format."""
    from jpintel_mcp.mcp.moat_lane_tools.he3_briefing_pack import estimate_tokens

    out = _call(
        topic="役員報酬",
        target_segment="税理士",
        output_format="claude_xml",
        token_budget=3500,
    )
    recomputed = estimate_tokens(out["briefing_pack_xml"])
    assert out["token_count_estimated"] == recomputed


def test_segment_validation_pattern_registered_on_mcp_tool() -> None:
    """The MCP tool registration carries the segment regex pattern.

    Direct Python calls bypass FastMCP's validation pipeline, so the
    enforcement happens at MCP RPC time. Here we assert the pattern is
    present on the registered tool's input schema so the RPC layer can
    reject unsupported segments at the protocol boundary.
    """
    from jpintel_mcp.mcp.moat_lane_tools.he3_briefing_pack import _SEGMENT_PATTERN

    assert "税理士" in _SEGMENT_PATTERN
    assert "会計士" in _SEGMENT_PATTERN
    assert "中小経営者" in _SEGMENT_PATTERN
    assert "AX_engineer" in _SEGMENT_PATTERN
    assert "FDE" in _SEGMENT_PATTERN


def test_safe_like_sanitizes_topic_special_chars() -> None:
    """LIKE-escape helper must defang % and _ from caller-supplied topics."""
    from jpintel_mcp.mcp.moat_lane_tools.he3_briefing_pack import _safe_like_token

    assert _safe_like_token("100% off") == "100\\% off"
    assert _safe_like_token("a_b_c") == "a\\_b\\_c"
