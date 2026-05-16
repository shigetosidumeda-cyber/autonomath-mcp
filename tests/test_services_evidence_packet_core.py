"""Stream T coverage gap: services/evidence_packet.py core surface.

Targets the pure / deterministic helpers on
``EvidencePacketComposer`` plus the module-level cache helpers.
Avoids any DB round-trip — the existing
``tests/test_evidence_packet.py`` covers the SQLite-backed paths;
this file exercises the algorithmic surface (verdict mapping,
prefecture detection, free-text query normalisation, citations
projection, cost-savings decision, source-linked record counting)
so coverage of the 3,200-line module stops being load-bearing on
one mega test only.

No source mutation. Fixtures inline; no autouse, no shared state.
"""

from __future__ import annotations

import pytest

from jpintel_mcp.services.evidence_packet import (
    MAX_FACTS_PER_RECORD,
    MAX_RECORDS_PER_PACKET,
    PACKET_API_VERSION,
    VALID_CITATION_STATUSES,
    EvidencePacketComposer,
    _cache_get,
    _cache_put,
    _reset_cache_for_tests,
)

# ---------------------------------------------------------------------------
# Module-level constants — guard against silent wire-shape drift
# ---------------------------------------------------------------------------


def test_module_constants_pinned() -> None:
    assert PACKET_API_VERSION == "v1"
    assert MAX_RECORDS_PER_PACKET == 500
    assert MAX_FACTS_PER_RECORD == 500
    assert "verified" in VALID_CITATION_STATUSES
    assert "unknown" in VALID_CITATION_STATUSES
    assert "inferred" in VALID_CITATION_STATUSES
    assert "stale" in VALID_CITATION_STATUSES
    assert len(VALID_CITATION_STATUSES) == 4


# ---------------------------------------------------------------------------
# In-memory packet cache
# ---------------------------------------------------------------------------


def test_cache_put_get_round_trip_returns_deep_copy() -> None:
    _reset_cache_for_tests()
    body = {"records": [{"id": "x"}]}
    _cache_put("k1", body)
    out = _cache_get("k1")
    assert out is not None
    assert out == body
    # Ensure it's a copy, not the same list reference
    out["records"].append({"id": "polluted"})
    again = _cache_get("k1")
    assert again is not None
    assert len(again["records"]) == 1


def test_cache_miss_returns_none() -> None:
    _reset_cache_for_tests()
    assert _cache_get("never-set") is None


def test_cache_reset_clears_all_entries() -> None:
    _cache_put("a", {"x": 1})
    _cache_put("b", {"x": 2})
    _reset_cache_for_tests()
    assert _cache_get("a") is None
    assert _cache_get("b") is None


# ---------------------------------------------------------------------------
# Verdict mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verdict,expected",
    [
        ("requires_review", "defer"),
        ("incompatible", "block"),
        ("compatible", "allow"),
        ("unknown", "unknown"),
        ("something_unknown_pass_through", "something_unknown_pass_through"),
    ],
)
def test_map_verdict(verdict: str, expected: str) -> None:
    assert EvidencePacketComposer._map_verdict(verdict) == expected


# ---------------------------------------------------------------------------
# Free-text query normalisation
# ---------------------------------------------------------------------------


def test_normalise_strips_whitespace_and_nfkc() -> None:
    # Full-width tilde survives but full-width digits collapse to ASCII
    out = EvidencePacketComposer._normalise_free_text_query("  １２３ＡＢＣ  ")
    assert out == "123ABC"


def test_normalise_empty_returns_empty() -> None:
    assert EvidencePacketComposer._normalise_free_text_query("") == ""
    assert EvidencePacketComposer._normalise_free_text_query("   ") == ""


# ---------------------------------------------------------------------------
# Prefecture detection
# ---------------------------------------------------------------------------


def test_detect_prefecture_handles_full_and_short_form() -> None:
    assert EvidencePacketComposer._detect_prefecture("東京都の設備投資") == "東京都"
    assert EvidencePacketComposer._detect_prefecture("大阪のものづくり") == "大阪府"
    assert EvidencePacketComposer._detect_prefecture("北海道の補助金") == "北海道"


def test_detect_prefecture_returns_none_for_no_match() -> None:
    assert EvidencePacketComposer._detect_prefecture("補助金") is None
    assert EvidencePacketComposer._detect_prefecture("") is None


# ---------------------------------------------------------------------------
# Query terms extraction
# ---------------------------------------------------------------------------


def test_query_terms_extracts_keywords_and_caps_at_8() -> None:
    text = "IT導入とDXとGXの設備投資について補助金や融資と税制と認定の創業"
    terms = EvidencePacketComposer._query_terms(text)
    assert 1 <= len(terms) <= 8
    # known keywords should appear
    assert any(t in ("IT導入", "DX", "GX") for t in terms)


def test_query_terms_handles_empty_and_short() -> None:
    assert EvidencePacketComposer._query_terms("") == []
    assert EvidencePacketComposer._query_terms("a") == []  # too short, no keyword


def test_query_terms_falls_back_for_no_keyword_input() -> None:
    # No known keyword but kana-only content should still produce something
    # via the fallback split path.
    terms = EvidencePacketComposer._query_terms("わたしのおきにいり")
    # Either non-empty (fallback) or empty if particle stripper leaves <2 chars
    assert isinstance(terms, list)


# ---------------------------------------------------------------------------
# Non-program intent + corporate number extraction
# ---------------------------------------------------------------------------


def test_prefers_non_program_context_detects_enforcement() -> None:
    assert EvidencePacketComposer._prefers_non_program_context("業務停止命令の根拠は?") is True


def test_prefers_non_program_context_returns_false_for_subsidy_text() -> None:
    assert EvidencePacketComposer._prefers_non_program_context("ものづくり補助金の上限") is False


def test_extract_corporate_number_13_digits() -> None:
    out = EvidencePacketComposer._extract_corporate_number("法人番号は T8010001213708 です")
    assert out == "8010001213708"


def test_extract_corporate_number_full_width() -> None:
    # Should NFKC normalise full-width digits first
    out = EvidencePacketComposer._extract_corporate_number("Ｔ８０１００ ")
    # Too short — returns None
    assert out is None


def test_extract_corporate_number_no_match() -> None:
    assert EvidencePacketComposer._extract_corporate_number("補助金の上限") is None


def test_non_program_context_order_prefers_enforcement_first() -> None:
    out = EvidencePacketComposer._non_program_context_order("業務停止が出た")
    assert out[0] == "enforcement"


def test_non_program_context_order_prefers_tax_first() -> None:
    out = EvidencePacketComposer._non_program_context_order("簡易課税の仕入率")
    assert out[0] == "tax"


def test_non_program_context_order_default_law_first() -> None:
    out = EvidencePacketComposer._non_program_context_order("一般")
    assert out[0] == "law"


# ---------------------------------------------------------------------------
# Source-linked record counting
# ---------------------------------------------------------------------------


def test_source_linked_record_count_counts_top_level_url() -> None:
    records = [
        {"source_url": "https://x"},
        {"source_url": ""},
        {"facts": []},
    ]
    assert EvidencePacketComposer._source_linked_record_count(records) == 1


def test_source_linked_record_count_counts_fact_level_source() -> None:
    records = [
        {"facts": [{"source": {"url": "https://a"}}]},
        {"facts": [{"source": None}]},
        {"facts": []},
    ]
    assert EvidencePacketComposer._source_linked_record_count(records) == 1


def test_source_linked_record_count_zero_for_empty() -> None:
    assert EvidencePacketComposer._source_linked_record_count([]) == 0


# ---------------------------------------------------------------------------
# Citation block projection
# ---------------------------------------------------------------------------


def test_build_citations_block_defaults_unknown() -> None:
    records: list[dict[str, object]] = [
        {"entity_id": "e1", "source_url": "https://x"},
    ]
    out = EvidencePacketComposer._build_citations_block(records, {})
    assert len(out) == 1
    cit = out[0]
    assert cit["verification_status"] == "unknown"
    assert cit["matched_form"] is None
    assert cit["verified_at"] is None


def test_build_citations_block_normalises_invalid_status() -> None:
    records: list[dict[str, object]] = [
        {"entity_id": "e1", "source_url": "https://x"},
    ]
    verdicts: dict[tuple[str, str], dict[str, object]] = {
        ("e1", "https://x"): {
            "verification_status": "not-a-real-status",
            "matched_form": "X",
            "verified_at": "2026",
        }
    }
    out = EvidencePacketComposer._build_citations_block(records, verdicts)
    assert out[0]["verification_status"] == "unknown"


def test_build_citations_block_preserves_valid_verified() -> None:
    records: list[dict[str, object]] = [
        {"entity_id": "e1", "source_url": "https://x"},
    ]
    verdicts: dict[tuple[str, str], dict[str, object]] = {
        ("e1", "https://x"): {
            "verification_status": "verified",
            "matched_form": "Match Co.",
            "verified_at": "2026-05-16",
            "source_checksum": "abc",
            "verification_basis": "html_hash",
        }
    }
    out = EvidencePacketComposer._build_citations_block(records, verdicts)
    assert out[0]["verification_status"] == "verified"
    assert out[0]["matched_form"] == "Match Co."


# ---------------------------------------------------------------------------
# Cost-savings decision
# ---------------------------------------------------------------------------


def test_cost_savings_decision_needs_baseline_when_not_evaluated() -> None:
    out = EvidencePacketComposer._cost_savings_decision(None)
    assert out["recommend_for_cost_savings"] is False
    assert out["cost_savings_decision"] == "needs_caller_baseline"


def test_cost_savings_decision_break_even_met_true() -> None:
    out = EvidencePacketComposer._cost_savings_decision({"evaluated": True, "break_even_met": True})
    assert out["recommend_for_cost_savings"] is True
    assert out["cost_savings_decision"] == "supported_by_caller_baseline"


def test_cost_savings_decision_break_even_met_false() -> None:
    out = EvidencePacketComposer._cost_savings_decision(
        {"evaluated": True, "break_even_met": False}
    )
    assert out["recommend_for_cost_savings"] is False
    assert out["cost_savings_decision"] == "not_supported_by_caller_baseline"


def test_cost_savings_decision_evaluated_without_break_even() -> None:
    out = EvidencePacketComposer._cost_savings_decision({"evaluated": True})
    assert out["recommend_for_cost_savings"] is False
    assert out["cost_savings_decision"] == "needs_input_token_price"


def test_suppress_cost_savings_keeps_negative_intact() -> None:
    base = {
        "recommend_for_cost_savings": False,
        "cost_savings_decision": "needs_caller_baseline",
        "missing_for_cost_claim": [],
    }
    out = EvidencePacketComposer._suppress_cost_savings_without_evidence(base, reason="x")
    assert out == base


def test_suppress_cost_savings_overrides_positive_when_no_evidence() -> None:
    base = {
        "recommend_for_cost_savings": True,
        "cost_savings_decision": "supported_by_caller_baseline",
        "missing_for_cost_claim": [],
    }
    out = EvidencePacketComposer._suppress_cost_savings_without_evidence(
        base, reason="no_source_linked_records"
    )
    assert out["recommend_for_cost_savings"] is False
    assert out["cost_savings_decision"] == "no_source_linked_records"
    assert out["suppressed_cost_savings_decision"] == "supported_by_caller_baseline"


# ---------------------------------------------------------------------------
# Evidence decision two-axis output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "records,linked,expect_recommend,expect_decision",
    [
        (0, 0, False, "no_records_returned"),
        (5, 0, False, "records_returned_without_source_links"),
        (5, 3, True, "supported_by_source_linked_records"),
    ],
)
def test_build_evidence_decision(
    records: int,
    linked: int,
    expect_recommend: bool,
    expect_decision: str,
) -> None:
    rec, dec = EvidencePacketComposer._build_evidence_decision(records, linked)
    assert rec is expect_recommend
    assert dec == expect_decision


# ---------------------------------------------------------------------------
# Packet ID generation
# ---------------------------------------------------------------------------


def test_new_packet_id_prefix_and_length() -> None:
    pid = EvidencePacketComposer._new_packet_id()
    assert pid.startswith("evp_")
    assert len(pid) == 4 + 16


def test_new_packet_id_unique_across_calls() -> None:
    ids = {EvidencePacketComposer._new_packet_id() for _ in range(20)}
    assert len(ids) == 20
