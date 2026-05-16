"""Pure-function coverage tests for ``api.artifacts`` private helpers.

Targets ``src/jpintel_mcp/api/artifacts.py`` (2,971 stmt). The module
emits deterministic artifacts (DD pack, application strategy, audit pack
etc.) and a fan of pure helpers do envelope assembly, source-receipt
quality grading, known-gap normalization, and claim-coverage walking.

NO DB / HTTP / LLM calls. Pure function I/O over dict bodies.

Stream CC tick (coverage 76% → 80% target).
"""

from __future__ import annotations

from typing import Any

import jpintel_mcp.api.artifacts as a

# ---------------------------------------------------------------------------
# _utc_now_iso
# ---------------------------------------------------------------------------


def test_utc_now_iso_ends_with_offset() -> None:
    ts = a._utc_now_iso()
    # datetime.now(UTC).replace(microsecond=0).isoformat() ends with +00:00.
    assert ts.endswith("+00:00")
    # Format check: YYYY-MM-DDTHH:MM:SS+00:00 = 25 chars.
    assert len(ts) == len("2026-01-01T00:00:00+00:00")


# ---------------------------------------------------------------------------
# _stable_artifact_id / _refresh_artifact_id / _artifact_packet_id
# ---------------------------------------------------------------------------


def test_stable_artifact_id_is_deterministic() -> None:
    payload = {"foo": "bar", "n": 1}
    out_a = a._stable_artifact_id("dd_pack", payload)
    out_b = a._stable_artifact_id("dd_pack", payload)
    assert out_a == out_b
    assert out_a.startswith("art_dd_pack_")


def test_stable_artifact_id_differs_on_payload_change() -> None:
    out_a = a._stable_artifact_id("dd_pack", {"foo": "bar"})
    out_b = a._stable_artifact_id("dd_pack", {"foo": "baz"})
    assert out_a != out_b


def test_refresh_artifact_id_excludes_seal_and_billing() -> None:
    body: dict[str, Any] = {
        "artifact_type": "dd_pack",
        "summary": {"x": 1},
        "audit_seal": {"sig": "abcd"},
        "billing_metadata": {"endpoint": "/v1/x"},
        "packet_id": "pkt_old",
    }
    a._refresh_artifact_id(body)
    body_copy = {**body}
    body_copy["audit_seal"] = {"sig": "completely_different"}
    body_copy["billing_metadata"] = {"endpoint": "/v1/y"}
    body_copy["packet_id"] = "pkt_other"
    # Refreshing again should produce identical artifact_id — those fields
    # are excluded from the content-identity material.
    original_id = body["artifact_id"]
    a._refresh_artifact_id(body_copy)
    assert body_copy["artifact_id"] == original_id


def test_artifact_packet_id_derives_from_artifact_id() -> None:
    body = {"artifact_type": "dd_pack", "artifact_id": "art_dd_pack_1234567890abcdef"}
    out = a._artifact_packet_id(body)
    assert out == "pkt_dd_pack_1234567890abcdef"


def test_artifact_packet_id_falls_back_when_no_art_prefix() -> None:
    body = {"artifact_type": "dd_pack", "artifact_id": "weirdformat"}
    out = a._artifact_packet_id(body)
    assert out.startswith("pkt_")


# ---------------------------------------------------------------------------
# _source_refs / _source_receipts / _source_receipt_completion
# ---------------------------------------------------------------------------


def test_source_refs_extracts_url_only_entries() -> None:
    body = {
        "sources": [
            {"source_url": "https://example.com/a", "source_kind": "ministry"},
            {"source_url": "", "source_kind": "noise"},
            "not_a_dict",
            {"source_kind": "no_url"},
        ]
    }
    refs = a._source_refs(body)
    assert len(refs) == 1
    assert refs[0]["source_url"] == "https://example.com/a"


def test_source_receipts_emits_stable_ids() -> None:
    body = {
        "sources": [
            {
                "source_url": "https://example.com/a",
                "source_kind": "ministry",
                "source_fetched_at": "2026-01-01T00:00:00+00:00",
                "content_hash": "abc",
                "license": "cc_by",
                "used_in": ["section_a"],
            },
        ]
    }
    r = a._source_receipts(body)
    assert len(r) == 1
    assert r[0]["source_receipt_id"].startswith("sr_")
    assert r[0]["content_hash"] == "abc"
    assert r[0]["license"] == "cc_by"


def test_source_receipts_uses_alternate_field_names() -> None:
    body = {
        "sources": [
            {
                "source_url": "https://example.com/x",
                "kind": "ministry",
                "fetched_at": "2026-01-01",
                "source_checksum": "sumA",
                "license_or_terms": "cc_by",
            },
        ]
    }
    r = a._source_receipts(body)
    assert r[0]["source_kind"] == "ministry"
    assert r[0]["source_fetched_at"] == "2026-01-01"
    assert r[0]["content_hash"] == "sumA"
    assert r[0]["license"] == "cc_by"


def test_source_receipt_completion_empty() -> None:
    out = a._source_receipt_completion([])
    assert out == {"total": 0, "complete": 0, "incomplete": 0}


def test_source_receipt_completion_partial() -> None:
    receipts = [
        {
            "source_url": "https://x",
            "source_fetched_at": "2026-01-01",
            "content_hash": "abc",
            "license": "cc",
            "used_in": ["s_a"],
        },
        # incomplete: missing license + used_in
        {"source_url": "https://y", "source_fetched_at": "2026-01-01"},
    ]
    out = a._source_receipt_completion(receipts)
    assert out["total"] == 2
    assert out["complete"] == 1
    assert out["incomplete"] == 1


# ---------------------------------------------------------------------------
# _gap_id_from_text / _normalize_source_fields / _normalize_known_gap(s)
# ---------------------------------------------------------------------------


def test_gap_id_from_text_takes_prefix_before_colon() -> None:
    assert a._gap_id_from_text("source_missing: row_007") == "source_missing"


def test_gap_id_from_text_empty_falls_back() -> None:
    assert a._gap_id_from_text("") == "known_gap"


def test_normalize_source_fields_handles_list_filter_empty() -> None:
    out = a._normalize_source_fields(["a", "", None, "b"])
    assert out == ["a", "b"]


def test_normalize_source_fields_handles_string() -> None:
    assert a._normalize_source_fields("only_one") == ["only_one"]


def test_normalize_source_fields_handles_other_returns_empty() -> None:
    assert a._normalize_source_fields(None) == []
    assert a._normalize_source_fields(42) == []


def test_normalize_known_gap_string_input() -> None:
    out = a._normalize_known_gap("source_missing: needs URL")
    assert out["gap_id"] == "source_missing"
    assert out["severity"] == "review"
    assert "needs URL" in out["message"]


def test_normalize_known_gap_dict_with_invalid_severity_falls_back() -> None:
    out = a._normalize_known_gap({"gap_id": "g1", "severity": "extreme"})
    assert out["severity"] == "review"


def test_normalize_known_gap_dict_with_valid_severity_preserved() -> None:
    out = a._normalize_known_gap({"gap_id": "g1", "severity": "blocking"})
    assert out["severity"] == "blocking"


def test_normalize_known_gaps_replaces_non_list_with_empty() -> None:
    body: dict[str, Any] = {"known_gaps": "not_a_list"}
    a._normalize_known_gaps(body)
    assert body["known_gaps"] == []


def test_normalize_known_gaps_normalises_each_entry() -> None:
    body: dict[str, Any] = {"known_gaps": ["raw_text_gap", {"gap_id": "g2"}]}
    a._normalize_known_gaps(body)
    assert len(body["known_gaps"]) == 2
    assert body["known_gaps"][0]["gap_id"] == "raw_text_gap"
    assert body["known_gaps"][1]["gap_id"] == "g2"


# ---------------------------------------------------------------------------
# _contains_http_url / _row_has_source_hint / _row_ref / _row_claim_fields
# ---------------------------------------------------------------------------


def test_contains_http_url_true_for_string_url() -> None:
    assert a._contains_http_url("https://example.com") is True
    assert a._contains_http_url("http://x") is True


def test_contains_http_url_false_for_plain_text() -> None:
    assert a._contains_http_url("plain text") is False


def test_contains_http_url_traverses_dict_and_list() -> None:
    assert a._contains_http_url({"x": ["https://example.com"]}) is True
    assert a._contains_http_url([{"y": {"z": "https://e.com"}}]) is True


def test_row_has_source_hint_picks_up_source_url() -> None:
    assert a._row_has_source_hint({"source_url": "https://x.com"}) is True


def test_row_has_source_hint_returns_false_without_url() -> None:
    assert a._row_has_source_hint({"verdict": "ok"}) is False


def test_row_ref_prefers_row_id_then_unified_id_then_fallback() -> None:
    assert a._row_ref({"row_id": "r1"}, "fb") == "r1"
    assert a._row_ref({"unified_id": "UNI-1"}, "fb") == "UNI-1"
    assert a._row_ref({}, "row_003") == "row_003"


def test_row_claim_fields_returns_present_fields() -> None:
    row = {"verdict": "ok", "recommendation": "go", "unrelated": 1}
    out = a._row_claim_fields(row)
    assert "verdict" in out
    assert "recommendation" in out
    assert "unrelated" not in out


def test_row_claim_fields_skips_empty_values() -> None:
    row = {"verdict": "", "recommendation": []}
    out = a._row_claim_fields(row)
    assert out == []


# ---------------------------------------------------------------------------
# _build_recommended_followup / _build_agent_routing
# ---------------------------------------------------------------------------


def test_build_recommended_followup_emits_confirm_action_always() -> None:
    out = a._build_recommended_followup({})
    ids = [item["action_id"] for item in out]
    assert "confirm_target_and_date" in ids


def test_build_recommended_followup_adds_resolve_gap_when_present() -> None:
    body = {"known_gaps": [{"gap_id": "g1"}]}
    out = a._build_recommended_followup(body)
    ids = [item["action_id"] for item in out]
    assert "resolve_known_gaps" in ids


def test_build_agent_routing_company_branch() -> None:
    out = a._build_agent_routing({"artifact_type": "company_public_baseline"})
    assert "Japanese company public-record research" in out["call_jpcite_first_for"]


def test_build_agent_routing_default_branch() -> None:
    out = a._build_agent_routing({"artifact_type": "application_strategy_pack"})
    assert "Japanese public program research" in out["call_jpcite_first_for"]


def test_build_agent_routing_includes_no_llm_marker() -> None:
    out = a._build_agent_routing({"artifact_type": "x"})
    assert out["no_llm_called_by_jpcite"] is True


# ---------------------------------------------------------------------------
# _build_artifact_evidence
# ---------------------------------------------------------------------------


def test_build_artifact_evidence_counts_sources_and_gaps() -> None:
    body = {
        "sources": [
            {"source_url": "https://e.com/a", "used_in": ["s_a"]},
        ],
        "known_gaps": [{"gap_id": "g1"}],
    }
    out = a._build_artifact_evidence(body)
    assert out["source_count"] == 1
    assert out["known_gap_count"] == 1
    # Basis fields are always present.
    assert "sources" in out["basis_fields"]


# ---------------------------------------------------------------------------
# _build_billing_metadata / _mark_billing_metadata_seal_unavailable
# ---------------------------------------------------------------------------


def test_build_billing_metadata_includes_value_basis() -> None:
    out = a._build_billing_metadata(
        {"source_receipts": [{"x": 1}]},
        endpoint="/v1/artifacts/x",
        unit_type="artifact",
        quantity=1,
        result_count=1,
        strict_metering=True,
        metered=True,
        authenticated=True,
    )
    assert out["quantity"] == 1
    assert out["metered"] is True
    assert "deterministic_artifact" in out["value_basis"]
    assert "source_receipts" in out["value_basis"]


def test_mark_billing_metadata_seal_unavailable_strips_authenticated_basis() -> None:
    body: dict[str, Any] = {
        "billing_metadata": {
            "value_basis": [
                "deterministic_artifact",
                "authenticated_response_audit_seal",
                "metered_response_audit_seal",
            ],
            "audit_seal": {"authenticated_key_present": True},
        }
    }
    a._mark_billing_metadata_seal_unavailable(body)
    assert "authenticated_response_audit_seal" not in body["billing_metadata"]["value_basis"]
    assert body["billing_metadata"]["audit_seal"]["seal_unavailable"] is True
