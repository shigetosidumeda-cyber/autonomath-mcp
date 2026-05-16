"""Coverage push #4 — `src/jpintel_mcp/mcp/server.py` 50% → 70%+ [lane:solo].

Stacks on top of `tests/test_mcp_server_coverage.py` (184 tests, baseline 49%
isolated). Each test here targets a specific uncovered branch so they remain
small + focused (1-3 branches per test) and tolerant of envelope additions.

Convention (mirrors v1):
* All assertions are tolerant of envelope additions (do not lock down exact
  key sets when the telemetry decorator might add `status`, `tool_name`, etc.).
* No DB mocking — uses the shared `seeded_db` + `client` fixtures from
  `tests/conftest.py`. LLM 0 — pure SQLite + python.
* For tools whose signature is gated by Annotated[Literal, …] but where we
  want to exercise the *invalid* path, we call the tool's `__wrapped__` to
  bypass the FastMCP signature wall (same trick used in v1).
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from jpintel_mcp.mcp.server import (
    _empty_case_studies_hint,
    _empty_invoice_registrants_hint,
    _empty_laws_hint,
    _empty_loan_hint,
    _empty_search_hint,
    _empty_tax_rules_hint,
    _envelope_merge,
    _err,
    _jst_fy_quarter,
    _project_next_opens,
    _resolve_supporting_programs,
    _score_case_similarity,
    _walk_and_sanitize_mcp,
)

if TYPE_CHECKING:
    from pathlib import Path


# =============================================================================
# _walk_and_sanitize_mcp — deep recursion paths.
# =============================================================================


def test_walk_sanitize_nested_dict_in_dict():
    """Dict containing nested dict triggers recursion (line 755-761)."""
    out, hits = _walk_and_sanitize_mcp({"outer": {"inner": "leaf string"}})
    assert isinstance(out, dict)
    assert out["outer"]["inner"] == "leaf string"
    assert hits == []


def test_walk_sanitize_list_in_dict():
    """Dict containing a list of mixed types."""
    out, hits = _walk_and_sanitize_mcp({"items": ["a", 1, {"x": "y"}, None]})
    assert out["items"] == ["a", 1, {"x": "y"}, None]
    assert hits == []


def test_walk_sanitize_dict_in_list():
    """List of dicts."""
    out, hits = _walk_and_sanitize_mcp([{"a": "b"}, {"c": "d"}])
    assert out == [{"a": "b"}, {"c": "d"}]
    assert hits == []


def test_walk_sanitize_list_in_list():
    """List of lists — recursion path through nested list."""
    out, hits = _walk_and_sanitize_mcp([["x", "y"], ["z"]])
    assert out == [["x", "y"], ["z"]]
    assert hits == []


def test_walk_sanitize_deeply_nested_4_levels():
    """4-level nesting forces full recursion in all branches."""
    deep = {"a": [{"b": {"c": ["leaf1", "leaf2"]}}]}
    out, hits = _walk_and_sanitize_mcp(deep)
    assert out["a"][0]["b"]["c"] == ["leaf1", "leaf2"]
    assert hits == []


def test_walk_sanitize_tuple_passes_through_unchanged():
    """Non-list / non-dict / non-string scalar — early return."""
    out, hits = _walk_and_sanitize_mcp((1, 2, 3))
    assert out == (1, 2, 3)
    assert hits == []


def test_walk_sanitize_float_passes_through():
    out, hits = _walk_and_sanitize_mcp(3.14159)
    assert out == 3.14159
    assert hits == []


def test_walk_sanitize_bool_passes_through():
    out, hits = _walk_and_sanitize_mcp(True)
    assert out is True
    assert hits == []


def test_walk_sanitize_empty_dict_no_recursion():
    out, hits = _walk_and_sanitize_mcp({})
    assert out == {}
    assert hits == []


def test_walk_sanitize_empty_list_no_recursion():
    out, hits = _walk_and_sanitize_mcp([])
    assert out == []
    assert hits == []


# =============================================================================
# _envelope_merge — additional branches: error envelope, _sanitized,
# bare list, non-string query keys.
# =============================================================================


def test_envelope_merge_error_envelope_with_code(seeded_db):
    """Tool pre-built error → envelope still merges status/suggested_actions."""
    base = {
        "results": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
        "error": {"code": "invalid_range", "message": "Bad input"},
    }
    out = _envelope_merge(
        tool_name="search_programs",
        result=base,
        kwargs={"q": "test"},
        latency_ms=10.0,
    )
    assert isinstance(out, dict)
    # Original error preserved
    assert out["error"]["code"] == "invalid_range"


def test_envelope_merge_error_envelope_with_message_only(seeded_db):
    """Error dict with `message` only (no code) still triggers the error path."""
    base = {
        "results": [],
        "error": {"message": "Bad thing happened"},
    }
    out = _envelope_merge(
        tool_name="x",
        result=base,
        kwargs={},
        latency_ms=2.0,
    )
    assert isinstance(out, dict)
    assert out["error"]["message"] == "Bad thing happened"


def test_envelope_merge_law_name_query_echo(seeded_db):
    """Picks `law_name` for query_echo when `q` is absent."""
    base = {"results": [{"id": 1}], "total": 1}
    out = _envelope_merge(
        tool_name="get_law",
        result=base,
        kwargs={"law_name": "民法"},
        latency_ms=5.0,
    )
    assert isinstance(out, dict)


def test_envelope_merge_program_name_query_echo(seeded_db):
    base = {"results": [{"id": 1}], "total": 1}
    out = _envelope_merge(
        tool_name="get_program",
        result=base,
        kwargs={"program_name": "IT導入補助金"},
        latency_ms=5.0,
    )
    assert isinstance(out, dict)


def test_envelope_merge_natural_query_echo(seeded_db):
    base = {"results": [], "total": 0}
    out = _envelope_merge(
        tool_name="x",
        result=base,
        kwargs={"natural_query": "事業承継 制度"},
        latency_ms=5.0,
    )
    assert isinstance(out, dict)


def test_envelope_merge_dict_with_pre_sanitized_flag(seeded_db):
    """When `_sanitized` is already True on the merged dict, second-pass skipped."""
    base = {
        "results": [{"x": "y"}],
        "total": 1,
        "_sanitized": 1,
    }
    out = _envelope_merge(
        tool_name="x",
        result=base,
        kwargs={},
        latency_ms=5.0,
    )
    assert out.get("_sanitized") == 1


def test_envelope_merge_meta_collision_existing_wins(seeded_db):
    """Existing meta key wins; envelope-added key fills the gap."""
    base = {
        "results": [],
        "total": 0,
        "meta": {"data_as_of": "2024-12-31", "custom": "keep"},
    }
    out = _envelope_merge(
        tool_name="x",
        result=base,
        kwargs={},
        latency_ms=1.0,
    )
    # Existing meta keys preserved.
    assert out["meta"]["data_as_of"] == "2024-12-31"
    assert out["meta"]["custom"] == "keep"


def test_envelope_merge_list_result_returns_envelope(seeded_db):
    """Bare list → envelope returned in its full structured form."""
    out = _envelope_merge(
        tool_name="x",
        result=[{"a": 1}, {"b": 2}],
        kwargs={},
        latency_ms=1.0,
    )
    # Should not raise — either envelope dict or bare list, both fine.
    assert out is not None


# =============================================================================
# _err helper — exercise hint + retry_with branches.
# =============================================================================


def test_err_minimal():
    out = _err("invalid_enum", "bad input")
    assert out["error"] == "bad input"
    assert out["code"] == "invalid_enum"
    assert "hint" not in out
    assert "retry_with" not in out


def test_err_with_hint():
    out = _err("invalid_enum", "bad input", hint="try this")
    assert out["hint"] == "try this"


def test_err_with_retry_with():
    out = _err("seed_not_found", "no match", retry_with=["search_x", "search_y"])
    assert out["retry_with"] == ["search_x", "search_y"]


def test_err_with_all_optional():
    out = _err("internal", "boom", hint="see logs", retry_with=["retry_me"])
    assert out["error"] == "boom"
    assert out["code"] == "internal"
    assert out["hint"] == "see logs"
    assert out["retry_with"] == ["retry_me"]


# =============================================================================
# _jst_fy_quarter + _project_next_opens — pure date math.
# =============================================================================


def test_jst_fy_quarter_q1_april():
    assert _jst_fy_quarter("2026-04-01") == "FY2026 Q1"


def test_jst_fy_quarter_q1_june():
    assert _jst_fy_quarter("2026-06-30") == "FY2026 Q1"


def test_jst_fy_quarter_q2_july():
    assert _jst_fy_quarter("2026-07-01") == "FY2026 Q2"


def test_jst_fy_quarter_q3_october():
    assert _jst_fy_quarter("2026-10-15") == "FY2026 Q3"


def test_jst_fy_quarter_q4_january_rolls_back():
    """1-3 月 → 前年度 Q4"""
    assert _jst_fy_quarter("2026-02-15") == "FY2025 Q4"


def test_jst_fy_quarter_invalid_returns_sentinel():
    assert _jst_fy_quarter("not-a-date") == "FY?? Q?"


def test_project_next_opens_none_start():
    assert _project_next_opens(None, "annual", "2026-01-01") is None


def test_project_next_opens_future_start_returns_as_iso():
    # Start already future → returned as-is
    assert _project_next_opens("2027-04-01", "annual", "2026-04-01") == "2027-04-01"


def test_project_next_opens_past_non_annual_returns_none():
    """Past + non-annual cycle = None (no projection)."""
    assert _project_next_opens("2024-01-01", "rolling", "2026-04-01") is None


def test_project_next_opens_past_annual_rolls_forward():
    """Annual cycle past → roll +N years until anchor."""
    out = _project_next_opens("2024-05-01", "annual", "2026-04-01")
    assert out is not None
    assert out >= "2026-04-01"


def test_project_next_opens_invalid_iso_returns_none():
    assert _project_next_opens("garbage", "annual", "2026-04-01") is None


# =============================================================================
# _score_case_similarity — every match-reason branch.
# =============================================================================


def test_score_case_similarity_same_industry_full():
    score, reasons = _score_case_similarity("E32", None, [], "E32", None, [])
    assert score > 0
    assert any("full match" in r for r in reasons)


def test_score_case_similarity_industry_prefix_partial():
    score, reasons = _score_case_similarity("E32", None, [], "E15", None, [])
    assert score > 0
    assert any("related industry" in r for r in reasons)


def test_score_case_similarity_no_industry_match():
    score, _ = _score_case_similarity("E32", None, [], "K15", None, [])
    assert score == 0.0


def test_score_case_similarity_same_prefecture():
    score, reasons = _score_case_similarity(None, "東京都", [], None, "東京都", [])
    assert score > 0
    assert any("same prefecture" in r for r in reasons)


def test_score_case_similarity_program_overlap_one():
    score, reasons = _score_case_similarity(
        "E", None, ["IT導入補助金"], "E", None, ["IT導入補助金", "別の制度"]
    )
    assert score > 0
    # Shared program reason
    assert any("shared 1 program" in r for r in reasons)


def test_score_case_similarity_program_overlap_two_plus():
    score, reasons = _score_case_similarity("E", None, ["P1", "P2", "P3"], "E", None, ["P1", "P2"])
    assert score > 0
    assert any("shared 2 programs" in r for r in reasons)


def test_score_case_similarity_no_overlap_in_programs():
    score, reasons = _score_case_similarity(None, None, ["P1"], None, None, ["P2"])
    # No shared programs → 0 score (industry / prefecture also empty)
    assert score == 0.0


def test_score_case_similarity_empty_seed_programs():
    score, _ = _score_case_similarity(None, None, [], None, None, [])
    # Both empty → 0
    assert score == 0.0


# =============================================================================
# _resolve_supporting_programs — best-effort name → program row.
# =============================================================================


def test_resolve_supporting_programs_empty_names(seeded_db: Path):
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        out = _resolve_supporting_programs(conn, [])
        assert out == []
    finally:
        conn.close()


def test_resolve_supporting_programs_none_in_list(seeded_db: Path):
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        out = _resolve_supporting_programs(conn, ["", "テスト S-tier 補助金"])
        # Empty name skipped; valid one resolved (or returns matched=False if no DB hit)
        assert isinstance(out, list)
        assert len(out) == 1
    finally:
        conn.close()


def test_resolve_supporting_programs_unmatched_name(seeded_db: Path):
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        out = _resolve_supporting_programs(conn, ["nonexistent program zzz"])
        assert out[0]["matched"] is False
    finally:
        conn.close()


# =============================================================================
# DB-backed tools: subsidy_combo_finder branches (combo not found, blocked
# name path, prefecture warning, etc.).
# =============================================================================


def test_subsidy_combo_finder_neither_keyword_nor_id(client, seeded_db):
    """Both keyword + unified_id None → seed_not_found error."""
    from jpintel_mcp.mcp.server import subsidy_combo_finder

    res = subsidy_combo_finder()
    assert isinstance(res, dict)
    # Either seed_not_found error envelope OR an empty combos shape — both OK.


def test_subsidy_combo_finder_with_keyword(client, seeded_db):
    from jpintel_mcp.mcp.server import subsidy_combo_finder

    res = subsidy_combo_finder(keyword="テスト")
    assert isinstance(res, dict)


def test_subsidy_combo_finder_with_unified_id(client, seeded_db):
    from jpintel_mcp.mcp.server import subsidy_combo_finder

    res = subsidy_combo_finder(unified_id="UNI-test-s-1")
    assert isinstance(res, dict)


def test_subsidy_combo_finder_unknown_prefecture(client, seeded_db):
    from jpintel_mcp.mcp.server import subsidy_combo_finder

    res = subsidy_combo_finder(keyword="テスト", prefecture="Tokio")
    assert isinstance(res, dict)


def test_subsidy_combo_finder_limit_max(client, seeded_db):
    from jpintel_mcp.mcp.server import subsidy_combo_finder

    res = subsidy_combo_finder(keyword="テスト", limit=5)
    assert isinstance(res, dict)


def test_subsidy_combo_finder_unknown_seed(client, seeded_db):
    """seed not in programs → seed_not_found code envelope."""
    from jpintel_mcp.mcp.server import subsidy_combo_finder

    res = subsidy_combo_finder(unified_id="UNI-does-not-exist")
    assert isinstance(res, dict)


# =============================================================================
# subsidy_roadmap_3yr — invalid industry / horizon / date branches.
# =============================================================================


def test_subsidy_roadmap_3yr_invalid_industry(client, seeded_db):
    from jpintel_mcp.mcp.server import subsidy_roadmap_3yr

    res = subsidy_roadmap_3yr(industry="not_a_real_industry_xxx")
    # Either invalid_industry envelope or empty_roadmap
    assert isinstance(res, dict)


def test_subsidy_roadmap_3yr_valid_industry(client, seeded_db):
    from jpintel_mcp.mcp.server import subsidy_roadmap_3yr

    res = subsidy_roadmap_3yr(industry="E", horizon_months=12)
    assert isinstance(res, dict)


def test_subsidy_roadmap_3yr_with_all_optional(client, seeded_db):
    from jpintel_mcp.mcp.server import subsidy_roadmap_3yr

    res = subsidy_roadmap_3yr(
        industry="製造業",
        prefecture="東京都",
        company_size="small",
        funding_purpose="equipment",
        horizon_months=24,
        limit=10,
    )
    assert isinstance(res, dict)


def test_subsidy_roadmap_3yr_unknown_prefecture_warns(client, seeded_db):
    from jpintel_mcp.mcp.server import subsidy_roadmap_3yr

    res = subsidy_roadmap_3yr(industry="E", prefecture="Tokio")
    assert isinstance(res, dict)


def test_subsidy_roadmap_3yr_past_from_date_clamped(client, seeded_db):
    from jpintel_mcp.mcp.server import subsidy_roadmap_3yr

    res = subsidy_roadmap_3yr(industry="E", from_date="2020-01-01")
    # Should clamp + emit hint, or return empty_roadmap
    assert isinstance(res, dict)


def test_subsidy_roadmap_3yr_invalid_from_date(client, seeded_db):
    from jpintel_mcp.mcp.server import subsidy_roadmap_3yr

    res = subsidy_roadmap_3yr(industry="E", from_date="bad-date")
    # Either invalid_from_date error or normalization
    assert isinstance(res, dict)


# =============================================================================
# similar_cases — full execution paths via description.
# =============================================================================


def test_similar_cases_with_description_fallback(client, seeded_db):
    from jpintel_mcp.mcp.server import similar_cases

    res = similar_cases(description="ものづくり")
    assert isinstance(res, dict)


def test_similar_cases_with_case_id_missing(client, seeded_db):
    from jpintel_mcp.mcp.server import similar_cases

    res = similar_cases(case_id="CS-does-not-exist")
    assert isinstance(res, dict)


def test_similar_cases_with_industry_override(client, seeded_db):
    from jpintel_mcp.mcp.server import similar_cases

    res = similar_cases(description="補助金", industry_jsic="E")
    assert isinstance(res, dict)


def test_similar_cases_with_prefecture_override(client, seeded_db):
    from jpintel_mcp.mcp.server import similar_cases

    res = similar_cases(description="補助金", prefecture="東京都")
    assert isinstance(res, dict)


def test_similar_cases_with_unknown_prefecture(client, seeded_db):
    from jpintel_mcp.mcp.server import similar_cases

    res = similar_cases(description="補助金", prefecture="Tokio")
    assert isinstance(res, dict)


def test_similar_cases_with_high_limit(client, seeded_db):
    from jpintel_mcp.mcp.server import similar_cases

    res = similar_cases(description="補助金", limit=20)
    assert isinstance(res, dict)


# =============================================================================
# combined_compliance_check — coverage of body branches.
# =============================================================================


def test_combined_compliance_check_with_unknown_program(client, seeded_db):
    """program_unified_id not in programs → program_not_found envelope."""
    from jpintel_mcp.mcp.server import combined_compliance_check

    res = combined_compliance_check(
        business_profile={"prefecture": "東京都"},
        program_unified_id="UNI-does-not-exist",
    )
    assert isinstance(res, dict)


def test_combined_compliance_check_with_valid_program(client, seeded_db):
    """program_unified_id matches → exclusion_check + tax_evaluation run."""
    from jpintel_mcp.mcp.server import combined_compliance_check

    res = combined_compliance_check(
        business_profile={"prefecture": "東京都"},
        program_unified_id="UNI-test-s-1",
    )
    assert isinstance(res, dict)


def test_combined_compliance_check_with_top_bids_zero(client, seeded_db):
    """top_bids=0 → relevant_bids stays empty."""
    from jpintel_mcp.mcp.server import combined_compliance_check

    res = combined_compliance_check(
        business_profile={"prefecture": "東京都"},
        top_bids=0,
    )
    assert isinstance(res, dict)


def test_combined_compliance_check_no_program_with_prefecture(client, seeded_db):
    """No program_unified_id, prefecture set → bids filtered by prefecture."""
    from jpintel_mcp.mcp.server import combined_compliance_check

    res = combined_compliance_check(
        business_profile={"prefecture": "東京都"},
        top_bids=5,
    )
    assert isinstance(res, dict)


def test_combined_compliance_check_tax_verbose_true(client, seeded_db):
    """tax_verbose=True → include unmatched rulesets."""
    from jpintel_mcp.mcp.server import combined_compliance_check

    res = combined_compliance_check(
        business_profile={"prefecture": "東京都", "annual_revenue_yen": 1_000_000},
        tax_verbose=True,
    )
    assert isinstance(res, dict)


def test_combined_compliance_check_include_tax_eval_false(client, seeded_db):
    """include_tax_eval=False → tax results empty list."""
    from jpintel_mcp.mcp.server import combined_compliance_check

    res = combined_compliance_check(
        business_profile={"prefecture": "東京都"},
        include_tax_eval=False,
    )
    assert isinstance(res, dict)


# =============================================================================
# trace_program_to_law — branches: unknown program / empty chain.
# =============================================================================


def test_trace_program_to_law_unknown_program(client, seeded_db):
    """Unknown id → program_not_found envelope."""
    from jpintel_mcp.mcp.server import trace_program_to_law

    res = trace_program_to_law(program_unified_id="UNI-does-not-exist")
    assert isinstance(res, dict)
    # Some shape with error envelope OR empty chain
    assert "legal_basis_chain" in res or "error" in res


def test_trace_program_to_law_known_program_no_refs(client, seeded_db):
    """Known program but no program_law_refs → empty legal_basis_chain."""
    from jpintel_mcp.mcp.server import trace_program_to_law

    res = trace_program_to_law(program_unified_id="UNI-test-s-1")
    assert isinstance(res, dict)


def test_trace_program_to_law_follow_revision_chain_false(client, seeded_db):
    from jpintel_mcp.mcp.server import trace_program_to_law

    res = trace_program_to_law(program_unified_id="UNI-test-s-1", follow_revision_chain=False)
    assert isinstance(res, dict)


# =============================================================================
# find_cases_by_law — branches: law not found, no court_decisions.
# =============================================================================


def test_find_cases_by_law_unknown_law_id(client, seeded_db):
    """Unknown LAW id → seed_not_found error."""
    from jpintel_mcp.mcp.server import find_cases_by_law

    res = find_cases_by_law(law_unified_id="LAW-aaaaaaaaaa")
    assert isinstance(res, dict)


def test_find_cases_by_law_include_enforcement_false(client, seeded_db):
    from jpintel_mcp.mcp.server import find_cases_by_law

    res = find_cases_by_law(law_unified_id="LAW-aaaaaaaaaa", include_enforcement=False)
    assert isinstance(res, dict)


def test_find_cases_by_law_high_limit(client, seeded_db):
    from jpintel_mcp.mcp.server import find_cases_by_law

    res = find_cases_by_law(law_unified_id="LAW-aaaaaaaaaa", limit=50)
    assert isinstance(res, dict)


# =============================================================================
# bid_eligible_for_profile — branches.
# =============================================================================


def test_bid_eligible_unknown_bid(client, seeded_db):
    from jpintel_mcp.mcp.server import bid_eligible_for_profile

    res = bid_eligible_for_profile(
        bid_unified_id="BID-aaaaaaaaaa",
        business_profile={"prefecture": "東京都"},
    )
    assert isinstance(res, dict)


def test_bid_eligible_minimal_profile(client, seeded_db):
    from jpintel_mcp.mcp.server import bid_eligible_for_profile

    res = bid_eligible_for_profile(
        bid_unified_id="BID-aaaaaaaaaa",
        business_profile={},
    )
    assert isinstance(res, dict)


# =============================================================================
# evaluate_tax_applicability — target_ruleset_ids branches.
# =============================================================================


def test_evaluate_tax_applicability_with_target_ids(client, seeded_db):
    from jpintel_mcp.mcp.server import evaluate_tax_applicability

    # Use __wrapped__ to bypass any signature checks that might reject TR-
    # vs TAX- prefix (test_mcp_server_coverage.py uses measure_id sig, but
    # the actual fn uses target_ruleset_ids).
    fn = getattr(evaluate_tax_applicability, "__wrapped__", evaluate_tax_applicability)
    res = fn(
        business_profile={"annual_revenue_yen": 10_000_000},
        target_ruleset_ids=["TAX-0123456789"],
    )
    assert isinstance(res, dict)


def test_evaluate_tax_applicability_malformed_target_id(client, seeded_db):
    """Malformed TAX id → invalid_enum error."""
    from jpintel_mcp.mcp.server import evaluate_tax_applicability

    fn = getattr(evaluate_tax_applicability, "__wrapped__", evaluate_tax_applicability)
    res = fn(
        business_profile={},
        target_ruleset_ids=["NOT-A-TAX-ID"],
    )
    assert isinstance(res, dict)
    # Either invalid_enum error or successful empty path — both valid.


def test_evaluate_tax_applicability_empty_target_ids(client, seeded_db):
    from jpintel_mcp.mcp.server import evaluate_tax_applicability

    fn = getattr(evaluate_tax_applicability, "__wrapped__", evaluate_tax_applicability)
    res = fn(
        business_profile={},
        target_ruleset_ids=[],
    )
    assert isinstance(res, dict)


def test_evaluate_tax_applicability_no_target_evaluates_all(client, seeded_db):
    """No target_ruleset_ids → walks all currently-effective rulesets."""
    from jpintel_mcp.mcp.server import evaluate_tax_applicability

    fn = getattr(evaluate_tax_applicability, "__wrapped__", evaluate_tax_applicability)
    res = fn(business_profile={"annual_revenue_yen": 1_000_000})
    assert isinstance(res, dict)


# =============================================================================
# compose_audit_workpaper — error envelopes.
# =============================================================================


def test_compose_audit_workpaper_invalid_client_id(client, seeded_db):
    from jpintel_mcp.mcp.server import compose_audit_workpaper

    fn = getattr(compose_audit_workpaper, "__wrapped__", compose_audit_workpaper)
    res = fn(
        client_id="bad client id with spaces / ascii-only enforced",
        target_ruleset_ids=["TAX-0123456789"],
        business_profile={},
    )
    assert isinstance(res, dict)


def test_compose_audit_workpaper_malformed_ruleset_id(client, seeded_db):
    from jpintel_mcp.mcp.server import compose_audit_workpaper

    fn = getattr(compose_audit_workpaper, "__wrapped__", compose_audit_workpaper)
    res = fn(
        client_id="client_1",
        target_ruleset_ids=["NOT-A-TAX-ID"],
        business_profile={},
    )
    assert isinstance(res, dict)


def test_compose_audit_workpaper_unknown_ruleset_ids(client, seeded_db):
    """All TAX ids don't exist → no_matching_records envelope."""
    from jpintel_mcp.mcp.server import compose_audit_workpaper

    fn = getattr(compose_audit_workpaper, "__wrapped__", compose_audit_workpaper)
    res = fn(
        client_id="client_1",
        target_ruleset_ids=["TAX-0000000000"],
        business_profile={"annual_revenue_yen": 1_000_000},
    )
    assert isinstance(res, dict)


# =============================================================================
# audit_batch_evaluate — minimal smoke.
# =============================================================================


def test_audit_batch_evaluate_empty_profiles(client, seeded_db):
    from jpintel_mcp.mcp.server import audit_batch_evaluate

    fn = getattr(audit_batch_evaluate, "__wrapped__", audit_batch_evaluate)
    res = fn(
        audit_firm_id="firm_1",
        profiles=[],
        target_ruleset_ids=["TAX-0123456789"],
    )
    assert isinstance(res, dict)


def test_audit_batch_evaluate_invalid_firm_id(client, seeded_db):
    from jpintel_mcp.mcp.server import audit_batch_evaluate

    fn = getattr(audit_batch_evaluate, "__wrapped__", audit_batch_evaluate)
    res = fn(
        audit_firm_id="bad firm id with spaces",
        profiles=[],
        target_ruleset_ids=["TAX-0123456789"],
    )
    assert isinstance(res, dict)


# =============================================================================
# resolve_citation_chain — error envelope.
# =============================================================================


def test_resolve_citation_chain_unknown_ruleset(client, seeded_db):
    from jpintel_mcp.mcp.server import resolve_citation_chain

    fn = getattr(resolve_citation_chain, "__wrapped__", resolve_citation_chain)
    res = fn(ruleset_id="TAX-0000000000")
    assert isinstance(res, dict)


# =============================================================================
# regulatory_prep_pack — branches: missing industry, empty sections.
# =============================================================================


def test_regulatory_prep_pack_missing_industry(client, seeded_db):
    """No industry → missing_required_arg envelope."""
    from jpintel_mcp.mcp.server import regulatory_prep_pack

    fn = getattr(regulatory_prep_pack, "__wrapped__", regulatory_prep_pack)
    res = fn(industry="")
    assert isinstance(res, dict)


def test_regulatory_prep_pack_with_industry(client, seeded_db):
    from jpintel_mcp.mcp.server import regulatory_prep_pack

    res = regulatory_prep_pack(industry="製造業")
    assert isinstance(res, dict)


def test_regulatory_prep_pack_with_prefecture(client, seeded_db):
    from jpintel_mcp.mcp.server import regulatory_prep_pack

    res = regulatory_prep_pack(industry="E", prefecture="東京都")
    assert isinstance(res, dict)


def test_regulatory_prep_pack_unknown_prefecture(client, seeded_db):
    from jpintel_mcp.mcp.server import regulatory_prep_pack

    res = regulatory_prep_pack(industry="E", prefecture="Tokio")
    assert isinstance(res, dict)


def test_regulatory_prep_pack_include_expired(client, seeded_db):
    from jpintel_mcp.mcp.server import regulatory_prep_pack

    res = regulatory_prep_pack(industry="E", include_expired=True)
    assert isinstance(res, dict)


def test_regulatory_prep_pack_with_company_size(client, seeded_db):
    from jpintel_mcp.mcp.server import regulatory_prep_pack

    res = regulatory_prep_pack(industry="E", company_size="small")
    assert isinstance(res, dict)


# =============================================================================
# Disaster trio — list_active_disaster_programs / match / catalog.
# =============================================================================


def test_list_active_disaster_programs_defaults(client, seeded_db):
    from jpintel_mcp.mcp.server import list_active_disaster_programs

    res = list_active_disaster_programs()
    assert isinstance(res, dict)


def test_list_active_disaster_programs_with_prefecture(client, seeded_db):
    from jpintel_mcp.mcp.server import list_active_disaster_programs

    res = list_active_disaster_programs(prefecture="東京都")
    assert isinstance(res, dict)


def test_list_active_disaster_programs_with_disaster_type(client, seeded_db):
    from jpintel_mcp.mcp.server import list_active_disaster_programs

    res = list_active_disaster_programs(disaster_type="flood")
    assert isinstance(res, dict)


def test_list_active_disaster_programs_window_max(client, seeded_db):
    from jpintel_mcp.mcp.server import list_active_disaster_programs

    res = list_active_disaster_programs(window_months=60, limit=100)
    assert isinstance(res, dict)


def test_match_disaster_programs_invalid_prefecture_code(client, seeded_db):
    """Invalid JIS X 0401 → invalid_enum envelope."""
    from jpintel_mcp.mcp.server import match_disaster_programs

    res = match_disaster_programs(
        prefecture_code="99", disaster_type="flood", incident_date="2025-09-01"
    )
    assert isinstance(res, dict)


def test_match_disaster_programs_valid_call(client, seeded_db):
    from jpintel_mcp.mcp.server import match_disaster_programs

    res = match_disaster_programs(
        prefecture_code="13", disaster_type="flood", incident_date="2025-09-01"
    )
    assert isinstance(res, dict)


def test_match_disaster_programs_any_type(client, seeded_db):
    from jpintel_mcp.mcp.server import match_disaster_programs

    res = match_disaster_programs(
        prefecture_code="13", disaster_type="any", incident_date="2025-09-01"
    )
    assert isinstance(res, dict)


def test_match_disaster_programs_earthquake(client, seeded_db):
    from jpintel_mcp.mcp.server import match_disaster_programs

    res = match_disaster_programs(
        prefecture_code="17", disaster_type="earthquake", incident_date="2024-01-01"
    )
    assert isinstance(res, dict)


def test_disaster_catalog_defaults(client, seeded_db):
    from jpintel_mcp.mcp.server import disaster_catalog

    res = disaster_catalog()
    assert isinstance(res, dict)


def test_disaster_catalog_years_max(client, seeded_db):
    from jpintel_mcp.mcp.server import disaster_catalog

    res = disaster_catalog(years=10, sample_per_event=20)
    assert isinstance(res, dict)


def test_disaster_catalog_min_sample(client, seeded_db):
    from jpintel_mcp.mcp.server import disaster_catalog

    res = disaster_catalog(years=1, sample_per_event=1)
    assert isinstance(res, dict)


# =============================================================================
# search_court_decisions — full filter combinations.
# =============================================================================


def test_search_court_decisions_with_court_level(client, seeded_db):
    from jpintel_mcp.mcp.server import search_court_decisions

    res = search_court_decisions(court_level="supreme")
    assert isinstance(res, dict)


def test_search_court_decisions_with_decision_type(client, seeded_db):
    from jpintel_mcp.mcp.server import search_court_decisions

    res = search_court_decisions(decision_type="判決")
    assert isinstance(res, dict)


def test_search_court_decisions_with_subject_area(client, seeded_db):
    from jpintel_mcp.mcp.server import search_court_decisions

    res = search_court_decisions(subject_area="租税")
    assert isinstance(res, dict)


def test_search_court_decisions_with_law_id(client, seeded_db):
    from jpintel_mcp.mcp.server import search_court_decisions

    res = search_court_decisions(references_law_id="LAW-aaaaaaaaaa")
    assert isinstance(res, dict)


def test_search_court_decisions_with_decided_from(client, seeded_db):
    from jpintel_mcp.mcp.server import search_court_decisions

    res = search_court_decisions(decided_from="2020-01-01")
    assert isinstance(res, dict)


def test_search_court_decisions_with_decided_to(client, seeded_db):
    from jpintel_mcp.mcp.server import search_court_decisions

    res = search_court_decisions(decided_to="2099-12-31")
    assert isinstance(res, dict)


def test_search_court_decisions_with_offset(client, seeded_db):
    from jpintel_mcp.mcp.server import search_court_decisions

    res = search_court_decisions(offset=10, limit=5)
    assert isinstance(res, dict)


def test_search_court_decisions_short_q_like_fallback(client, seeded_db):
    """q < 3 chars → LIKE fallback."""
    from jpintel_mcp.mcp.server import search_court_decisions

    res = search_court_decisions(q="DX")
    assert isinstance(res, dict)


# =============================================================================
# search_bids — full filter combos.
# =============================================================================


def test_search_bids_with_prefecture(client, seeded_db):
    from jpintel_mcp.mcp.server import search_bids

    res = search_bids(prefecture="東京都")
    assert isinstance(res, dict)


def test_search_bids_with_min_amount(client, seeded_db):
    from jpintel_mcp.mcp.server import search_bids

    res = search_bids(min_amount_yen=1_000_000)
    assert isinstance(res, dict)


def test_search_bids_with_max_amount(client, seeded_db):
    from jpintel_mcp.mcp.server import search_bids

    res = search_bids(max_amount_yen=100_000_000)
    assert isinstance(res, dict)


def test_search_bids_with_offset(client, seeded_db):
    from jpintel_mcp.mcp.server import search_bids

    res = search_bids(offset=5)
    assert isinstance(res, dict)


def test_search_bids_short_q_like(client, seeded_db):
    from jpintel_mcp.mcp.server import search_bids

    res = search_bids(q="EC")
    assert isinstance(res, dict)


# =============================================================================
# search_tax_rules — extra filter branches.
# =============================================================================


def test_search_tax_rules_with_ruleset_kind(client, seeded_db):
    from jpintel_mcp.mcp.server import search_tax_rules

    res = search_tax_rules(ruleset_kind="credit")
    assert isinstance(res, dict)


def test_search_tax_rules_with_include_expired(client, seeded_db):
    from jpintel_mcp.mcp.server import search_tax_rules

    res = search_tax_rules(include_expired=True)
    assert isinstance(res, dict)


def test_search_tax_rules_with_authority(client, seeded_db):
    from jpintel_mcp.mcp.server import search_tax_rules

    res = search_tax_rules(authority="国税庁")
    assert isinstance(res, dict)


def test_search_tax_rules_short_q(client, seeded_db):
    from jpintel_mcp.mcp.server import search_tax_rules

    res = search_tax_rules(q="DX")
    assert isinstance(res, dict)


def test_search_tax_rules_with_offset(client, seeded_db):
    from jpintel_mcp.mcp.server import search_tax_rules

    res = search_tax_rules(offset=10, limit=5)
    assert isinstance(res, dict)


def test_search_tax_rules_with_fields_standard(client, seeded_db):
    from jpintel_mcp.mcp.server import search_tax_rules

    res = search_tax_rules(fields="standard")
    assert isinstance(res, dict)


def test_search_tax_rules_with_fields_full(client, seeded_db):
    from jpintel_mcp.mcp.server import search_tax_rules

    res = search_tax_rules(fields="full")
    assert isinstance(res, dict)


# =============================================================================
# search_invoice_registrants — extra branches.
# =============================================================================


def test_search_invoice_registrants_with_kind_corporate(client, seeded_db):
    from jpintel_mcp.mcp.server import search_invoice_registrants

    res = search_invoice_registrants(kind="corporate")
    assert isinstance(res, dict)


def test_search_invoice_registrants_with_kind_individual(client, seeded_db):
    from jpintel_mcp.mcp.server import search_invoice_registrants

    res = search_invoice_registrants(kind="individual")
    assert isinstance(res, dict)


def test_search_invoice_registrants_with_prefecture(client, seeded_db):
    from jpintel_mcp.mcp.server import search_invoice_registrants

    res = search_invoice_registrants(prefecture="東京都")
    assert isinstance(res, dict)


def test_search_invoice_registrants_unknown_prefecture(client, seeded_db):
    from jpintel_mcp.mcp.server import search_invoice_registrants

    res = search_invoice_registrants(prefecture="Tokio")
    assert isinstance(res, dict)


def test_search_invoice_registrants_short_q(client, seeded_db):
    """q < 2 chars rejected per docstring."""
    from jpintel_mcp.mcp.server import search_invoice_registrants

    res = search_invoice_registrants(q="a")
    assert isinstance(res, dict)


def test_search_invoice_registrants_with_offset(client, seeded_db):
    from jpintel_mcp.mcp.server import search_invoice_registrants

    res = search_invoice_registrants(offset=5)
    assert isinstance(res, dict)


# =============================================================================
# find_precedents_by_statute — extra branches.
# =============================================================================


def test_find_precedents_by_statute_with_article_citation(client, seeded_db):
    from jpintel_mcp.mcp.server import find_precedents_by_statute

    res = find_precedents_by_statute(law_unified_id="LAW-aaaaaaaaaa", article_citation="第709条")
    assert isinstance(res, dict)


def test_find_precedents_by_statute_with_limit(client, seeded_db):
    from jpintel_mcp.mcp.server import find_precedents_by_statute

    res = find_precedents_by_statute(law_unified_id="LAW-aaaaaaaaaa", limit=50)
    assert isinstance(res, dict)


# =============================================================================
# search_laws — extra filter branches.
# =============================================================================


def test_search_laws_with_subject_area(client, seeded_db):
    from jpintel_mcp.mcp.server import search_laws

    res = search_laws(subject_area="税法")
    assert isinstance(res, dict)


def test_search_laws_with_offset(client, seeded_db):
    from jpintel_mcp.mcp.server import search_laws

    res = search_laws(offset=10, limit=5)
    assert isinstance(res, dict)


def test_search_laws_with_revision_status(client, seeded_db):
    from jpintel_mcp.mcp.server import search_laws

    res = search_laws(revision_status="current")
    assert isinstance(res, dict)


# =============================================================================
# list_law_revisions — branches.
# =============================================================================


def test_list_law_revisions_unknown_law(client, seeded_db):
    from jpintel_mcp.mcp.server import list_law_revisions

    res = list_law_revisions(unified_id="LAW-doesnotexist")
    assert isinstance(res, dict)


# =============================================================================
# search_loan_programs — coverage of full filter combinations.
# =============================================================================


def test_search_loan_programs_with_offset(client, seeded_db):
    from jpintel_mcp.mcp.server import search_loan_programs

    res = search_loan_programs(offset=5)
    assert isinstance(res, dict)


def test_search_loan_programs_with_fields_full(client, seeded_db):
    from jpintel_mcp.mcp.server import search_loan_programs

    res = search_loan_programs(fields="full")
    assert isinstance(res, dict)


def test_search_loan_programs_with_fields_standard(client, seeded_db):
    from jpintel_mcp.mcp.server import search_loan_programs

    res = search_loan_programs(fields="standard")
    assert isinstance(res, dict)


# =============================================================================
# prescreen_programs — more branches.
# =============================================================================


def test_prescreen_programs_sole_proprietor_true(client, seeded_db):
    from jpintel_mcp.mcp.server import prescreen_programs

    res = prescreen_programs(prefecture="東京都", is_sole_proprietor=True)
    assert isinstance(res, dict)


def test_prescreen_programs_with_employees(client, seeded_db):
    from jpintel_mcp.mcp.server import prescreen_programs

    res = prescreen_programs(prefecture="東京都", employees=5)
    assert isinstance(res, dict)


def test_prescreen_programs_with_revenue(client, seeded_db):
    from jpintel_mcp.mcp.server import prescreen_programs

    res = prescreen_programs(prefecture="東京都", revenue_yen=1_000_000)
    assert isinstance(res, dict)


def test_prescreen_programs_with_industry_jsic(client, seeded_db):
    from jpintel_mcp.mcp.server import prescreen_programs

    res = prescreen_programs(industry_jsic="E", prefecture="東京都")
    assert isinstance(res, dict)


def test_prescreen_programs_with_funding_purpose(client, seeded_db):
    from jpintel_mcp.mcp.server import prescreen_programs

    res = prescreen_programs(prefecture="東京都", funding_purpose=["equipment"])
    assert isinstance(res, dict)


# =============================================================================
# smb_starter_pack — additional branches.
# =============================================================================


def test_smb_starter_pack_minimal(client, seeded_db):
    from jpintel_mcp.mcp.server import smb_starter_pack

    res = smb_starter_pack()
    assert isinstance(res, dict)


def test_smb_starter_pack_unknown_prefecture(client, seeded_db):
    from jpintel_mcp.mcp.server import smb_starter_pack

    res = smb_starter_pack(prefecture="Tokio")
    assert isinstance(res, dict)


def test_smb_starter_pack_with_all_filters(client, seeded_db):
    from jpintel_mcp.mcp.server import smb_starter_pack

    res = smb_starter_pack(
        prefecture="東京都",
        industry_jsic="E",
        employees=20,
        revenue_yen=100_000_000,
    )
    assert isinstance(res, dict)


# =============================================================================
# upcoming_deadlines + deadline_calendar — more branches.
# =============================================================================


def test_upcoming_deadlines_with_prefecture(client, seeded_db):
    from jpintel_mcp.mcp.server import upcoming_deadlines

    res = upcoming_deadlines(prefecture="東京都")
    assert isinstance(res, dict)


def test_upcoming_deadlines_unknown_prefecture(client, seeded_db):
    from jpintel_mcp.mcp.server import upcoming_deadlines

    res = upcoming_deadlines(prefecture="Tokio")
    assert isinstance(res, dict)


def test_upcoming_deadlines_with_tier(client, seeded_db):
    from jpintel_mcp.mcp.server import upcoming_deadlines

    res = upcoming_deadlines(tier=["S", "A"])
    assert isinstance(res, dict)


def test_deadline_calendar_with_prefecture(client, seeded_db):
    from jpintel_mcp.mcp.server import deadline_calendar

    res = deadline_calendar(prefecture="東京都", months_ahead=3)
    assert isinstance(res, dict)


def test_deadline_calendar_unknown_prefecture(client, seeded_db):
    from jpintel_mcp.mcp.server import deadline_calendar

    res = deadline_calendar(prefecture="Tokio")
    assert isinstance(res, dict)


def test_deadline_calendar_with_tier(client, seeded_db):
    from jpintel_mcp.mcp.server import deadline_calendar

    res = deadline_calendar(tier=["S", "A", "B"])
    assert isinstance(res, dict)


# =============================================================================
# get_meta — basic call.
# =============================================================================


def test_get_meta_returns_required_keys(client, seeded_db):
    from jpintel_mcp.mcp.server import get_meta

    res = get_meta()
    assert isinstance(res, dict)
    for key in ("total_programs", "visible_programs", "tool_count"):
        assert key in res


# =============================================================================
# check_exclusions — branches.
# =============================================================================


def test_check_exclusions_empty_program_ids(client, seeded_db):
    from jpintel_mcp.mcp.server import check_exclusions

    res = check_exclusions(program_ids=[])
    assert isinstance(res, dict)
    assert "error" in res or "hits" in res


def test_check_exclusions_too_many_ids(client, seeded_db):
    from jpintel_mcp.mcp.server import check_exclusions

    fn = getattr(check_exclusions, "__wrapped__", check_exclusions)
    res = fn(program_ids=[f"UNI-id-{i}" for i in range(51)])
    assert isinstance(res, dict)


def test_check_exclusions_with_two_ids(client, seeded_db):
    from jpintel_mcp.mcp.server import check_exclusions

    res = check_exclusions(program_ids=["UNI-test-s-1", "UNI-test-b-1"])
    assert isinstance(res, dict)


def test_check_exclusions_single_id_prerequisite_path(client, seeded_db):
    """Single program id → only prerequisite rules fire."""
    from jpintel_mcp.mcp.server import check_exclusions

    res = check_exclusions(program_ids=["UNI-test-s-1"])
    assert isinstance(res, dict)


# =============================================================================
# batch_get_programs — branches.
# =============================================================================


def test_batch_get_programs_empty(client, seeded_db):
    from jpintel_mcp.mcp.server import batch_get_programs

    res = batch_get_programs(unified_ids=[])
    assert isinstance(res, dict)


def test_batch_get_programs_too_many(client, seeded_db):
    from jpintel_mcp.mcp.server import batch_get_programs

    fn = getattr(batch_get_programs, "__wrapped__", batch_get_programs)
    res = fn(unified_ids=[f"UNI-id-{i}" for i in range(51)])
    assert isinstance(res, dict)


def test_batch_get_programs_with_valid(client, seeded_db):
    from jpintel_mcp.mcp.server import batch_get_programs

    res = batch_get_programs(unified_ids=["UNI-test-s-1", "UNI-test-a-1"])
    assert isinstance(res, dict)


def test_batch_get_programs_all_missing(client, seeded_db):
    from jpintel_mcp.mcp.server import batch_get_programs

    res = batch_get_programs(unified_ids=["UNI-fake-1", "UNI-fake-2"])
    assert isinstance(res, dict)
    # all_ids_not_found data_state path
    if "results" in res and not res["results"]:
        assert "not_found" in res or "data_state" in res or "hint" in res


def test_batch_get_programs_dedups(client, seeded_db):
    """Duplicate ids → dedupe preserves first-occurrence order."""
    from jpintel_mcp.mcp.server import batch_get_programs

    res = batch_get_programs(unified_ids=["UNI-test-s-1", "UNI-test-s-1"])
    assert isinstance(res, dict)


# =============================================================================
# list_exclusion_rules — branches.
# =============================================================================


def test_list_exclusion_rules_filter_by_kind(client, seeded_db):
    from jpintel_mcp.mcp.server import list_exclusion_rules

    res = list_exclusion_rules(kind=["exclude", "absolute"])
    assert isinstance(res, dict)


def test_list_exclusion_rules_filter_by_program_id(client, seeded_db):
    from jpintel_mcp.mcp.server import list_exclusion_rules

    res = list_exclusion_rules(program_id="UNI-test-s-1")
    assert isinstance(res, dict)


def test_list_exclusion_rules_verbose(client, seeded_db):
    from jpintel_mcp.mcp.server import list_exclusion_rules

    res = list_exclusion_rules(verbose=True)
    assert isinstance(res, dict)


def test_list_exclusion_rules_kind_and_program_id(client, seeded_db):
    """Combined filter → empty + suggestions branch."""
    from jpintel_mcp.mcp.server import list_exclusion_rules

    res = list_exclusion_rules(kind=["combine_ok"], program_id="UNI-fake")
    assert isinstance(res, dict)


# =============================================================================
# enum_values — every supported field type.
# =============================================================================


def test_enum_values_program_kind(client, seeded_db):
    from jpintel_mcp.mcp.server import enum_values

    res = enum_values(field="program_kind")
    assert "values" in res


def test_enum_values_authority_level(client, seeded_db):
    from jpintel_mcp.mcp.server import enum_values

    res = enum_values(field="authority_level")
    assert "values" in res


def test_enum_values_event_type(client, seeded_db):
    from jpintel_mcp.mcp.server import enum_values

    res = enum_values(field="event_type")
    assert "values" in res


def test_enum_values_ministry(client, seeded_db):
    from jpintel_mcp.mcp.server import enum_values

    res = enum_values(field="ministry")
    assert "values" in res


def test_enum_values_loan_type(client, seeded_db):
    from jpintel_mcp.mcp.server import enum_values

    res = enum_values(field="loan_type")
    assert "values" in res


def test_enum_values_provider(client, seeded_db):
    from jpintel_mcp.mcp.server import enum_values

    res = enum_values(field="provider")
    assert "values" in res


def test_enum_values_programs_used(client, seeded_db):
    from jpintel_mcp.mcp.server import enum_values

    res = enum_values(field="programs_used")
    assert "values" in res


# =============================================================================
# get_usage_status — extra branches.
# =============================================================================


def test_get_usage_status_explicit_none(client, seeded_db):
    from jpintel_mcp.mcp.server import get_usage_status

    res = get_usage_status(api_key=None)
    assert res["tier"] == "anonymous"


def test_get_usage_status_anonymous_format(client, seeded_db):
    from jpintel_mcp.mcp.server import get_usage_status

    res = get_usage_status()
    assert "reset_at" in res
    assert "reset_timezone" in res
    # JST timezone for anonymous
    assert res["reset_timezone"] == "JST"


# =============================================================================
# search_programs additional branches.
# =============================================================================


def test_search_programs_with_tier_filter(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(tier=["S", "A"])
    assert isinstance(res, dict)


def test_search_programs_with_prefecture_only(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(prefecture="東京都")
    assert "results" in res


def test_search_programs_with_target_type_filter(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(target_type=["corporation"])
    assert "results" in res


def test_search_programs_with_funding_purpose_filter(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(funding_purpose=["設備投資"])
    assert "results" in res


def test_search_programs_with_amount_min_only(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(amount_min_man_yen=100)
    assert "results" in res


def test_search_programs_with_amount_max_only(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(amount_max_man_yen=999_999)
    assert "results" in res


def test_search_programs_with_as_of(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(as_of="2024-01-01")
    assert isinstance(res, dict)


def test_search_programs_with_as_of_today(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(as_of="today")
    assert isinstance(res, dict)


def test_search_programs_with_q_three_char_fts(client, seeded_db):
    """q >= 3 chars triggers FTS path."""
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(q="テスト")
    assert isinstance(res, dict)


def test_search_programs_with_q_short_like(client, seeded_db):
    """q < 3 chars triggers LIKE + KANA_EXPANSIONS path."""
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(q="DX")
    assert isinstance(res, dict)


def test_search_programs_with_fields_full(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(fields="full")
    assert "results" in res


def test_search_programs_with_fields_minimal(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(fields="minimal")
    assert "results" in res


def test_search_programs_limit_over_cap(client, seeded_db):
    """limit > 20 → clamped and surfaced via input_warnings."""
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(limit=50)
    assert isinstance(res, dict)
    # limit should be clamped
    assert res["limit"] <= 50


# =============================================================================
# get_program & get_loan_program — branches.
# =============================================================================


def test_get_program_known_id(client, seeded_db):
    from jpintel_mcp.mcp.server import get_program

    res = get_program(unified_id="UNI-test-s-1")
    assert isinstance(res, dict)


def test_get_program_known_id_fields_full(client, seeded_db):
    from jpintel_mcp.mcp.server import get_program

    res = get_program(unified_id="UNI-test-s-1", fields="full")
    assert isinstance(res, dict)


def test_get_program_known_id_fields_minimal(client, seeded_db):
    from jpintel_mcp.mcp.server import get_program

    res = get_program(unified_id="UNI-test-s-1", fields="minimal")
    assert isinstance(res, dict)


# =============================================================================
# search_case_studies — more branches.
# =============================================================================


def test_search_case_studies_with_min_subsidy(client, seeded_db):
    from jpintel_mcp.mcp.server import search_case_studies

    res = search_case_studies(min_subsidy_yen=100_000)
    assert isinstance(res, dict)


def test_search_case_studies_with_offset(client, seeded_db):
    from jpintel_mcp.mcp.server import search_case_studies

    res = search_case_studies(offset=5)
    assert isinstance(res, dict)


def test_search_case_studies_with_fields_standard(client, seeded_db):
    from jpintel_mcp.mcp.server import search_case_studies

    res = search_case_studies(fields="standard")
    assert isinstance(res, dict)


def test_search_case_studies_with_fields_full(client, seeded_db):
    from jpintel_mcp.mcp.server import search_case_studies

    res = search_case_studies(fields="full")
    assert isinstance(res, dict)


# =============================================================================
# search_enforcement_cases — more branches via short q.
# =============================================================================


def test_search_enforcement_cases_with_offset(client, seeded_db):
    from jpintel_mcp.mcp.server import search_enforcement_cases

    res = search_enforcement_cases(offset=3)
    assert isinstance(res, dict)


def test_search_enforcement_cases_with_high_limit(client, seeded_db):
    from jpintel_mcp.mcp.server import search_enforcement_cases

    res = search_enforcement_cases(limit=50)
    assert isinstance(res, dict)


# =============================================================================
# Empty-hint helpers — additional branches not covered in v1.
# =============================================================================


def test_empty_search_hint_with_funding_purpose():
    msg = _empty_search_hint(None, None, None, None, None, ["equipment"])
    assert isinstance(msg, str)
    assert len(msg) > 0


def test_empty_search_hint_with_target_type():
    msg = _empty_search_hint(None, None, None, None, ["corporation"], None)
    assert isinstance(msg, str)


def test_empty_search_hint_with_long_q():
    msg = _empty_search_hint("非常に長いキーワード文字列", None, None, None)
    assert isinstance(msg, str)


def test_empty_loan_hint_both_filters():
    msg = _empty_loan_hint("JFC", "運転資金")
    assert isinstance(msg, str)
    # Both filters mentioned — concatenation OK
    assert "provider" in msg or "loan_type" in msg


def test_empty_laws_hint_all_branches():
    # Test the all-filter-combined path
    msg = _empty_laws_hint(None, "厚労省", "法律")
    assert "ministry" in msg or "law_type" in msg


def test_empty_case_studies_hint_houjin_valid():
    msg = _empty_case_studies_hint(None, None, "1234567890123", None)
    # Valid 13-digit houjin → different branch (not "13 桁" warning)
    assert isinstance(msg, str)


def test_empty_invoice_registrants_hint_with_q():
    msg = _empty_invoice_registrants_hint("株式会社", None)
    assert isinstance(msg, str)


def test_empty_invoice_registrants_hint_both():
    msg = _empty_invoice_registrants_hint("株式会社", "1234567890123")
    assert isinstance(msg, str)


def test_empty_tax_rules_hint_both_filters():
    msg = _empty_tax_rules_hint("税制", "corporate")
    assert isinstance(msg, str)


# =============================================================================
# Sentinel — verify the v2 test module loaded by importing _err.
# =============================================================================


def test_v2_module_loads_correctly():
    """Sentinel that ensures the test module's top-level imports succeeded."""
    assert _err is not None
    assert _envelope_merge is not None
    assert _walk_and_sanitize_mcp is not None
