"""Tests for Moat HE-1 ``agent_full_context`` heavy-output endpoint.

The endpoint composes 10 atomic moat lanes (N1..N9 + ``search_programs``)
into one server-side response. The tests below verify:

* the three depth profiles (1=LITE / 3=NORMAL / 5=FULL) clamp the
  response shape correctly and the resulting payload sizes stay in the
  spec'd bands (~5 KB / ~30 KB / ~100 KB ceiling),
* segment maps both JA 士業 segments and business segments (中小経営者 /
  AX_engineer) without raising,
* ``houjin_bangou=None`` keeps ``houjin_portfolio_gap`` empty while a
  syntactically valid 13-digit houjin still returns a structured
  envelope (live data may be empty depending on DB rows, but the shape
  must hold),
* ``next_call_hints`` is always a list with at most 5 entries and adapts
  to the input shape,
* the ``_disclaimer`` envelope and provenance / billing fields are
  always populated.

All tests are pure-Python — no LLM call, no HTTP fetch.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from jpintel_mcp.mcp.moat_lane_tools.he1_full_context import (
    _agent_full_context_impl,
    _build_next_call_hints,
    _depth_profile,
    _normalize_segment,
)


def _run(query: str, **kwargs: Any) -> dict[str, Any]:
    """Helper - run the async impl synchronously for assertions."""
    return asyncio.run(
        _agent_full_context_impl(
            query=query,
            segment=kwargs.get("segment"),
            houjin_bangou=kwargs.get("houjin_bangou"),
            depth_level=kwargs.get("depth_level", 3),
        )
    )


def _size_kb(payload: dict[str, Any]) -> float:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) / 1024.0


# ---------------------------------------------------------------------------
# Depth profile + segment normalisation unit tests (no DB)
# ---------------------------------------------------------------------------


def test_depth_profile_lite() -> None:
    """LITE (depth=1) skips reasoning chain and caps top-N at 1."""
    profile = _depth_profile(1)
    assert profile["top_programs"] == 1
    assert profile["reasoning_limit"] == 0
    assert profile["include_reasoning_opposing"] == 0


def test_depth_profile_normal_default() -> None:
    """NORMAL (depth=3) is the published default - 5/3/3 caps."""
    profile = _depth_profile(3)
    assert profile["top_programs"] == 5
    assert profile["top_judgments"] == 3
    assert profile["reasoning_limit"] == 3


def test_depth_profile_full() -> None:
    """FULL (depth=5) carries opposing views + full portfolio matrix."""
    profile = _depth_profile(5)
    assert profile["top_programs"] == 10
    assert profile["include_reasoning_opposing"] == 1
    assert profile["portfolio_top_n"] == 50


def test_depth_profile_unknown_falls_back_to_normal() -> None:
    """Values outside {1, 3, 5} fall back to NORMAL (the spec'd default)."""
    profile = _depth_profile(2)
    assert profile["top_programs"] == 5


def test_normalize_segment_ja() -> None:
    """JA 士業 segments map cleanly to N1 JA + N8 EN slug."""
    assert _normalize_segment("税理士") == ("税理士", "tax")
    assert _normalize_segment("会計士") == ("会計士", "audit")
    assert _normalize_segment("行政書士") == ("行政書士", "gyousei")
    assert _normalize_segment("司法書士") == ("司法書士", "shihoshoshi")


def test_normalize_segment_business_segments() -> None:
    """Business segments cannot map to N1; they always pick 'all' there."""
    n1, n8 = _normalize_segment("AX_engineer")
    assert n1 == "all"
    assert n8 == "ax_fde"
    n1b, n8b = _normalize_segment("中小経営者")
    assert n1b == "all"
    assert n8b == "all"


def test_normalize_segment_none_and_unknown() -> None:
    """``None`` / unknown segments fall back to ('all', 'all')."""
    assert _normalize_segment(None) == ("all", "all")
    assert _normalize_segment("alien_segment") == ("all", "all")


# ---------------------------------------------------------------------------
# Hint generator
# ---------------------------------------------------------------------------


def test_next_call_hints_bounded_to_five() -> None:
    """Hints are capped at 5 entries regardless of input flags."""
    hints = _build_next_call_hints(
        query="x",
        segment=None,
        houjin_bangou=None,
        has_programs=True,
        has_portfolio_gap=True,
        has_reasoning=True,
    )
    assert len(hints) <= 5
    # When everything is missing, we should still get at least the
    # "personalize" hint.
    bare = _build_next_call_hints(
        query="x",
        segment=None,
        houjin_bangou=None,
        has_programs=False,
        has_portfolio_gap=False,
        has_reasoning=False,
    )
    assert any(h["action"].startswith("Personalize") for h in bare)


# ---------------------------------------------------------------------------
# End-to-end shape verification (DB-backed; tolerant to empty rows)
# ---------------------------------------------------------------------------


def test_envelope_canonical_fields_present() -> None:
    """Every required envelope field is present on a depth=3 response."""
    res = _run("ものづくり補助金", segment="税理士", depth_level=3)
    expected = {
        "tool_name",
        "schema_version",
        "lane_id",
        "query",
        "resolved_aliases",
        "core_results",
        "reasoning_chain",
        "filing_windows",
        "applicable_artifact_templates",
        "houjin_portfolio_gap",
        "amendment_alerts",
        "segment_view",
        "related_recipes",
        "placeholder_mappings_preview",
        "next_call_hints",
        "billing",
        "_disclaimer",
        "_billing_unit",
        "_citation_envelope",
        "_provenance",
    }
    assert expected.issubset(res.keys())
    assert res["tool_name"] == "agent_full_context"
    assert res["schema_version"] == "moat.he1.v1"
    assert res["lane_id"] == "HE1"
    assert res["billing"] == {"unit": 1, "yen": 3, "depth_level": 3}
    assert "scaffold-only" in res["_disclaimer"].lower() or "士業" in res["_disclaimer"]
    assert res["_provenance"]["no_llm"] is True


def test_depth_level_1_payload_fits_lite_band() -> None:
    """LITE response must stay under ~10 KB (5 KB target with headroom)."""
    res = _run("ものづくり補助金", depth_level=1)
    size = _size_kb(res)
    assert size < 10.0, f"LITE response should be < 10 KB, got {size:.2f} KB"
    assert len(res["core_results"]["programs"]) <= 1
    # reasoning chain is skipped under LITE
    assert res["reasoning_chain"].get("total", 0) == 0


def test_depth_level_3_payload_fits_normal_band() -> None:
    """NORMAL response should be in the 10-50 KB band (30 KB target)."""
    res = _run("ものづくり補助金", segment="税理士", depth_level=3)
    size = _size_kb(res)
    assert 10.0 <= size <= 50.0, f"NORMAL response should be 10-50 KB, got {size:.2f} KB"
    assert len(res["core_results"]["programs"]) <= 5
    assert len(res["applicable_artifact_templates"]) <= 5


def test_depth_level_5_payload_fits_full_band() -> None:
    """FULL response should stay under the ~100 KB ceiling."""
    res = _run("ものづくり補助金", segment="税理士", depth_level=5)
    size = _size_kb(res)
    assert size <= 110.0, f"FULL response must be <= 110 KB, got {size:.2f} KB"
    # FULL surfaces up to 10 programs and full reasoning chain.
    assert len(res["core_results"]["programs"]) <= 10


def test_houjin_bangou_none_skips_portfolio_gap() -> None:
    """Without a houjin_bangou the portfolio_gap field is empty (no surface)."""
    res = _run("インボイス制度", segment="税理士", depth_level=3)
    assert res["houjin_portfolio_gap"] == {}
    # No houjin -> no filing windows either (lane is address-prefix matched).
    assert res["filing_windows"] == []


def test_houjin_bangou_set_returns_structured_envelope() -> None:
    """With a valid houjin_bangou the gap envelope is at least a dict
    (rows may be empty if the test DB has no row for the houjin).
    """
    res = _run(
        "ものづくり補助金",
        segment="税理士",
        houjin_bangou="8010001213708",  # Bookyou株式会社 (operator)
        depth_level=3,
    )
    assert isinstance(res["houjin_portfolio_gap"], dict)
    # filing_windows + alerts may be empty, but must be lists
    assert isinstance(res["filing_windows"], list)
    assert isinstance(res["amendment_alerts"], list)


def test_segment_tax_routes_to_correct_n8_bucket() -> None:
    """Segment '税理士' must surface recipes from the 'tax' N8 segment."""
    res = _run("月次決算", segment="税理士", depth_level=3)
    recipes = res["related_recipes"]
    # Recipe entries should have segment='tax' (or be empty if N8 unavailable).
    for entry in recipes:
        assert entry.get("segment") in {"tax", None}


def test_segment_unknown_falls_back_to_all() -> None:
    """Unknown segments do not raise and fall back to 'all'."""
    res = _run("インボイス", segment="完全に存在しないセグメント", depth_level=3)
    assert isinstance(res["related_recipes"], list)
    assert res["lane_id"] == "HE1"


def test_invalid_query_returns_error_envelope() -> None:
    """Empty / non-string queries return a structured error envelope."""

    async def run_empty() -> dict[str, Any]:
        return await _agent_full_context_impl(
            query="",
            segment=None,
            houjin_bangou=None,
            depth_level=3,
        )

    res = asyncio.run(run_empty())
    assert "error" in res
    assert res["error"]["code"] == "invalid_input"
    assert res["billing"] == {"unit": 1, "yen": 3, "depth_level": 3}


def test_next_call_hints_present_for_anonymous_query() -> None:
    """Anonymous query (no houjin) must surface the personalize hint."""
    res = _run("ものづくり補助金", depth_level=3)
    actions = [h["action"] for h in res["next_call_hints"]]
    assert any("Personalize" in a for a in actions)


def test_mcp_tool_decorator_registered() -> None:
    """The HE-1 tool registers as ``agent_full_context`` on the MCP server."""
    # Triggering an import is enough to register; here we just verify
    # the symbol is callable and named.
    from jpintel_mcp.mcp.moat_lane_tools.he1_full_context import agent_full_context

    fn = getattr(agent_full_context, "fn", agent_full_context)
    name = getattr(agent_full_context, "name", getattr(fn, "__name__", ""))
    assert name == "agent_full_context"


def test_provenance_lists_composition_chain() -> None:
    """The ``_provenance.composition`` field enumerates the composed tools."""
    res = _run("IT導入補助金", depth_level=3)
    provenance = res["_provenance"]
    composition = provenance["composition"]
    assert isinstance(composition, list)
    assert any("moat_n5_synonym.resolve_alias" in c for c in composition)
    assert any("moat_n3_reasoning.walk_reasoning_chain" in c for c in composition)
    assert provenance["no_llm"] is True


@pytest.mark.parametrize("depth", [1, 3, 5])
def test_depth_levels_all_emit_billing_envelope(depth: int) -> None:
    """billing envelope is stable across depths (1 unit per call)."""
    res = _run("ものづくり補助金", depth_level=depth)
    assert res["billing"] == {"unit": 1, "yen": 3, "depth_level": depth}
    assert res["_billing_unit"] == 1
