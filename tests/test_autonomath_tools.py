"""Smoke + envelope-shape tests for the 16 AutonoMath MCP tools.

Backlog task #148. The 16 tools live across three files in
``src/jpintel_mcp/mcp/autonomath_tools/``:

    autonomath_wrappers.py    — search_gx_programs_am / search_loans_am /
                                 check_enforcement_am / search_mutual_plans_am /
                                 get_law_article_am  (5 tools, _safe_envelope deco)
    tax_rule_tool.py           — get_am_tax_rule  (1 tool, no _safe_envelope)
    tools.py                   — search_tax_incentives / search_certifications /
                                 list_open_programs / enum_values_am /
                                 search_by_law / active_programs_at /
                                 related_programs / search_acceptance_stats_am /
                                 intent_of / reason_answer  (10 tools, _safe_tool deco)

Tests run against the real ~7.3 GB autonomath.db + graph.sqlite at the repo
root. Connections are thread-local cached (``connect_autonomath`` /
``connect_graph``) so we never close them. Tests skip module-wide if the DB
is missing (CI with no fixture, or laptops without a snapshot).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"
_DEFAULT_GRAPH = _REPO_ROOT / "graph.sqlite"

# Honor an explicit env override if set; fall back to the repo-root copy.
_DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_DB)))
_GRAPH_PATH = Path(os.environ.get("AUTONOMATH_GRAPH_DB_PATH", str(_DEFAULT_GRAPH)))

if not _DB_PATH.exists() or not _GRAPH_PATH.exists():
    pytest.skip(
        f"autonomath.db ({_DB_PATH}) or graph.sqlite ({_GRAPH_PATH}) "
        "not present; skipping the AutonoMath tool suite. "
        "Set AUTONOMATH_DB_PATH / AUTONOMATH_GRAPH_DB_PATH to point at a snapshot.",
        allow_module_level=True,
    )

# Ensure the autonomath_tools.db helper picks up the right paths even if the
# import order resolved before this test module loaded.
os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ["AUTONOMATH_GRAPH_DB_PATH"] = str(_GRAPH_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")

# `jpintel_mcp.mcp.server` must be imported FIRST to break the circular
# import between autonomath_tools/tools.py (imports server.mcp) and
# server.py (imports autonomath_tools.tools). After server is loaded, both
# wrapper packages and the underlying tool modules are safe to import.
from jpintel_mcp.mcp import server  # noqa: F401, E402

from jpintel_mcp.mcp.autonomath_tools.autonomath_wrappers import (  # noqa: E402
    check_enforcement_am,
    get_law_article_am,
    search_gx_programs_am,
    search_loans_am,
    search_mutual_plans_am,
)
from jpintel_mcp.mcp.autonomath_tools.tax_rule_tool import get_am_tax_rule  # noqa: E402
from jpintel_mcp.mcp.autonomath_tools.tools import (  # noqa: E402
    active_programs_at,
    enum_values_am,
    intent_of,
    list_open_programs,
    reason_answer,
    related_programs,
    search_acceptance_stats_am,
    search_by_law,
    search_certifications,
    search_tax_incentives,
)


# ---------------------------------------------------------------------------
# Tiny helpers — keep envelope assertions readable.
# ---------------------------------------------------------------------------


def _has_nested_error(res: dict, code: str) -> bool:
    """True iff res contains the canonical nested envelope with the given code."""
    err = res.get("error")
    return isinstance(err, dict) and err.get("code") == code


def _assert_paginated_envelope(res: dict) -> None:
    """Common shape for the 8 search_* / list_* tools that paginate."""
    assert isinstance(res, dict)
    assert "total" in res
    assert "results" in res
    assert isinstance(res["results"], list)


# ---------------------------------------------------------------------------
# 1. search_gx_programs_am  (autonomath_wrappers.py)
# ---------------------------------------------------------------------------


def test_search_gx_programs_am_happy_ev_theme():
    res = search_gx_programs_am(theme="ev", limit=5)
    _assert_paginated_envelope(res)
    assert res["total"] >= 1
    row = res["results"][0]
    assert row["theme"] == "ev"
    assert row["canonical_id"].startswith("program:gx:")
    assert "program_name" in row


def test_search_gx_programs_am_happy_renewable_theme():
    res = search_gx_programs_am(theme="renewable", limit=5)
    _assert_paginated_envelope(res)
    assert res["total"] >= 1
    assert all(r["theme"] == "renewable" for r in res["results"])


def test_search_gx_programs_am_company_size_axis():
    """company_size adds an axis: filters down to rows that include the SME token."""
    res = search_gx_programs_am(theme="ghg_reduction", company_size="sme", limit=5)
    _assert_paginated_envelope(res)
    # 0 hits is acceptable (axis may eliminate everything) but if non-empty,
    # every row must have the SME token in target_types.
    for r in res["results"]:
        assert "中小企業" in (r.get("target_types") or [])


def test_search_gx_programs_am_bad_theme_returns_invalid_enum():
    res = search_gx_programs_am(theme="not_a_real_theme", limit=5)  # type: ignore[arg-type]
    assert _has_nested_error(res, "invalid_enum")
    assert res["total"] == 0
    assert res["results"] == []


# ---------------------------------------------------------------------------
# 2. search_loans_am  (autonomath_wrappers.py)
# ---------------------------------------------------------------------------


def test_search_loans_am_happy_no_filter():
    res = search_loans_am(limit=5)
    _assert_paginated_envelope(res)
    assert res["total"] >= 1
    row = res["results"][0]
    assert row["canonical_id"].startswith("loan:")
    assert "primary_name" in row
    assert "flags" in row  # 3-axis flags surfaced


def test_search_loans_am_happy_loan_kind_axis():
    res = search_loans_am(loan_kind="sogyo", limit=5)
    _assert_paginated_envelope(res)
    assert res["total"] >= 1
    for r in res["results"]:
        assert r["loan_program_kind"] == "sogyo"


def test_search_loans_am_happy_three_axis_no_personal_guarantor():
    res = search_loans_am(no_personal_guarantor=True, limit=5)
    _assert_paginated_envelope(res)
    for r in res["results"]:
        assert r["personal_guarantor"] == "not_required"
        assert r["flags"]["no_personal_guarantor"] is True


def test_search_loans_am_bad_loan_kind_returns_invalid_enum():
    res = search_loans_am(loan_kind="not_a_loan_kind", limit=5)  # type: ignore[arg-type]
    assert _has_nested_error(res, "invalid_enum")


# ---------------------------------------------------------------------------
# 3. check_enforcement_am  (autonomath_wrappers.py)
# ---------------------------------------------------------------------------


def test_check_enforcement_am_happy_with_real_houjin():
    """Use a 法人番号 that exists in am_enforcement_detail (株式会社ラインナップ)."""
    res = check_enforcement_am(houjin_bangou="1010401030882")
    assert res["found"] is True
    assert res["all_count"] >= 1
    assert "queried" in res
    assert res["queried"]["houjin_bangou"] == "1010401030882"


def test_check_enforcement_am_unknown_houjin_returns_no_matching_records():
    """Bogus-but-13-digit number — valid input, no rows matched. Standardized
    on the canonical envelope with ``error.code='no_matching_records'`` (soft
    severity). ``found=False`` + ``all_count=0`` are still surfaced alongside
    the error so DD agents read the corpus-scope disclosure."""
    res = check_enforcement_am(houjin_bangou="9999999999999")
    assert res["found"] is False
    assert res["all_count"] == 0
    assert _has_nested_error(res, "no_matching_records")
    assert "coverage_scope" in res["error"]


def test_check_enforcement_am_unknown_name_returns_no_matching_records():
    """Name-only miss surfaces the same canonical envelope plus a
    name-specific retry hint (法人格 / fuzzy variant)."""
    res = check_enforcement_am(target_name="存在しない株式会社XYZ12345")
    assert res["found"] is False
    assert _has_nested_error(res, "no_matching_records")
    assert res["error"].get("data_state") == "name_only_exact_match"


def test_check_enforcement_am_bad_input_returns_missing_required_arg():
    """No identifier at all → missing_required_arg envelope (not just empty response)."""
    res = check_enforcement_am()
    err = res.get("error")
    assert isinstance(err, dict)
    assert err.get("code") == "missing_required_arg"


# ---------------------------------------------------------------------------
# 4. search_mutual_plans_am  (autonomath_wrappers.py)
# ---------------------------------------------------------------------------


def test_search_mutual_plans_am_happy_retirement_kind():
    res = search_mutual_plans_am(plan_kind="retirement_mutual", limit=5)
    _assert_paginated_envelope(res)
    assert res["total"] >= 1
    for r in res["results"]:
        assert r["plan_kind"] == "retirement_mutual"
        assert r["canonical_id"].startswith("mutual:")


def test_search_mutual_plans_am_premium_axis():
    """premium_monthly_yen filters to rows whose [min, max] contains the budget."""
    res = search_mutual_plans_am(premium_monthly_yen=30000, limit=10)
    _assert_paginated_envelope(res)
    for r in res["results"]:
        pmin = r.get("premium_min_yen")
        pmax = r.get("premium_max_yen")
        if pmin is not None:
            assert pmin <= 30000
        if pmax is not None:
            assert pmax >= 30000


def test_search_mutual_plans_am_bad_plan_kind_returns_invalid_enum():
    res = search_mutual_plans_am(plan_kind="not_a_plan", limit=5)  # type: ignore[arg-type]
    assert _has_nested_error(res, "invalid_enum")


# ---------------------------------------------------------------------------
# 5. get_law_article_am  (autonomath_wrappers.py)
# ---------------------------------------------------------------------------


def test_get_law_article_am_happy_canonical_form():
    res = get_law_article_am(
        law_name_or_canonical_id="租税特別措置法",
        article_number="第41条の19",
    )
    assert res["found"] is True
    assert res["article_number"] == "第41条の19"
    assert res["law"]["canonical_name"] == "租税特別措置法"
    assert res.get("title")


def test_get_law_article_am_happy_normalized_form():
    """Normalization branch: '41の19' should resolve to '第41条の19'."""
    res = get_law_article_am(
        law_name_or_canonical_id="租税特別措置法",
        article_number="41の19",
    )
    assert res["found"] is True
    assert res["article_number"] == "第41条の19"


def test_get_law_article_am_unknown_law_returns_seed_not_found():
    """Standardized on the canonical envelope: a missing law is a
    ``seed_not_found`` (the law canonical_id failed to resolve)."""
    res = get_law_article_am(
        law_name_or_canonical_id="存在しない法律XYZ",
        article_number="第1条",
    )
    assert res["found"] is False
    assert _has_nested_error(res, "seed_not_found")
    assert res["error"]["queried"]["law_name_or_canonical_id"] == "存在しない法律XYZ"


def test_get_law_article_am_unknown_article_returns_no_matching_records():
    """Law resolves but article missing → ``no_matching_records`` (soft).
    The resolved law is preserved at top level for the LLM to see."""
    res = get_law_article_am(
        law_name_or_canonical_id="租税特別措置法",
        article_number="第99999条",
    )
    assert res["found"] is False
    assert _has_nested_error(res, "no_matching_records")
    assert res["law"]["canonical_name"] == "租税特別措置法"
    assert res["error"]["queried"]["article_number"] == "第99999条"


# ---------------------------------------------------------------------------
# 6. get_am_tax_rule  (tax_rule_tool.py)
# ---------------------------------------------------------------------------


def test_get_am_tax_rule_happy_known_measure():
    res = get_am_tax_rule(measure_name_or_id="中小企業投資促進税制")
    assert res["total"] >= 1
    row = res["results"][0]
    assert "tax_measure" in row
    assert row["tax_measure"]["name"]
    assert "rule_type" in row
    assert "effective_period" in row


def test_get_am_tax_rule_filter_by_rule_type():
    """rule_type axis filters to a single option (credit / deduction / …)."""
    res = get_am_tax_rule(
        measure_name_or_id="中小企業投資促進税制",
        rule_type="credit",
    )
    for r in res["results"]:
        assert r["rule_type"] == "credit"


def test_get_am_tax_rule_unknown_measure_returns_seed_not_found():
    """Standardized on the canonical envelope: an unresolved measure is a
    ``seed_not_found`` (analogous to graph-seed lookups). The actionable hint
    moves into ``error.hint``; ``error.queried`` echoes the input."""
    res = get_am_tax_rule(measure_name_or_id="ZZZ_NOT_A_REAL_TAX_MEASURE_XYZ")
    assert res["total"] == 0
    assert res["results"] == []
    assert _has_nested_error(res, "seed_not_found")
    assert res["error"]["queried"] == "ZZZ_NOT_A_REAL_TAX_MEASURE_XYZ"


# ---------------------------------------------------------------------------
# 7. search_tax_incentives  (tools.py)
# ---------------------------------------------------------------------------


def test_search_tax_incentives_happy_query():
    # Default fields="minimal" (dd_v3_09 / v8 P3-K token shaping).
    res = search_tax_incentives(query="事業承継", limit=5)
    _assert_paginated_envelope(res)
    assert res["total"] >= 1
    row = res["results"][0]
    # Minimal shape: 4 keys exactly.
    assert set(row.keys()) == {"id", "name", "score", "source_url"}


def test_search_tax_incentives_full_shape_preserves_legacy_columns():
    # fields="full" restores the pre-shaping legacy row (raw_json-derived
    # columns like canonical_id, root_law, etc.).
    res = search_tax_incentives(query="事業承継", limit=5, fields="full")
    _assert_paginated_envelope(res)
    assert res["total"] >= 1
    row = res["results"][0]
    assert "name" in row
    assert "canonical_id" in row


def test_search_tax_incentives_standard_shape():
    res = search_tax_incentives(query="事業承継", limit=2, fields="standard")
    _assert_paginated_envelope(res)
    assert res["total"] >= 1
    row = res["results"][0]
    # Standard adds 6 fields on top of minimal-4.
    assert {"id", "name", "score", "source_url", "authority",
            "tax_category", "amount_or_rate", "application_period_to",
            "fetched_at", "summary"}.issubset(row.keys())


def test_search_tax_incentives_limit_cap_emits_warning():
    res = search_tax_incentives(query="税制", limit=50)
    # Capped to 20 with input_warnings (limit_max_exceeded → limit_capped).
    assert res["limit"] == 20
    warns = res.get("input_warnings", [])
    assert any(w.get("code") == "limit_capped" for w in warns)


def test_search_tax_incentives_happy_authority_axis():
    res = search_tax_incentives(authority="国税庁", limit=5)
    _assert_paginated_envelope(res)
    # authority filter resolves to source_url_domain hints; just confirm shape.
    assert res["total"] >= 0


def test_search_tax_incentives_bad_query_returns_no_matching_records():
    res = search_tax_incentives(query="QQQ_NEVER_MATCH_ZZZ", limit=5)
    assert res["total"] == 0
    assert _has_nested_error(res, "no_matching_records")


# ---------------------------------------------------------------------------
# 8. search_certifications  (tools.py)
# ---------------------------------------------------------------------------


def test_search_certifications_happy_query():
    # Default fields="minimal" (dd_v3_09 / v8 P3-K token shaping).
    res = search_certifications(query="健康経営", limit=5)
    _assert_paginated_envelope(res)
    assert res["total"] >= 1
    row = res["results"][0]
    # Minimal shape: 4 keys exactly.
    assert set(row.keys()) == {"id", "name", "score", "source_url"}


def test_search_certifications_full_shape_preserves_legacy_columns():
    # fields="full" restores legacy row including linked_subsidies +
    # linked_tax_incentives (load-bearing for "what does this cert unlock").
    res = search_certifications(query="健康経営", limit=5, fields="full")
    _assert_paginated_envelope(res)
    assert res["total"] >= 1
    row = res["results"][0]
    assert "program_name" in row
    assert "canonical_id" in row


def test_search_certifications_standard_shape():
    res = search_certifications(query="健康経営", limit=2, fields="standard")
    _assert_paginated_envelope(res)
    assert res["total"] >= 1
    row = res["results"][0]
    assert {"id", "name", "score", "source_url", "authority",
            "root_law", "validity_years", "target_size",
            "fetched_at", "summary"}.issubset(row.keys())


def test_search_certifications_limit_cap_emits_warning():
    res = search_certifications(limit=99)
    assert res["limit"] == 20
    warns = res.get("input_warnings", [])
    assert any(w.get("code") == "limit_capped" for w in warns)


def test_search_certifications_bad_query_returns_no_matching_records():
    res = search_certifications(query="QQQ_NEVER_MATCH_CERT_999", limit=5)
    assert res["total"] == 0
    assert _has_nested_error(res, "no_matching_records")


# ---------------------------------------------------------------------------
# 9. list_open_programs  (tools.py)
# ---------------------------------------------------------------------------


def test_list_open_programs_happy_today():
    res = list_open_programs(limit=5)
    _assert_paginated_envelope(res)
    assert "pivot_date" in res
    # No assertion on total — depends on what's "open" today; just ensure
    # the envelope is well-formed.


def test_list_open_programs_bad_date_returns_invalid_date_format():
    res = list_open_programs(on_date="not-a-date")
    assert _has_nested_error(res, "invalid_date_format")


# ---------------------------------------------------------------------------
# 10. enum_values_am  (tools.py)
# ---------------------------------------------------------------------------


def test_enum_values_am_happy_authority():
    res = enum_values_am(enum_name="authority")
    assert res["enum_name"] == "authority"
    assert isinstance(res["values"], list)
    assert len(res["values"]) >= 1
    assert isinstance(res["frequency_map"], dict)


def test_enum_values_am_happy_region():
    res = enum_values_am(enum_name="region")
    assert res["enum_name"] == "region"
    assert "values" in res
    # 47 都道府県 should be loaded.
    assert len(res["values"]) >= 40


def test_enum_values_am_bad_enum_returns_invalid_enum():
    res = enum_values_am(enum_name="not_a_real_enum")  # type: ignore[arg-type]
    assert _has_nested_error(res, "invalid_enum")
    assert res["values"] == []


# ---------------------------------------------------------------------------
# 11. search_by_law  (tools.py)
# ---------------------------------------------------------------------------


def test_search_by_law_happy_known_law():
    res = search_by_law(law_name="中小企業等経営強化法", limit=5)
    _assert_paginated_envelope(res)
    assert res["total"] >= 1
    assert "law_aliases_tried" in res
    assert "中小企業等経営強化法" in res["law_aliases_tried"]


def test_search_by_law_empty_law_name_returns_missing_required_arg():
    res = search_by_law(law_name="   ", limit=5)
    assert _has_nested_error(res, "missing_required_arg")


def test_search_by_law_unknown_law_returns_no_matching_records():
    res = search_by_law(law_name="ZZZ_NEVER_MATCHES_LAW_XYZ", limit=5)
    assert res["total"] == 0
    assert _has_nested_error(res, "no_matching_records")


# ---------------------------------------------------------------------------
# 12. active_programs_at  (tools.py)
# ---------------------------------------------------------------------------


def test_active_programs_at_happy_past_date():
    res = active_programs_at(date="2024-01-01", limit=5)
    _assert_paginated_envelope(res)
    assert res["pivot_date"] == "2024-01-01"
    assert res["total"] >= 1
    row = res["results"][0]
    assert "on_date_status" in row
    assert row["on_date_status"] in ("active", "about_to_close", "just_started")


def test_active_programs_at_bad_date_returns_invalid_date_format():
    res = active_programs_at(date="not-a-real-date")
    assert _has_nested_error(res, "invalid_date_format")


def test_active_programs_at_empty_date_returns_missing_required_arg():
    res = active_programs_at(date="")
    assert _has_nested_error(res, "missing_required_arg")


# ---------------------------------------------------------------------------
# 13. related_programs  (tools.py)
# ---------------------------------------------------------------------------


def test_related_programs_happy_dense_seed():
    """J-Startup is one of the densest seeds in graph.sqlite (~28 edges)."""
    res = related_programs(
        program_id="program:J-Startup",
        depth=1,
        max_edges=50,
    )
    assert res["seed_kind"] == "program"
    assert "relations" in res
    # At least one relation axis fired.
    assert res["total_edges"] >= 1


def test_related_programs_bogus_seed_returns_seed_not_found():
    res = related_programs(program_id="not_a_real_seed_zzz", depth=1)
    assert _has_nested_error(res, "seed_not_found")


def test_related_programs_empty_seed_returns_missing_required_arg():
    res = related_programs(program_id="   ", depth=1)
    assert _has_nested_error(res, "missing_required_arg")


# ---------------------------------------------------------------------------
# 14. search_acceptance_stats_am  (tools.py)
# ---------------------------------------------------------------------------


def test_search_acceptance_stats_am_no_filter_emits_envelope():
    res = search_acceptance_stats_am(limit=5)
    _assert_paginated_envelope(res)
    assert res["total"] >= 1
    assert len(res["results"]) >= 1
    row = res["results"][0]
    for key in ("program_name", "round_label", "applicants", "accepted", "source_url"):
        assert key in row


def test_search_acceptance_stats_am_with_program_name_filter():
    res = search_acceptance_stats_am(program_name="ものづくり補助金", limit=5)
    _assert_paginated_envelope(res)
    assert res["total"] >= 1
    assert all("ものづくり" in (r.get("program_name") or "") for r in res["results"])


def test_search_acceptance_stats_am_unknown_program_returns_no_match_envelope():
    res = search_acceptance_stats_am(program_name="存在しない補助金XYZ123", limit=5)
    _assert_paginated_envelope(res)
    assert res["total"] == 0
    assert _has_nested_error(res, "no_matching_records")


# ---------------------------------------------------------------------------
# 15. intent_of  (tools.py)
# ---------------------------------------------------------------------------


def test_intent_of_happy_or_subsystem_unavailable():
    """The reasoning subsystem is an optional package. In this repo the
    `reasoning` module ISN'T on sys.path during pytest, so the tool returns
    a `subsystem_unavailable` envelope (intent=None, confidence=0). We
    accept either path: subsystem present → real classification; absent →
    well-formed unavailable envelope. Both surface a structured response,
    never a stack trace."""
    res = intent_of(query="事業承継税制の特例措置はいつまで?")
    assert isinstance(res, dict)
    assert "intent_id" in res
    assert "confidence" in res
    assert "all_scores" in res
    err = res.get("error")
    if err is not None:
        # Subsystem-absent path.
        assert err["code"] == "subsystem_unavailable"
        assert res["intent_id"] is None
    else:
        # Subsystem-present path.
        assert isinstance(res["intent_id"], str)
        assert 0.0 <= res["confidence"] <= 1.0


def test_intent_of_empty_query_returns_missing_required_arg():
    res = intent_of(query="   ")
    assert _has_nested_error(res, "missing_required_arg")


# ---------------------------------------------------------------------------
# 16. reason_answer  (tools.py)
# ---------------------------------------------------------------------------


def test_reason_answer_happy_or_subsystem_unavailable():
    """Same subsystem-optional pattern as intent_of. The tool MUST always
    return the canonical 13-key skeleton even when `reasoning` is missing,
    so customer LLMs can reason about the failure shape."""
    res = reason_answer(query="熊本県 製造業 従業員 30 人で使える補助金は?")
    expected_keys = {
        "intent",
        "intent_name_ja",
        "filters_extracted",
        "answer_skeleton",
        "confidence",
        "missing_data",
        "precompute_gaps",
        "source_urls",
        "db_bind_ok",
        "db_bind_notes",
        "persona_hint",
        "retry_with",
    }
    assert expected_keys.issubset(res.keys())
    err = res.get("error")
    if err is not None:
        assert err["code"] == "subsystem_unavailable"
        assert res["intent"] is None
    else:
        # Subsystem-present path.
        assert res["intent"] is not None


def test_reason_answer_empty_query_returns_missing_required_arg():
    res = reason_answer(query="")
    assert _has_nested_error(res, "missing_required_arg")


def test_reason_answer_skeleton_strips_missing_tokens():
    """P7 fix 2026-04-25: the prose-facing answer_skeleton must NOT contain
    raw <<<missing:KEY>>> or <<<precompute gap: ...>>> tokens — customer LLMs
    paste them verbatim into outputs. Machine-readable signal lives in
    missing_data / precompute_gaps arrays instead."""
    res = reason_answer(query="熊本県 製造業 従業員 30 人で使える補助金は?")
    if res.get("error") and res["error"].get("code") == "subsystem_unavailable":
        return
    skeleton = res.get("answer_skeleton") or ""
    assert "<<<missing:" not in skeleton
    assert "<<<precompute gap:" not in skeleton


def test_reason_answer_skeleton_rollback_flag_returns_raw_tokens(monkeypatch):
    """Rollback path: when AUTONOMATH_STRIP_MISSING_TOKENS="0" the skeleton
    is returned verbatim, including any raw <<<missing:KEY>>> / <<<precompute
    gap: ...>>> tokens. Verifies the env-var gate so we can revert P7 fix
    without redeploy if downstream consumers depend on raw tokens.

    Verification strategy: the same query that raised tokens in the strip
    test should, with the flag off, expose at least one raw token IFF that
    token would have appeared. If the query happens to bind cleanly (no
    missing keys), the test still passes — we only assert that the strip
    substitutions ('(該当データなし)' / '(集計準備中)') are NOT injected by
    the flag-off path."""
    monkeypatch.setenv("AUTONOMATH_STRIP_MISSING_TOKENS", "0")
    res = reason_answer(query="熊本県 製造業 従業員 30 人で使える補助金は?")
    if res.get("error") and res["error"].get("code") == "subsystem_unavailable":
        return
    skeleton = res.get("answer_skeleton") or ""
    missing_data = res.get("missing_data") or []
    precompute_gaps = res.get("precompute_gaps") or []
    # If the binder reported missing keys, the raw token MUST be present in
    # the skeleton (rollback fidelity). Same for precompute gaps.
    for key in missing_data:
        assert f"<<<missing:{key}>>>" in skeleton, (
            f"flag-off path lost raw <<<missing:{key}>>> token"
        )
    for gap in precompute_gaps:
        assert f"<<<precompute gap: {gap}>>>" in skeleton, (
            f"flag-off path lost raw <<<precompute gap: {gap}>>> token"
        )
    # And the strip substitutions must NOT have been applied by the flag-off
    # path (they could legitimately appear in raw skeleton template literals,
    # so we only check this when the binder reported gaps that would have
    # triggered substitution).
    if missing_data:
        assert "(該当データなし)" not in skeleton or any(
            f"<<<missing:{k}>>>" in skeleton for k in missing_data
        )
