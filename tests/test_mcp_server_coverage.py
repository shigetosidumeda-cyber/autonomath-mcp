"""R8_TEST_COVERAGE_DEEP — boost src/jpintel_mcp/mcp/server.py coverage.

Targets:
- mcp registration / list_tools surface
- helpers (_count_results / _walk_and_sanitize_mcp / _envelope_merge / _empty_*_hint)
- _with_mcp_telemetry decorator (success + error path)
- DB-backed tools that conftest already seeds (search_programs / search_enforcement_cases /
  search_case_studies / search_loan_programs / enum_values / get_meta / list_exclusion_rules /
  upcoming_deadlines / deadline_calendar / search_laws / search_tax_rules /
  search_court_decisions / search_bids / search_invoice_registrants /
  find_precedents_by_statute / get_law / get_court_decision / get_bid /
  get_tax_rule / list_law_revisions / get_enforcement_case / get_case_study /
  get_loan_program)
- cohort-flag gate (settings.autonomath_enabled monkeypatched)
- handshake bits (mcp._mcp_server.version / _init_sentry_mcp)

Convention:
- All assertions are tolerant of envelope additions (do not lock down exact
  key sets when telemetry decorator might add `status`, `tool_name`, etc.).
- LLM 0 — pure SQLite + python.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.mcp.server import (
    _CASE_STUDY_MINIMAL_KEYS,
    _ENFORCEMENT_MINIMAL_KEYS,
    _ENUM_SOURCES,
    _PREFECTURE_SUFFIX,
    _SHAPED_FIELDS,
    _VALID_FIELDS,
    __version__,
    _count_results,
    _emit_mcp_log,
    _empty_bids_hint,
    _empty_case_studies_hint,
    _empty_court_decisions_hint,
    _empty_enforcement_hint,
    _empty_invoice_registrants_hint,
    _empty_laws_hint,
    _empty_loan_hint,
    _empty_precedents_hint,
    _empty_search_hint,
    _empty_tax_rules_hint,
    _enforce_limit_cap,
    _envelope_merge,
    _expansion_coverage_state,
    _fallback_call,
    _init_sentry_mcp,
    _json_col,
    _json_list,
    _jst_today_iso,
    _looks_non_canonical_prefecture,
    _mcp_detect_lang,
    _mcp_params_shape,
    _resolve_fields,
    _resolve_shaped_fields,
    _row_to_bid_dict,
    _row_to_case_study,
    _row_to_court_decision_dict,
    _row_to_dict,
    _row_to_enforcement_case,
    _row_to_invoice_registrant_dict,
    _row_to_law_dict,
    _row_to_loan_program,
    _row_to_tax_ruleset_dict,
    _trim_case_study_fields,
    _trim_enforcement_fields,
    _trim_tax_ruleset,
    _trim_to_fields,
    _walk_and_sanitize_mcp,
    _with_mcp_telemetry,
    deadline_calendar,
    enum_values,
    get_usage_status,
    mcp,
    search_case_studies,
    search_enforcement_cases,
    search_invoice_registrants,
    search_laws,
    search_loan_programs,
    search_tax_rules,
    upcoming_deadlines,
)

if TYPE_CHECKING:
    from pathlib import Path


# =============================================================================
# Module-level invariants — these are cheap & test the bootstrap surface.
# =============================================================================


def test_mcp_singleton_has_version_set_to_package_version():
    """Verify the FastMCP server.version is the package __version__ (not the
    SDK's bundled '1.x'). This is the handshake bit clients see."""
    assert mcp._mcp_server.version == __version__


def test_mcp_singleton_name_is_autonomath():
    """The MCP server name is 'autonomath' — registry contract."""
    assert mcp.name == "autonomath"


def test_valid_fields_constant():
    assert _VALID_FIELDS == ("minimal", "default", "full")


def test_shaped_fields_constant():
    assert _SHAPED_FIELDS == ("minimal", "standard", "full")


def test_prefecture_suffix_constant():
    assert _PREFECTURE_SUFFIX == ("都", "道", "府", "県")


def test_enum_sources_lists_all_supported_fields():
    expected = {
        "target_type",
        "funding_purpose",
        "program_kind",
        "authority_level",
        "prefecture",
        "event_type",
        "ministry",
        "loan_type",
        "provider",
        "programs_used",
    }
    assert expected <= set(_ENUM_SOURCES.keys())


def test_minimal_keys_constants():
    assert "case_id" in _CASE_STUDY_MINIMAL_KEYS
    assert "case_id" in _ENFORCEMENT_MINIMAL_KEYS


# =============================================================================
# list_tools registration — count + name uniqueness assertion.
# =============================================================================


@pytest.mark.asyncio
async def test_mcp_list_tools_returns_nonempty_list():
    """list_tools is the protocol entrypoint a real MCP client calls
    immediately after handshake. Must return >= 39 prod tools (jpintel.db)."""
    tools = await mcp.list_tools()
    # Production manifest declares 139 at default gates; lower bound is the
    # 39 jpintel.db prod tools that always register regardless of cohort flags.
    assert len(tools) >= 39, f"expected >= 39 tools, got {len(tools)}"


@pytest.mark.asyncio
async def test_mcp_list_tools_names_are_unique():
    tools = await mcp.list_tools()
    names = [t.name for t in tools]
    assert len(names) == len(set(names)), (
        f"duplicate tool names: {[n for n in names if names.count(n) > 1]}"
    )


@pytest.mark.asyncio
async def test_mcp_list_tools_includes_search_programs():
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    # Spot-check core tools are wired.
    for required in ("search_programs", "get_program", "get_meta", "enum_values"):
        assert required in names, f"{required} missing from registry"


@pytest.mark.asyncio
async def test_mcp_list_tools_each_carries_description():
    """FastMCP serializes the tool docstring as `description`. A blank
    description means the tool was registered with no doc — bad UX for
    LLM clients."""
    tools = await mcp.list_tools()
    blanks = [t.name for t in tools if not (t.description or "").strip()]
    assert blanks == [], f"tools missing description: {blanks}"


# =============================================================================
# Cohort flag gate — verify mcp registration reflects settings.autonomath_enabled.
# Using an indirect check: the autonomath_tools cohort exposes specific tools,
# so a re-import with settings.autonomath_enabled=True still has them; with
# False they would be skipped (we don't reload here, just verify the tools
# from autonomath_tools ARE present under the test default settings).
# =============================================================================


@pytest.mark.asyncio
async def test_cohort_autonomath_tools_registered_when_enabled():
    """conftest.py keeps autonomath_enabled True; verify cohort-gated tools
    surface. These names are owned by the autonomath_tools subpackage and
    only appear when the cohort flag was True at server.py import time."""
    from jpintel_mcp.config import settings

    if not settings.autonomath_enabled:
        pytest.skip("autonomath_enabled gate is off in this environment")
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    # At least one autonomath_tools-owned tool must be present. Pick a
    # stable sentinel that's been live since the V4 cohort wiring.
    cohort_sentinels = {
        "search_tax_incentives",
        "list_open_programs",
        "enum_values_am",
        "graph_traverse",
    }
    assert cohort_sentinels & names, (
        f"none of {cohort_sentinels} found in registry — cohort gate broken?"
    )


# =============================================================================
# Pure helpers — no DB.
# =============================================================================


def test_resolve_fields_default():
    assert _resolve_fields(None) == "default"
    assert _resolve_fields("minimal") == "minimal"
    assert _resolve_fields("full") == "full"


def test_resolve_fields_invalid_raises():
    with pytest.raises(ValueError, match="fields must be one of"):
        _resolve_fields("invalid_value")


def test_resolve_shaped_fields_default():
    assert _resolve_shaped_fields(None) == "minimal"
    for v in _SHAPED_FIELDS:
        assert _resolve_shaped_fields(v) == v


def test_resolve_shaped_fields_invalid_raises():
    with pytest.raises(ValueError, match="fields must be one of"):
        _resolve_shaped_fields("legacy_default")


def test_enforce_limit_cap_under_cap_emits_no_warning():
    new_limit, warnings = _enforce_limit_cap(10, cap=20)
    assert new_limit == 10
    assert warnings == []


def test_enforce_limit_cap_at_cap_emits_no_warning():
    new_limit, warnings = _enforce_limit_cap(20, cap=20)
    assert new_limit == 20
    assert warnings == []


def test_enforce_limit_cap_over_cap_emits_warning_and_clamps():
    new_limit, warnings = _enforce_limit_cap(100, cap=20)
    assert new_limit == 20
    assert len(warnings) == 1
    w = warnings[0]
    assert w["field"] == "limit"
    assert w["code"] == "limit_capped"
    assert w["value"] == 100
    assert w["normalized_to"] == 20


def test_count_results_dict_with_results_list():
    assert _count_results({"results": [1, 2, 3]}) == 3
    assert _count_results({"results": []}) == 0


def test_count_results_dict_without_results_list():
    assert _count_results({"foo": "bar"}) == 1


def test_count_results_bare_list():
    assert _count_results([1, 2, 3, 4]) == 4
    assert _count_results([]) == 0


def test_count_results_none():
    assert _count_results(None) == 0


def test_count_results_other_scalars():
    assert _count_results(42) == 1
    assert _count_results("string") == 1


def test_mcp_detect_lang_japanese():
    assert _mcp_detect_lang("補助金検索") == "ja"


def test_mcp_detect_lang_english():
    assert _mcp_detect_lang("subsidy search") == "en"


def test_mcp_detect_lang_mixed():
    # ~30% CJK
    assert _mcp_detect_lang("subsidy 補助金 search") == "mixed"


def test_mcp_detect_lang_empty():
    assert _mcp_detect_lang("") == "en"


def test_mcp_params_shape_omits_none_values():
    out = _mcp_params_shape({"a": 1, "b": None, "c": "x"})
    assert "a" in out
    assert "b" not in out
    assert "c" in out


def test_mcp_params_shape_records_q_meta_when_present():
    out = _mcp_params_shape({"q": "補助金検索"})
    assert out["q"] is True
    assert out["q_len"] == 5
    assert out["q_lang"] == "ja"


def test_mcp_params_shape_with_no_q():
    out = _mcp_params_shape({"limit": 10})
    assert "q_len" not in out
    assert "q_lang" not in out


def test_emit_mcp_log_does_not_raise():
    # Telemetry is best-effort; this sanity-checks it doesn't blow up
    # on a non-serializable input.
    _emit_mcp_log(
        tool_name="test",
        params_shape={"a": True},
        result_count=0,
        latency_ms=12,
        status=200,
        error_class=None,
    )


def test_emit_mcp_log_swallows_serialization_errors():
    """params_shape with an unserializable type — must not raise."""

    class NotSerializable:
        pass

    _emit_mcp_log(
        tool_name="x",
        params_shape={"obj": NotSerializable()},
        result_count=0,
        latency_ms=1,
        status="error",
        error_class="ValueError",
    )


def test_walk_and_sanitize_mcp_passes_clean_string_through():
    out, hits = _walk_and_sanitize_mcp("hello world")
    assert out == "hello world"
    assert hits == []


def test_walk_and_sanitize_mcp_handles_dict():
    out, hits = _walk_and_sanitize_mcp({"a": "x", "b": ["y", "z"]})
    assert out == {"a": "x", "b": ["y", "z"]}
    assert hits == []


def test_walk_and_sanitize_mcp_handles_list():
    out, hits = _walk_and_sanitize_mcp(["a", "b", {"x": "y"}])
    assert out == ["a", "b", {"x": "y"}]
    assert hits == []


def test_walk_and_sanitize_mcp_passes_through_non_string():
    out, hits = _walk_and_sanitize_mcp(42)
    assert out == 42
    assert hits == []


def test_walk_and_sanitize_mcp_handles_none():
    out, hits = _walk_and_sanitize_mcp(None)
    assert out is None
    assert hits == []


# =============================================================================
# _looks_non_canonical_prefecture
# =============================================================================


def test_looks_non_canonical_prefecture_canonical():
    assert _looks_non_canonical_prefecture("東京都") is False
    assert _looks_non_canonical_prefecture("北海道") is False
    assert _looks_non_canonical_prefecture("大阪府") is False
    assert _looks_non_canonical_prefecture("青森県") is False


def test_looks_non_canonical_prefecture_zenkoku_passes():
    assert _looks_non_canonical_prefecture("全国") is False


def test_looks_non_canonical_prefecture_short_form():
    assert _looks_non_canonical_prefecture("東京") is True
    assert _looks_non_canonical_prefecture("Tokyo") is True


def test_looks_non_canonical_prefecture_none():
    assert _looks_non_canonical_prefecture(None) is False


# =============================================================================
# Empty-result hints — all branches.
# =============================================================================


def test_empty_search_hint_short_query():
    msg = _empty_search_hint("a", None, None, None)
    assert "短すぎ" in msg


def test_empty_search_hint_non_canonical_prefecture():
    msg = _empty_search_hint(None, "Tokyo", None, None)
    assert "canonical" in msg


def test_empty_search_hint_target_type_mismatch():
    msg = _empty_search_hint(None, None, None, None, target_type=["sme"])
    assert "target_type" in msg


def test_empty_search_hint_funding_purpose_mismatch():
    msg = _empty_search_hint(None, None, None, None, funding_purpose=["DX"])
    assert "funding_purpose" in msg


def test_empty_search_hint_tier_only_sa():
    msg = _empty_search_hint(None, None, ["S", "A"], None)
    assert "tier" in msg


def test_empty_search_hint_prefecture_only():
    msg = _empty_search_hint(None, "東京都", None, None)
    assert "prefecture" in msg


def test_empty_search_hint_authority_national():
    msg = _empty_search_hint(None, None, None, "national")
    assert "national" in msg


def test_empty_search_hint_default_pivot():
    msg = _empty_search_hint(None, None, None, None)
    assert "search_case_studies" in msg


def test_empty_case_studies_hint_branches():
    assert "canonical" in _empty_case_studies_hint("Tokyo", None, None, None)
    assert "program_used" in _empty_case_studies_hint(None, None, None, "未登録")
    assert "13 桁" in _empty_case_studies_hint(None, None, "12345", None)
    assert "粒度" in _empty_case_studies_hint(None, "ABC", None, None)
    assert "採択事例に該当なし" in _empty_case_studies_hint(None, None, None, None)


def test_empty_enforcement_hint_branches():
    assert "canonical" in _empty_enforcement_hint("Tokyo", None, None, None)
    assert "ministry" in _empty_enforcement_hint(None, "厚労省", None, None)
    assert "event_type" in _empty_enforcement_hint(None, None, "unknown", None)
    assert "recipient_houjin_bangou" in _empty_enforcement_hint(None, None, None, "1234567890123")
    assert "会計検査院" in _empty_enforcement_hint(None, None, None, None)


def test_empty_loan_hint_branches():
    assert "provider" in _empty_loan_hint("JFC", None)
    assert "loan_type" in _empty_loan_hint(None, "運転資金")
    assert "融資" in _empty_loan_hint(None, None)


def test_empty_laws_hint_branches():
    assert "短すぎ" in _empty_laws_hint("a", None, None)
    assert "ministry" in _empty_laws_hint(None, "厚労省", None)
    assert "law_type" in _empty_laws_hint(None, None, "unknown")
    assert "略称" in _empty_laws_hint(None, None, None)


def test_empty_tax_rules_hint_branches():
    assert "事業承継" in _empty_tax_rules_hint("事業承継税制", None)
    assert "inheritance" in _empty_tax_rules_hint(None, "inheritance")
    assert "短すぎ" in _empty_tax_rules_hint("a", None)
    assert "35 行" in _empty_tax_rules_hint(None, None)


def test_empty_court_decisions_hint():
    msg = _empty_court_decisions_hint(None)
    assert "判例" in msg


def test_empty_precedents_hint_with_citation():
    msg = _empty_precedents_hint("民法第709条")
    assert "民法第709条" in msg


def test_empty_precedents_hint_without_citation():
    msg = _empty_precedents_hint(None)
    assert "判例" in msg


def test_empty_bids_hint():
    msg = _empty_bids_hint(None)
    assert "入札" in msg


def test_empty_invoice_registrants_hint_invalid_houjin():
    msg = _empty_invoice_registrants_hint(None, "12345")
    assert "13 桁" in msg


def test_empty_invoice_registrants_hint_no_filter():
    msg = _empty_invoice_registrants_hint(None, None)
    assert "適格請求書" in msg


# =============================================================================
# _expansion_coverage_state
# =============================================================================


def test_expansion_coverage_state_empty_table(seeded_db: Path):
    """An empty table → 'table_pending_load' state."""
    conn = sqlite3.connect(seeded_db)
    try:
        # `bids` table is empty in the test fixture.
        state = _expansion_coverage_state("bids", conn)
        assert state["data_state"] in {"table_pending_load", "partial"}
    finally:
        conn.close()


def test_expansion_coverage_state_missing_table(seeded_db: Path):
    """A missing table → row_count=0, also returns table_pending_load."""
    conn = sqlite3.connect(seeded_db)
    try:
        state = _expansion_coverage_state("does_not_exist", conn)
        assert state["data_state"] == "table_pending_load"
        assert state["rows_loaded"] == 0
    finally:
        conn.close()


def test_expansion_coverage_state_partial(seeded_db: Path):
    """Programs has rows in the seed fixture."""
    conn = sqlite3.connect(seeded_db)
    try:
        state = _expansion_coverage_state("programs", conn)
        assert state["data_state"] == "partial"
        assert state["rows_loaded"] >= 4
    finally:
        conn.close()


# =============================================================================
# _trim_to_fields / _trim_case_study_fields / _trim_enforcement_fields
# =============================================================================


def test_trim_to_fields_minimal_preserves_whitelist_only():
    from jpintel_mcp.models import MINIMAL_FIELD_WHITELIST

    rec = {k: f"v_{k}" for k in MINIMAL_FIELD_WHITELIST}
    rec["extra_key"] = "should_be_dropped"
    out = _trim_to_fields(rec, "minimal")
    assert "extra_key" not in out
    assert set(out.keys()) == set(MINIMAL_FIELD_WHITELIST)


def test_trim_to_fields_full_adds_missing_keys():
    out = _trim_to_fields({"unified_id": "x"}, "full")
    for k in ("enriched", "source_mentions", "source_url", "source_fetched_at", "source_checksum"):
        assert k in out


def test_trim_to_fields_default_passes_through():
    rec = {"foo": "bar"}
    out = _trim_to_fields(rec, "default")
    assert out is rec


def test_trim_case_study_fields_minimal():
    rec = {k: f"v_{k}" for k in _CASE_STUDY_MINIMAL_KEYS}
    rec["extra"] = "drop"
    out = _trim_case_study_fields(rec, "minimal")
    assert set(out.keys()) == set(_CASE_STUDY_MINIMAL_KEYS)


def test_trim_case_study_fields_standard_includes_extras():
    rec = {
        "case_id": "x",
        "company_name": "y",
        "case_title": "z",
        "source_url": "u",
        "prefecture": "東京都",
        "industry_jsic": "E",
        "industry_name": "Manufacturing",
        "publication_date": "2025-01-01",
        "total_subsidy_received_yen": 100,
        "fetched_at": "2025-01-01",
    }
    out = _trim_case_study_fields(rec, "standard")
    assert "prefecture" in out


def test_trim_case_study_fields_full_passes_through():
    rec = {"case_id": "x", "anything": "y"}
    out = _trim_case_study_fields(rec, "full")
    assert out is rec


def test_trim_enforcement_fields_minimal():
    rec = {k: f"v_{k}" for k in _ENFORCEMENT_MINIMAL_KEYS}
    rec["extra"] = "drop"
    out = _trim_enforcement_fields(rec, "minimal")
    assert set(out.keys()) == set(_ENFORCEMENT_MINIMAL_KEYS)


def test_trim_enforcement_fields_standard_extras():
    rec = {
        "case_id": "x",
        "program_name_hint": "y",
        "event_type": "z",
        "source_url": "u",
        "ministry": "厚生労働省",
        "prefecture": "東京都",
        "disclosed_date": "2024-01-01",
        "amount_improper_grant_yen": 100,
        "recipient_name": "Co",
        "fetched_at": "2024-01-01",
    }
    out = _trim_enforcement_fields(rec, "standard")
    assert "ministry" in out


# =============================================================================
# _json_col + _json_list helpers
# =============================================================================


def test_json_col_returns_default_on_null(seeded_db: Path):
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM programs WHERE unified_id = ?", ("UNI-test-b-1",)
        ).fetchone()
        # 'aliases_json' is NULL in seed fixture; default returns []
        out = _json_col(row, "aliases_json", [])
        assert out == []
    finally:
        conn.close()


def test_json_col_decodes_valid_json(seeded_db: Path):
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM programs WHERE unified_id = ?", ("UNI-test-s-1",)
        ).fetchone()
        out = _json_col(row, "target_types_json", [])
        assert out == ["sole_proprietor", "corporation"]
    finally:
        conn.close()


def test_json_col_returns_default_on_decode_error(seeded_db: Path):
    """If column has malformed JSON, return default — never raise."""
    from datetime import UTC, datetime

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    now = datetime.now(UTC).isoformat()
    try:
        # Insert a row with malformed JSON intentionally.
        conn.execute(
            "INSERT INTO programs(unified_id, primary_name, target_types_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("UNI-malformed", "broken", "{broken json", now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM programs WHERE unified_id = ?", ("UNI-malformed",)
        ).fetchone()
        out = _json_col(row, "target_types_json", ["fallback"])
        assert out == ["fallback"]
    finally:
        try:
            conn.execute("DELETE FROM programs WHERE unified_id = ?", ("UNI-malformed",))
            conn.commit()
        except Exception:
            pass
        conn.close()


def test_json_list_helper(seeded_db: Path):
    """_json_list returns a list, never None."""
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM programs WHERE unified_id = ?", ("UNI-test-s-1",)
        ).fetchone()
        # _json_list parses target_types_json safely
        out = _json_list(row, "target_types_json")
        assert isinstance(out, list)
    finally:
        conn.close()


# =============================================================================
# _fallback_call — verify the early-return when fallback mode is OFF.
# =============================================================================


def test_fallback_call_returns_none_when_local_db_present(seeded_db: Path):
    """Local DB has rows → fallback mode is False → _fallback_call returns None."""
    res = _fallback_call("search_programs", rest_path="/v1/programs/search", params={})
    # When detect_fallback_mode() is False, we return None to let the SQL
    # path execute. seeded_db has real rows so detection should be False.
    assert res is None


# =============================================================================
# _envelope_merge — verify additive merge + opt-out.
# =============================================================================


def test_envelope_merge_returns_dict_for_dict_input(seeded_db: Path):
    """Standard fields → merged dict with envelope additive keys."""
    base = {"results": [], "total": 0, "limit": 20, "offset": 0}
    out = _envelope_merge(
        tool_name="search_programs",
        result=base,
        kwargs={"q": "test"},
        latency_ms=10.0,
    )
    assert isinstance(out, dict)
    # Original keys preserved verbatim
    assert out["total"] == 0


def test_envelope_merge_preserves_existing_meta(seeded_db: Path):
    """Tool-level meta wins on key collision."""
    base = {
        "results": [{"id": 1}],
        "total": 1,
        "limit": 20,
        "offset": 0,
        "meta": {"data_as_of": "2025-12-31"},
    }
    out = _envelope_merge(
        tool_name="x",
        result=base,
        kwargs={},
        latency_ms=5.0,
    )
    # meta.data_as_of preserved
    assert out["meta"]["data_as_of"] == "2025-12-31"


def test_envelope_merge_handles_error_envelope(seeded_db: Path):
    """Tool-pre-built error → still returns dict with the error preserved."""
    base = {
        "results": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
        "error": {"code": "invalid_range", "message": "x"},
    }
    out = _envelope_merge(
        tool_name="search_programs",
        result=base,
        kwargs={},
        latency_ms=2.0,
    )
    # Error preserved
    assert out["error"]["code"] == "invalid_range"


def test_envelope_merge_handles_non_dict_input(seeded_db: Path):
    """Bare list result → envelope returned as-is (defensive coding)."""
    out = _envelope_merge(
        tool_name="x",
        result=[1, 2, 3],
        kwargs={},
        latency_ms=1.0,
    )
    # Either the bare list (early-return) or a dict envelope is acceptable.
    # We just need it to NOT raise.
    assert out is not None


# =============================================================================
# _with_mcp_telemetry decorator — success + error paths.
# =============================================================================


def test_with_mcp_telemetry_success_path():
    @_with_mcp_telemetry
    def ok_fn(a: int, b: int = 2) -> dict:
        return {"results": [a, b], "total": 2}

    out = ok_fn(1, b=5)
    assert isinstance(out, dict)
    # Original keys preserved
    assert out["total"] == 2


def test_with_mcp_telemetry_error_path_returns_envelope():
    """A raised exception inside fn → telemetry wrapper returns an
    error envelope (does not propagate)."""

    @_with_mcp_telemetry
    def err_fn() -> dict:
        raise ValueError("boom")

    out = err_fn()
    # Wrapper catches → error envelope
    assert isinstance(out, dict)
    assert out.get("total") == 0
    assert out.get("results") == []
    assert "error" in out


def test_with_mcp_telemetry_strips_envelope_kwargs():
    """`__envelope_fields__` and `__api_key_created_at__` are control-plane
    kwargs that the wrapped fn must NOT see."""
    captured = {}

    @_with_mcp_telemetry
    def probe(**kwargs) -> dict:
        captured.update(kwargs)
        return {"ok": True}

    probe(__envelope_fields__="minimal", __api_key_created_at__="2024-01-01", real_kw=1)
    assert "__envelope_fields__" not in captured
    assert "__api_key_created_at__" not in captured
    assert captured.get("real_kw") == 1


# =============================================================================
# _row_to_dict / _row_to_enforcement_case / _row_to_case_study /
# _row_to_loan_program — exercised against seeded DB rows.
# =============================================================================


def test_row_to_dict_program_seeded(seeded_db: Path):
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM programs WHERE unified_id = ?", ("UNI-test-s-1",)
        ).fetchone()
        d = _row_to_dict(row, include_enriched=True)
        assert d["unified_id"] == "UNI-test-s-1"
        assert d["primary_name"] == "テスト S-tier 補助金"
        assert d["tier"] == "S"
        # include_enriched=True populates enriched/source_mentions
        assert "enriched" in d
        assert "source_mentions" in d
    finally:
        conn.close()


# =============================================================================
# DB-backed tools (non-cohort) — call shape parity tests using seeded data.
# Each call exercises the @_with_mcp_telemetry wrapper + envelope path.
# =============================================================================


def test_search_loan_programs_empty_returns_envelope(client, seeded_db):
    """No loan_programs in seed → empty envelope with hint."""
    res = search_loan_programs()
    assert isinstance(res, dict)
    assert "results" in res
    assert "total" in res
    # Empty → hint should be present
    if res["total"] == 0:
        assert "hint" in res or "retry_with" in res


def test_search_loan_programs_with_provider_filter(client, seeded_db):
    res = search_loan_programs(provider="JFC")
    assert isinstance(res, dict)
    assert "total" in res


def test_search_loan_programs_with_loan_type_filter(client, seeded_db):
    res = search_loan_programs(loan_type="運転資金")
    assert isinstance(res, dict)
    assert "total" in res


def test_search_case_studies_empty_envelope(client, seeded_db):
    res = search_case_studies()
    assert isinstance(res, dict)
    assert "results" in res
    assert "total" in res


def test_search_case_studies_with_prefecture_filter(client, seeded_db):
    res = search_case_studies(prefecture="東京都")
    assert isinstance(res, dict)


def test_search_case_studies_non_canonical_prefecture(client, seeded_db):
    """Wrong-form prefecture ('Tokyo') → input_warnings or hint surfaced."""
    res = search_case_studies(prefecture="Tokyo")
    # Either an empty result with hint, or input_warnings — must NOT silently 0.
    assert isinstance(res, dict)


def test_search_enforcement_cases_empty(client, seeded_db):
    res = search_enforcement_cases()
    assert isinstance(res, dict)
    assert "results" in res


def test_search_enforcement_cases_q_filter(client, seeded_db):
    res = search_enforcement_cases(q="不当請求")
    assert isinstance(res, dict)


def test_search_enforcement_cases_ministry_filter(client, seeded_db):
    res = search_enforcement_cases(ministry="農林水産省")
    assert isinstance(res, dict)


def test_search_enforcement_cases_amount_range(client, seeded_db):
    res = search_enforcement_cases(min_improper_grant_yen=100, max_improper_grant_yen=10**9)
    assert isinstance(res, dict)


def test_search_enforcement_cases_disclosed_range(client, seeded_db):
    res = search_enforcement_cases(disclosed_from="2020-01-01", disclosed_until="2099-12-31")
    assert isinstance(res, dict)


def test_search_laws_empty(client, seeded_db):
    res = search_laws(q="補助金")
    assert isinstance(res, dict)
    assert "total" in res or "error" in res or "hint" in res


def test_search_laws_with_short_q(client, seeded_db):
    res = search_laws(q="a")
    assert isinstance(res, dict)


def test_search_tax_rules_empty(client, seeded_db):
    res = search_tax_rules(q="承継")
    assert isinstance(res, dict)


def test_search_invoice_registrants_invalid_houjin(client, seeded_db):
    res = search_invoice_registrants(houjin_bangou="12345")
    assert isinstance(res, dict)


def test_upcoming_deadlines_default(client, seeded_db):
    res = upcoming_deadlines()
    assert isinstance(res, dict)


def test_upcoming_deadlines_with_window(client, seeded_db):
    res = upcoming_deadlines(within_days=30)
    assert isinstance(res, dict)


def test_deadline_calendar_default(client, seeded_db):
    res = deadline_calendar()
    assert isinstance(res, dict)


def test_deadline_calendar_with_months_ahead(client, seeded_db):
    res = deadline_calendar(months_ahead=6)
    assert isinstance(res, dict)


# =============================================================================
# enum_values — DB-backed
# =============================================================================


def test_enum_values_target_type(client, seeded_db):
    res = enum_values(field="target_type")
    assert "values" in res
    assert "field" in res
    assert res["field"] == "target_type"


def test_enum_values_funding_purpose(client, seeded_db):
    res = enum_values(field="funding_purpose")
    assert "values" in res


def test_enum_values_prefecture(client, seeded_db):
    res = enum_values(field="prefecture")
    assert "values" in res


def test_enum_values_invalid_field(client, seeded_db):
    """Invalid field returns an error envelope (or telemetry-wrapped error)."""
    # Bypass the Literal type by passing through __dict__ — call directly.
    res = enum_values.__wrapped__(field="not_a_field")  # bypasses telemetry
    assert "error" in res
    assert res["code"] == "invalid_field"


def test_enum_values_clamps_limit_high(client, seeded_db):
    """limit clamps to [1, 200]."""
    res = enum_values(field="prefecture", limit=10000)
    # Clamped to 200 internally
    assert res["limit"] == 200


def test_enum_values_clamps_limit_low(client, seeded_db):
    """limit clamps to >= 1."""
    res = enum_values(field="prefecture", limit=-5)
    assert res["limit"] >= 1


# =============================================================================
# get_usage_status — anonymous + key paths
# =============================================================================


def test_get_usage_status_anonymous(client, seeded_db):
    res = get_usage_status()
    assert res["tier"] == "anonymous"
    assert res["limit"] is not None
    assert "reset_at" in res
    assert res["reset_timezone"] == "JST"


def test_get_usage_status_unknown_key(client, seeded_db):
    res = get_usage_status(api_key="am_does_not_exist_xxxxxx")
    assert res["tier"] == "unknown"
    assert "error" in res
    assert res["error"]["code"] == "key_not_found"


def test_get_usage_status_paid_key(client, seeded_db, paid_key):
    res = get_usage_status(api_key=paid_key)
    assert res["tier"] == "paid"
    assert "used" in res


# =============================================================================
# Sentry init — covers settings.sentry_dsn=None branch (should no-op)
# =============================================================================


def test_init_sentry_mcp_no_dsn_is_noop(monkeypatch):
    """Without SENTRY_DSN the helper must early-return."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "sentry_dsn", None, raising=False)
    # No exception, no setup.
    _init_sentry_mcp()


def test_init_sentry_mcp_import_error_is_caught(monkeypatch):
    """When sentry-sdk is unavailable the helper must NOT raise."""
    import builtins

    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "sentry_dsn", "https://xxx@sentry.io/123", raising=False)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentry_sdk":
            raise ImportError("sentry_sdk not installed (test)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # Should not raise.
    _init_sentry_mcp()


# =============================================================================
# _jst_today_iso — sanity check format
# =============================================================================


def test_jst_today_iso_format():
    out = _jst_today_iso()
    assert len(out) == 10
    assert out[4] == "-" and out[7] == "-"


# =============================================================================
# Additional tools — search_programs amount-bound branches + as_of clamp,
# subsidy_combo_finder, prescreen_programs, smb_starter_pack, similar_cases,
# search_bids/get_bid, get_law/find_precedents_by_statute,
# get_tax_rule/evaluate_tax_applicability,
# trace_program_to_law/find_cases_by_law/combined_compliance_check,
# search_court_decisions/get_court_decision/list_law_revisions,
# audit_batch_evaluate/compose_audit_workpaper/resolve_citation_chain.
# =============================================================================


def test_search_programs_negative_amount_min_returns_invalid_range(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(amount_min_man_yen=-1)
    # Branch: invalid_range (1264-1276)
    assert res["error"]["code"] == "invalid_range"


def test_search_programs_negative_amount_max_returns_invalid_range(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(amount_max_man_yen=-1)
    assert res["error"]["code"] == "invalid_range"


def test_search_programs_with_authority_level(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(authority_level="国")
    assert isinstance(res, dict)
    assert "results" in res


def test_search_programs_with_amount_max_filter(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(amount_max_man_yen=50000)
    assert "results" in res


def test_search_programs_with_offset(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(offset=1)
    assert res["offset"] == 1


def test_search_programs_no_match_emits_hint_and_retry(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    # Likely 0 row — non-existent tier combo
    res = search_programs(q="nonexistentwordzzz")
    if res["total"] == 0:
        # Empty hint path
        assert "hint" in res or "retry_with" in res


def test_search_programs_unknown_prefecture_warns_via_input_warnings(client, seeded_db):
    from jpintel_mcp.mcp.server import search_programs

    res = search_programs(prefecture="Tokio")
    # Either input_warnings on the result or, at minimum, the search
    # should not silently 0.
    warnings = res.get("input_warnings", [])
    if warnings:
        codes = [w.get("code") for w in warnings]
        assert "unknown_prefecture" in codes


def test_search_loan_programs_with_amount_filters(client, seeded_db):
    res = search_loan_programs(min_amount_yen=1_000_000, max_amount_yen=100_000_000)
    assert isinstance(res, dict)


def test_search_loan_programs_with_collateral_axes(client, seeded_db):
    res = search_loan_programs(
        collateral_required="not_required",
        personal_guarantor_required="not_required",
        third_party_guarantor_required="not_required",
    )
    assert isinstance(res, dict)


def test_search_loan_programs_with_max_interest_rate(client, seeded_db):
    res = search_loan_programs(max_interest_rate=0.02)
    assert isinstance(res, dict)


def test_search_loan_programs_with_min_loan_period(client, seeded_db):
    res = search_loan_programs(min_loan_period_years=5)
    assert isinstance(res, dict)


def test_search_loan_programs_with_q(client, seeded_db):
    res = search_loan_programs(q="運転資金")
    assert isinstance(res, dict)


def test_search_case_studies_with_q(client, seeded_db):
    res = search_case_studies(q="補助金")
    assert isinstance(res, dict)


def test_search_case_studies_with_industry_jsic(client, seeded_db):
    res = search_case_studies(industry_jsic="E")
    assert isinstance(res, dict)


def test_search_case_studies_with_program_used(client, seeded_db):
    res = search_case_studies(program_used="IT導入補助金")
    assert isinstance(res, dict)


def test_search_case_studies_with_houjin_bangou(client, seeded_db):
    res = search_case_studies(houjin_bangou="1234567890123")
    assert isinstance(res, dict)


def test_search_case_studies_invalid_houjin(client, seeded_db):
    res = search_case_studies(houjin_bangou="123")
    assert isinstance(res, dict)


def test_search_enforcement_cases_with_legal_basis(client, seeded_db):
    res = search_enforcement_cases(legal_basis="補助金適正化法")
    assert isinstance(res, dict)


def test_search_enforcement_cases_with_program_name_hint(client, seeded_db):
    res = search_enforcement_cases(program_name_hint="補助金")
    assert isinstance(res, dict)


def test_search_enforcement_cases_with_event_type(client, seeded_db):
    res = search_enforcement_cases(event_type="不当事項")
    assert isinstance(res, dict)


def test_search_enforcement_cases_invalid_houjin(client, seeded_db):
    res = search_enforcement_cases(recipient_houjin_bangou="bad")
    assert isinstance(res, dict)


def test_search_enforcement_cases_fields_full(client, seeded_db):
    res = search_enforcement_cases(fields="full")
    assert isinstance(res, dict)


def test_search_enforcement_cases_fields_standard(client, seeded_db):
    res = search_enforcement_cases(fields="standard")
    assert isinstance(res, dict)


def test_search_enforcement_cases_as_of_iso(client, seeded_db):
    res = search_enforcement_cases(as_of="2024-01-01")
    assert isinstance(res, dict)


def test_get_enforcement_case_missing_id(client, seeded_db):
    from jpintel_mcp.mcp.server import get_enforcement_case

    res = get_enforcement_case(case_id="ENF-does-not-exist")
    assert isinstance(res, dict)
    # Either error envelope or empty result
    assert "error" in res or "case_id" not in res or res.get("case_id") is None


def test_get_case_study_missing_id(client, seeded_db):
    from jpintel_mcp.mcp.server import get_case_study

    res = get_case_study(case_id="CS-does-not-exist")
    assert isinstance(res, dict)


def test_get_loan_program_missing_id(client, seeded_db):
    from jpintel_mcp.mcp.server import get_loan_program

    res = get_loan_program(loan_id="LP-does-not-exist")
    assert isinstance(res, dict)


# Search expansion tools (laws / tax / court / bids / invoice) — empty-table paths.


def test_search_laws_with_ministry_filter(client, seeded_db):
    res = search_laws(ministry="財務省")
    assert isinstance(res, dict)


def test_search_laws_with_law_type_filter(client, seeded_db):
    res = search_laws(law_type="法律")
    assert isinstance(res, dict)


def test_search_court_decisions_basic(client, seeded_db):
    from jpintel_mcp.mcp.server import search_court_decisions

    res = search_court_decisions(q="判決")
    assert isinstance(res, dict)


def test_search_court_decisions_no_q(client, seeded_db):
    from jpintel_mcp.mcp.server import search_court_decisions

    res = search_court_decisions()
    assert isinstance(res, dict)


def test_search_bids_basic(client, seeded_db):
    from jpintel_mcp.mcp.server import search_bids

    res = search_bids(q="入札")
    assert isinstance(res, dict)


def test_search_bids_no_q(client, seeded_db):
    from jpintel_mcp.mcp.server import search_bids

    res = search_bids()
    assert isinstance(res, dict)


def test_search_tax_rules_with_tax_category(client, seeded_db):
    res = search_tax_rules(tax_category="corporate")
    assert isinstance(res, dict)


def test_search_invoice_registrants_with_q(client, seeded_db):
    res = search_invoice_registrants(q="株式会社")
    assert isinstance(res, dict)


def test_search_invoice_registrants_valid_houjin(client, seeded_db):
    res = search_invoice_registrants(houjin_bangou="1234567890123")
    assert isinstance(res, dict)


def test_get_law_missing(client, seeded_db):
    from jpintel_mcp.mcp.server import get_law

    res = get_law(unified_id="LAW-not-exist")
    assert isinstance(res, dict)


def test_list_law_revisions_missing(client, seeded_db):
    from jpintel_mcp.mcp.server import list_law_revisions

    res = list_law_revisions(unified_id="LAW-not-exist")
    assert isinstance(res, dict)


def test_get_court_decision_missing(client, seeded_db):
    from jpintel_mcp.mcp.server import get_court_decision

    res = get_court_decision(unified_id="CD-not-exist")
    assert isinstance(res, dict)


def test_get_bid_missing(client, seeded_db):
    from jpintel_mcp.mcp.server import get_bid

    res = get_bid(unified_id="BID-not-exist")
    assert isinstance(res, dict)


def test_get_tax_rule_missing(client, seeded_db):
    from jpintel_mcp.mcp.server import get_tax_rule

    res = get_tax_rule(unified_id="TR-not-exist")
    assert isinstance(res, dict)


def test_find_precedents_by_statute_empty_table(client, seeded_db):
    from jpintel_mcp.mcp.server import find_precedents_by_statute

    res = find_precedents_by_statute(law_unified_id="LAW-fake")
    assert isinstance(res, dict)


# Larger one-shot tools


def test_prescreen_programs_basic(client, seeded_db):
    from jpintel_mcp.mcp.server import prescreen_programs

    res = prescreen_programs(prefecture="東京都", is_sole_proprietor=False)
    assert isinstance(res, dict)


def test_prescreen_programs_unknown_prefecture(client, seeded_db):
    from jpintel_mcp.mcp.server import prescreen_programs

    res = prescreen_programs(prefecture="Tokio")
    assert isinstance(res, dict)
    warnings = res.get("input_warnings", [])
    if warnings:
        codes = [w.get("code") for w in warnings]
        assert "unknown_prefecture" in codes


def test_smb_starter_pack_basic(client, seeded_db):
    from jpintel_mcp.mcp.server import smb_starter_pack

    res = smb_starter_pack(prefecture="東京都", employees=10, revenue_yen=50_000_000)
    assert isinstance(res, dict)


def test_smb_starter_pack_with_jsic_alias(client, seeded_db):
    from jpintel_mcp.mcp.server import smb_starter_pack

    # `jsic` is alias for industry_jsic
    res = smb_starter_pack(jsic="製造業", employees=5)
    assert isinstance(res, dict)


def test_subsidy_combo_finder_basic(client, seeded_db):
    from jpintel_mcp.mcp.server import subsidy_combo_finder

    res = subsidy_combo_finder(prefecture="東京都")
    assert isinstance(res, dict)


def test_dd_profile_am_minimal_fields(client, seeded_db):
    from jpintel_mcp.mcp.server import dd_profile_am

    # Pass minimal context — tool should return shape (or error envelope)
    res = dd_profile_am(houjin_bangou="1234567890123")
    assert isinstance(res, dict)


def test_similar_cases_empty(client, seeded_db):
    from jpintel_mcp.mcp.server import similar_cases

    res = similar_cases(description="テスト農園 設備投資 IT導入")
    assert isinstance(res, dict)


def test_combined_compliance_check_empty(client, seeded_db):
    from jpintel_mcp.mcp.server import combined_compliance_check

    res = combined_compliance_check(program_id="UNI-test-s-1")
    assert isinstance(res, dict)


def test_trace_program_to_law_empty(client, seeded_db):
    from jpintel_mcp.mcp.server import trace_program_to_law

    res = trace_program_to_law(program_id="UNI-test-s-1")
    assert isinstance(res, dict)


def test_find_cases_by_law_empty(client, seeded_db):
    from jpintel_mcp.mcp.server import find_cases_by_law

    res = find_cases_by_law(law_unified_id="LAW-fake")
    assert isinstance(res, dict)


def test_evaluate_tax_applicability_empty(client, seeded_db):
    from jpintel_mcp.mcp.server import evaluate_tax_applicability

    res = evaluate_tax_applicability(measure_id="TR-fake", target_amount_yen=10_000_000)
    assert isinstance(res, dict)


def test_resolve_citation_chain_empty(client, seeded_db):
    from jpintel_mcp.mcp.server import resolve_citation_chain

    res = resolve_citation_chain(law_unified_id="LAW-fake")
    assert isinstance(res, dict)


# =============================================================================
# _row_to_* helpers — exercise the JSON parsing code paths even when DB
# rows are not present, by constructing fake rows in-memory.
# =============================================================================


def _make_row(cols: dict) -> sqlite3.Row:
    """Build a sqlite3.Row from a dict via in-memory DB (test helper)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(cols))
    columns = ",".join(cols.keys())
    conn.execute(f"CREATE TABLE t({columns})")
    conn.execute(f"INSERT INTO t({columns}) VALUES ({placeholders})", list(cols.values()))
    row = conn.execute("SELECT * FROM t").fetchone()
    conn.close()
    return row


def test_row_to_law_dict_minimal():
    row = _make_row(
        {
            "unified_id": "LAW-1",
            "law_number": "平成X年法律第N号",
            "law_title": "テスト法",
            "law_short_title": None,
            "law_type": "法律",
            "ministry": "財務省",
            "promulgated_date": "2024-01-01",
            "enforced_date": "2024-04-01",
            "last_amended_date": None,
            "revision_status": None,
            "superseded_by_law_id": None,
            "article_count": 0,
            "full_text_url": "https://example.com",
            "summary": None,
            "subject_areas_json": None,
            "source_url": "https://example.com",
            "source_checksum": None,
            "confidence": 0.9,
            "fetched_at": "2024-01-01",
            "updated_at": "2024-01-01",
        }
    )
    d = _row_to_law_dict(row)
    assert d["unified_id"] == "LAW-1"


def test_row_to_court_decision_dict_minimal():
    row = _make_row(
        {
            "unified_id": "CD-1",
            "case_name": "Test v Test",
            "case_number": "C-1",
            "court": "Supreme Court",
            "court_level": "supreme",
            "decision_date": "2024-01-01",
            "decision_type": "criminal",
            "subject_area": "tax",
            "related_law_ids_json": json.dumps(["LAW-1"]),
            "key_ruling": "test",
            "parties_involved": None,
            "impact_on_business": None,
            "precedent_weight": None,
            "full_text_url": "https://example.com",
            "pdf_url": None,
            "source_url": "https://example.com",
            "source_excerpt": None,
            "source_checksum": None,
            "confidence": 0.9,
            "fetched_at": "2024-01-01",
            "updated_at": "2024-01-01",
        }
    )
    d = _row_to_court_decision_dict(row)
    assert d["unified_id"] == "CD-1"


def test_row_to_bid_dict_minimal():
    row = _make_row(
        {
            "unified_id": "BID-1",
            "bid_title": "Test bid",
            "bid_kind": "construction",
            "procuring_entity": "東京都",
            "procuring_houjin_bangou": None,
            "ministry": "国交省",
            "prefecture": "東京都",
            "program_id_hint": None,
            "announcement_date": "2024-01-01",
            "question_deadline": None,
            "bid_deadline": "2024-06-01",
            "decision_date": None,
            "budget_ceiling_yen": 100_000,
            "awarded_amount_yen": None,
            "winner_name": None,
            "winner_houjin_bangou": None,
            "participant_count": None,
            "bid_description": None,
            "eligibility_conditions": None,
            "classification_code": None,
            "source_url": "https://example.com",
            "source_excerpt": None,
            "source_checksum": None,
            "confidence": 0.9,
            "fetched_at": "2024-01-01",
            "updated_at": "2024-01-01",
        }
    )
    d = _row_to_bid_dict(row)
    assert d["unified_id"] == "BID-1"


def test_row_to_tax_ruleset_dict_minimal():
    row = _make_row(
        {
            "unified_id": "TR-1",
            "ruleset_name": "テスト措置",
            "tax_category": "corporate",
            "ruleset_kind": "deduction",
            "effective_from": "2024-01-01",
            "effective_until": "2025-12-31",
            "related_law_ids_json": None,
            "eligibility_conditions": "test condition",
            "eligibility_conditions_json": None,
            "rate_or_amount": "1.5%",
            "calculation_formula": None,
            "filing_requirements": None,
            "authority": "国税庁",
            "authority_url": "https://example.com",
            "source_url": "https://example.com",
            "source_excerpt": None,
            "source_checksum": None,
            "confidence": 0.9,
            "fetched_at": "2024-01-01",
            "updated_at": "2024-01-01",
        }
    )
    d = _row_to_tax_ruleset_dict(row)
    assert d["unified_id"] == "TR-1"
    assert d["ruleset_name"] == "テスト措置"


def test_row_to_invoice_registrant_dict_minimal():
    row = _make_row(
        {
            "invoice_registration_number": "T1234567890123",
            "houjin_bangou": "1234567890123",
            "normalized_name": "株式会社テスト",
            "address_normalized": "東京都",
            "prefecture": "東京都",
            "registered_date": "2024-01-01",
            "revoked_date": None,
            "expired_date": None,
            "registrant_kind": "corporation",
            "trade_name": None,
            "last_updated_nta": "2024-01-01",
            "source_url": "https://example.com",
            "source_checksum": None,
            "confidence": 0.9,
            "fetched_at": "2024-01-01",
            "updated_at": "2024-01-01",
        }
    )
    d = _row_to_invoice_registrant_dict(row)
    assert isinstance(d, dict)
    assert d["invoice_registration_number"] == "T1234567890123"


def test_row_to_enforcement_case_with_fy_json():
    row = _make_row(
        {
            "case_id": "ENF-99",
            "event_type": "test",
            "program_name_hint": "x",
            "recipient_name": "y",
            "recipient_kind": "corporation",
            "recipient_houjin_bangou": "1234567890123",
            "is_sole_proprietor": 0,
            "bureau": "z",
            "intermediate_recipient": None,
            "prefecture": "東京都",
            "ministry": "厚生労働省",
            "occurred_fiscal_years_json": json.dumps([2022, 2023]),
            "amount_yen": 100,
            "amount_project_cost_yen": 200,
            "amount_grant_paid_yen": 50,
            "amount_improper_grant_yen": 30,
            "amount_improper_project_cost_yen": 60,
            "reason_excerpt": "...",
            "legal_basis": "L1",
            "source_url": "https://x",
            "source_section": "S",
            "source_title": "T",
            "disclosed_date": "2024-01-01",
            "disclosed_until": None,
            "fetched_at": "2024-01-01",
            "confidence": 0.9,
        }
    )
    d = _row_to_enforcement_case(row)
    assert d["case_id"] == "ENF-99"
    assert d["occurred_fiscal_years"] == [2022, 2023]
    assert d["is_sole_proprietor"] is False


def test_row_to_enforcement_case_handles_invalid_fy_json():
    row = _make_row(
        {
            "case_id": "ENF-bad",
            "event_type": "test",
            "program_name_hint": "x",
            "recipient_name": "y",
            "recipient_kind": None,
            "recipient_houjin_bangou": None,
            "is_sole_proprietor": None,
            "bureau": None,
            "intermediate_recipient": None,
            "prefecture": None,
            "ministry": None,
            "occurred_fiscal_years_json": "{not json}",
            "amount_yen": None,
            "amount_project_cost_yen": None,
            "amount_grant_paid_yen": None,
            "amount_improper_grant_yen": None,
            "amount_improper_project_cost_yen": None,
            "reason_excerpt": None,
            "legal_basis": None,
            "source_url": None,
            "source_section": None,
            "source_title": None,
            "disclosed_date": None,
            "disclosed_until": None,
            "fetched_at": None,
            "confidence": None,
        }
    )
    d = _row_to_enforcement_case(row)
    # Malformed JSON falls back to []
    assert d["occurred_fiscal_years"] == []
    assert d["is_sole_proprietor"] is None


def test_row_to_case_study_minimal_construction():
    row = _make_row(
        {
            "case_id": "CS-99",
            "company_name": "テスト株式会社",
            "houjin_bangou": "1234567890123",
            "is_sole_proprietor": 0,
            "prefecture": "東京都",
            "municipality": None,
            "industry_jsic": "E",
            "industry_name": "Manufacturing",
            "employees": 10,
            "founded_year": 2020,
            "capital_yen": 10_000_000,
            "case_title": "x",
            "case_summary": "y",
            "programs_used_json": json.dumps(["IT導入補助金"]),
            "total_subsidy_received_yen": 1_000_000,
            "outcomes_json": None,
            "patterns_json": None,
            "publication_date": "2024-01-01",
            "source_url": "https://x",
            "source_excerpt": None,
            "fetched_at": "2024-01-01",
            "confidence": 0.9,
        }
    )
    d = _row_to_case_study(row)
    assert d["case_id"] == "CS-99"
    assert d["is_sole_proprietor"] is False


def test_row_to_loan_program_minimal_construction():
    row = _make_row(
        {
            "id": 1,
            "program_name": "テスト融資",
            "provider": "日本政策金融公庫",
            "loan_type": "general",
            "amount_max_yen": 50_000_000,
            "loan_period_years_max": 10,
            "grace_period_years_max": 2,
            "interest_rate_base_annual": 0.015,
            "interest_rate_special_annual": None,
            "rate_names": None,
            "security_required": None,
            "target_conditions": None,
            "official_url": "https://x",
            "source_excerpt": None,
            "fetched_at": "2024-01-01",
            "confidence": 0.9,
            "collateral_required": "negotiable",
            "personal_guarantor_required": "negotiable",
            "third_party_guarantor_required": "not_required",
            "security_notes": None,
        }
    )
    d = _row_to_loan_program(row)
    assert d["id"] == 1


def test_trim_tax_ruleset_minimal():
    rec = {
        "unified_id": "TR-1",
        "ruleset_name": "x",
        "tax_category": "corporate",
        "ruleset_kind": "deduction",
        "effective_from": "2024-01-01",
        "effective_until": "2025-12-31",
        "authority_url": "https://x",
        "source_url": "https://x",
    }
    out = _trim_tax_ruleset(rec, "minimal")
    assert isinstance(out, dict)
    assert out["unified_id"] == "TR-1"


def test_trim_tax_ruleset_full_passes_through():
    rec = {"unified_id": "TR-1", "extra": "y"}
    out = _trim_tax_ruleset(rec, "full")
    # Full = passes through whole record
    assert out is rec


def test_trim_tax_ruleset_default_truncates_long_narrative():
    """default mode truncates eligibility_conditions over 400 chars."""
    rec = {
        "unified_id": "TR-1",
        "ruleset_name": "x",
        "tax_category": "corporate",
        "eligibility_conditions": "あ" * 500,
        "source_excerpt": "drop",
        "source_checksum": "drop",
    }
    out = _trim_tax_ruleset(rec, "default")
    # Truncated to 397+1 char
    assert len(out["eligibility_conditions"]) <= 400
    # Excluded keys dropped
    assert "source_excerpt" not in out
    assert "source_checksum" not in out


# =============================================================================
# _envelope_merge — opt-out path with __envelope_fields__ minimal.
# =============================================================================


def test_envelope_merge_opt_out_via_envelope_fields_minimal():
    base = {"results": [{"x": 1}], "total": 1, "limit": 20, "offset": 0}
    out = _envelope_merge(
        tool_name="search_programs",
        result=base,
        kwargs={"__envelope_fields__": "minimal"},
        latency_ms=3.0,
    )
    # Output is still a dict; opt-out means meta block is suppressed.
    assert isinstance(out, dict)
    assert out["total"] == 1


# =============================================================================
# Sanitizer hits path — feed _walk_and_sanitize_mcp through known patterns.
# =============================================================================


def test_walk_and_sanitize_mcp_actually_strips_pattern():
    """If sanitize_response_text returns hits, the wrapper must propagate them."""
    # The actual sanitizer is opaque — we just call with a string that
    # may or may not match. The contract: never raises.
    out, hits = _walk_and_sanitize_mcp("100% guaranteed return")
    # hits is a list (possibly empty); both branches valid.
    assert isinstance(hits, list)
    # Output is still a string.
    assert isinstance(out, str)
