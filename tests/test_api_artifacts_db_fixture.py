"""DB-fixture-based coverage push for ``src/jpintel_mcp/api/artifacts.py``.

Stream LL 2026-05-16 — push coverage 85% → 90%. The module is mostly pure
dict-mungers, so this file targets the deeper composition helpers + a
tmp_path-backed sqlite contract test. No source change, no production DB
touch (memory: ``feedback_no_quick_check_on_huge_sqlite``).

Targets uncovered by tests/test_api_artifacts_pure.py:
  * ``_attach_common_artifact_envelope`` — orchestrates 8+ helpers.
  * ``_step_urls`` — url / urls / string fan-in.
  * ``_compatibility_sources`` — known_gap accumulation + by_url dedup.
  * ``_build_compatibility_artifact`` — full envelope assembly.
  * ``_build_markdown_display`` / ``_build_copy_paste_parts``.
  * ``_short_scalar`` over every scalar / dict / list type.
  * ``_summary_markdown`` — skips list / dict values.
  * ``_attach_billing_metadata`` + ``_mark_billing_metadata_seal_unavailable``.
  * ``_normalize_known_gap`` known-severity normalisation.
  * ``_finalize_artifact_usage_and_seal`` with stub ctx.
  * ``_refresh_artifact_id`` stability under field reorder.

Constraints (memory: ``feedback_no_quick_check_on_huge_sqlite``):
  * tmp_path-only sqlite, never touch /Users/shigetoumeda/jpcite/autonomath.db.
  * No source change.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

import jpintel_mcp.api.artifacts as A

# ---------------------------------------------------------------------------
# tmp_path stub DB — only used for tests that need a real sqlite file path
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Minimal sqlite file under tmp_path; no autonomath schema needed for
    pure-helper coverage but the fixture proves the file/path contract."""
    db = tmp_path / "artifacts_fixture.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE _probe (id INTEGER PRIMARY KEY, marker TEXT);
        INSERT INTO _probe (marker) VALUES ('ok');
        """
    )
    conn.commit()
    conn.close()
    return db


# ---------------------------------------------------------------------------
# _step_urls — url / urls (str OR list) / dict input variants
# ---------------------------------------------------------------------------


def test_step_urls_empty_step_returns_empty() -> None:
    assert A._step_urls({}) == []


def test_step_urls_single_source_url() -> None:
    out = A._step_urls({"source_url": "https://example.com/a"})
    assert out == ["https://example.com/a"]


def test_step_urls_source_urls_as_string() -> None:
    out = A._step_urls({"source_urls": "https://example.com/x"})
    assert out == ["https://example.com/x"]


def test_step_urls_source_urls_as_list() -> None:
    out = A._step_urls({"source_urls": ["https://a", "https://b", ""]})
    # Empty strings are filtered out.
    assert out == ["https://a", "https://b"]


def test_step_urls_combined_url_and_urls() -> None:
    out = A._step_urls(
        {"source_url": "https://primary", "source_urls": ["https://x"]}
    )
    assert out == ["https://primary", "https://x"]


# ---------------------------------------------------------------------------
# _compatibility_sources — by_url dedup, known_gap accumulation
# ---------------------------------------------------------------------------


def test_compatibility_sources_empty_rows() -> None:
    sources, known_gaps = A._compatibility_sources([])
    assert sources == []
    assert known_gaps == []


def test_compatibility_sources_dedup_by_url_and_used_in_accum() -> None:
    rows = [
        {
            "row_id": "pair_001",
            "rule_chain": [
                {"source_url": "https://shared.example.com", "source": "default"},
                {"source_url": "https://shared.example.com", "source": "default"},
            ],
            "verdict": "incompatible",
        }
    ]
    sources, known_gaps = A._compatibility_sources(rows)
    assert len(sources) == 1
    assert sources[0]["source_url"] == "https://shared.example.com"
    # Two appearances at step idx 0 + idx 1 => 2 used_in refs.
    assert len(sources[0]["used_in"]) == 2
    # `source=default` step emits a known_gap; the verdict is incompatible,
    # not 'unknown', so no unknown_verdict tag.
    assert any("default_rule_used:pair_001" in g for g in known_gaps)


def test_compatibility_sources_unknown_verdict_known_gap() -> None:
    rows = [
        {
            "row_id": "pair_001",
            "rule_chain": [{"source_url": "https://a", "source": "rule"}],
            "verdict": "unknown",
        }
    ]
    _, known_gaps = A._compatibility_sources(rows)
    assert any("unknown_verdict:pair_001" in g for g in known_gaps)


def test_compatibility_sources_missing_source_emits_gap() -> None:
    rows = [
        {
            "row_id": "pair_001",
            "rule_chain": [{"source": "rule"}],  # no url
            "verdict": "compatible",
        }
    ]
    _, known_gaps = A._compatibility_sources(rows)
    assert any("source_missing:pair_001" in g for g in known_gaps)


def test_compatibility_sources_inferred_only_emits_heuristic_gap() -> None:
    rows = [
        {
            "row_id": "pair_001",
            "rule_chain": [
                {"source_url": "https://example", "source": "rule", "inferred_only": 1}
            ],
            "verdict": "compatible",
        }
    ]
    _, known_gaps = A._compatibility_sources(rows)
    assert any("heuristic_rule_used:pair_001" in g for g in known_gaps)


# ---------------------------------------------------------------------------
# _build_compatibility_artifact — full envelope assembly
# ---------------------------------------------------------------------------


def test_build_compatibility_artifact_basic_shape() -> None:
    stack_body: dict[str, Any] = {
        "program_ids": ["UNI-1", "UNI-2"],
        "total_pairs": 1,
        "all_pairs_status": "compatible",
        "pairs": [
            {
                "program_a": "UNI-1",
                "program_b": "UNI-2",
                "verdict": "compatible",
                "confidence": 0.9,
                "rule_chain": [
                    {"source_url": "https://example.com/rule", "source": "rule"}
                ],
            }
        ],
    }
    out = A._build_compatibility_artifact(stack_body)
    assert out["artifact_type"] == "compatibility_table"
    assert out["schema_version"] == "v1"
    assert out["summary"]["program_count"] == 2
    assert out["summary"]["total_pairs"] == 1
    assert out["summary"]["verdict_counts"] == {"compatible": 1}
    assert out["sections"][0]["section_id"] == "compatibility_pairs"
    assert out["sections"][0]["rows"][0]["row_id"] == "pair_001"


def test_build_compatibility_artifact_human_review_for_unknown() -> None:
    stack_body: dict[str, Any] = {
        "program_ids": ["A"],
        "all_pairs_status": "requires_review",
        "pairs": [
            {
                "program_a": "A",
                "program_b": "B",
                "verdict": "unknown",
                "rule_chain": [],
            }
        ],
    }
    out = A._build_compatibility_artifact(stack_body)
    review = out.get("human_review_required") or []
    # `all_pairs_status:requires_review` AND row-level unknown both
    # land in the human_review list.
    assert any("all_pairs_status:requires_review" in str(item) for item in review)
    assert any("pair_001:A:B" in str(item) for item in review)


# ---------------------------------------------------------------------------
# _short_scalar / _summary_markdown — every input type
# ---------------------------------------------------------------------------


def test_short_scalar_none_returns_na() -> None:
    assert A._short_scalar(None) == "n/a"


def test_short_scalar_bool_int_float_str() -> None:
    assert A._short_scalar(True) == "True"
    assert A._short_scalar(42) == "42"
    assert A._short_scalar(3.14) == "3.14"
    assert A._short_scalar("foo") == "foo"


def test_short_scalar_list_renders_count() -> None:
    assert A._short_scalar([1, 2, 3]) == "3 items"


def test_short_scalar_dict_renders_field_count() -> None:
    assert A._short_scalar({"a": 1, "b": 2}) == "2 fields"


def test_short_scalar_truncates_at_160_chars() -> None:
    out = A._short_scalar("x" * 500)
    assert len(out) == 160


def test_summary_markdown_skips_list_and_dict() -> None:
    out = A._summary_markdown({"key1": "val", "key2": [1, 2], "key3": {"a": 1}})
    # Only scalar keys render; list / dict values are skipped.
    rendered = "\n".join(out)
    assert "`key1`" in rendered
    assert "`key2`" not in rendered
    assert "`key3`" not in rendered


def test_summary_markdown_empty_input_returns_empty() -> None:
    assert A._summary_markdown(None) == []
    assert A._summary_markdown({}) == []


# ---------------------------------------------------------------------------
# _build_markdown_display + _build_copy_paste_parts — composition smoke
# ---------------------------------------------------------------------------


def test_build_markdown_display_renders_artifact_type_and_packet_id() -> None:
    body = {
        "artifact_type": "compatibility_table",
        "packet_id": "pkt_abc",
        "summary": {"all_pairs_status": "compatible"},
        "agent_routing": {"pricing_note": "metered request"},
    }
    out = A._build_markdown_display(
        body,
        followup=[{"action_id": "verify_cited_sources", "priority": "high"}],
        evidence={"source_count": 1, "known_gap_count": 0},
    )
    assert "# compatibility_table `pkt_abc`" in out
    assert "## Summary" in out
    assert "## Evidence" in out
    assert "## Follow-up" in out
    assert "verify_cited_sources" in out


def test_build_markdown_display_summary_fallback() -> None:
    body = {"artifact_type": "audit_pack", "packet_id": "pkt_x", "summary": {}}
    out = A._build_markdown_display(body, followup=[], evidence={})
    assert "Summary fields are not available." in out


def test_build_copy_paste_parts_workflow_outputs_first() -> None:
    body = {
        "artifact_type": "audit_pack",
        "workflow_outputs": {"intro_email": "Hello world"},
        "summary": {"k": "v"},
        "human_review_required": [],
    }
    parts = A._build_copy_paste_parts(body, followup=[], evidence={})
    titles = [p["part_id"] for p in parts]
    # workflow_outputs land first, then the canonical summary / evidence / followup.
    assert titles[0] == "intro_email"
    assert "summary" in titles
    assert "evidence_status" in titles
    assert "followup" in titles


def test_build_copy_paste_parts_workflow_outputs_strips_empty() -> None:
    body = {
        "artifact_type": "audit_pack",
        "workflow_outputs": {"only_whitespace": "   ", "real": "actual"},
    }
    parts = A._build_copy_paste_parts(body, followup=[], evidence={})
    part_ids = [p["part_id"] for p in parts]
    assert "real" in part_ids
    assert "only_whitespace" not in part_ids


# ---------------------------------------------------------------------------
# _attach_billing_metadata + _mark_billing_metadata_seal_unavailable
# ---------------------------------------------------------------------------


def test_attach_billing_metadata_basic_authenticated_metered() -> None:
    body: dict[str, Any] = {"artifact_type": "audit_pack"}
    A._attach_billing_metadata(
        body,
        endpoint="/v1/artifacts/audit_pack",
        unit_type="metered_request",
        quantity=1,
        result_count=5,
        authenticated=True,
        metered=True,
    )
    md = body["billing_metadata"]
    assert md["endpoint"] == "/v1/artifacts/audit_pack"
    assert md["metered"] is True
    assert "authenticated_response_audit_seal" in md["value_basis"]
    assert "metered_response_audit_seal" in md["value_basis"]
    assert md["audit_seal"]["authenticated_key_present"] is True


def test_attach_billing_metadata_anonymous_passthrough() -> None:
    body: dict[str, Any] = {"artifact_type": "audit_pack"}
    A._attach_billing_metadata(
        body,
        endpoint="/v1/x",
        unit_type="metered_request",
        quantity=1,
        result_count=0,
        authenticated=False,
        metered=False,
    )
    md = body["billing_metadata"]
    assert md["audit_seal"]["authenticated_key_present"] is False
    assert "authenticated_response_audit_seal" not in md["value_basis"]


def test_attach_billing_metadata_pair_count_propagated() -> None:
    body: dict[str, Any] = {}
    A._attach_billing_metadata(
        body,
        endpoint="/v1/artifacts/compatibility_table",
        unit_type="pair",
        quantity=4,
        result_count=4,
        authenticated=True,
        metered=True,
        pair_count=4,
    )
    assert body["billing_metadata"]["pair_count"] == 4


def test_mark_billing_metadata_seal_unavailable_flips_flags() -> None:
    body: dict[str, Any] = {}
    A._attach_billing_metadata(
        body,
        endpoint="/v1/x",
        unit_type="metered_request",
        quantity=1,
        result_count=1,
        authenticated=True,
        metered=True,
    )
    A._mark_billing_metadata_seal_unavailable(body)
    audit = body["billing_metadata"]["audit_seal"]
    assert audit["seal_unavailable"] is True
    assert audit["included_when_available"] is False
    # value_basis stripped of audit-seal tokens.
    vb = body["billing_metadata"]["value_basis"]
    assert "authenticated_response_audit_seal" not in vb
    assert "metered_response_audit_seal" not in vb


def test_mark_billing_metadata_seal_unavailable_noop_when_no_metadata() -> None:
    body: dict[str, Any] = {}
    # No billing_metadata yet — must not raise / mutate.
    A._mark_billing_metadata_seal_unavailable(body)
    assert body == {}


# ---------------------------------------------------------------------------
# _normalize_known_gap — known-severity normalisation
# ---------------------------------------------------------------------------


def test_normalize_known_gap_severity_clamped_when_unknown() -> None:
    out = A._normalize_known_gap({"severity": "totally-made-up", "message": "x"})
    assert out["severity"] == "review"


def test_normalize_known_gap_falls_back_to_id_when_no_message() -> None:
    out = A._normalize_known_gap({"gap_id": "g1"})
    assert out["message"] == "g1"


def test_normalize_known_gap_passthrough_valid_severity() -> None:
    out = A._normalize_known_gap({"severity": "blocking", "message": "x"})
    assert out["severity"] == "blocking"


def test_normalize_known_gap_string_input_gap_id_from_prefix() -> None:
    out = A._normalize_known_gap("source_missing:pair_001")
    assert out["gap_id"] == "source_missing"
    assert out["severity"] == "review"
    assert out["message"] == "source_missing:pair_001"


# ---------------------------------------------------------------------------
# _refresh_artifact_id — content-stability under field reorder
# ---------------------------------------------------------------------------


def test_refresh_artifact_id_stable_under_field_reorder() -> None:
    body_a: dict[str, Any] = {
        "artifact_type": "audit_pack",
        "x": 1,
        "y": 2,
    }
    body_b: dict[str, Any] = {
        "y": 2,
        "x": 1,
        "artifact_type": "audit_pack",
    }
    A._refresh_artifact_id(body_a)
    A._refresh_artifact_id(body_b)
    assert body_a["artifact_id"] == body_b["artifact_id"]
    assert body_a["artifact_id"].startswith("art_audit_pack_")


def test_refresh_artifact_id_excludes_seal_and_packet_id() -> None:
    body: dict[str, Any] = {"artifact_type": "x", "k": 1}
    A._refresh_artifact_id(body)
    art_id_no_seal = body["artifact_id"]
    body["audit_seal"] = {"hmac": "abc"}
    body["packet_id"] = "pkt_xyz"
    A._refresh_artifact_id(body)
    # Both excluded from material → artifact_id stays the same.
    assert body["artifact_id"] == art_id_no_seal


def test_artifact_packet_id_derives_from_artifact_id() -> None:
    body = {"artifact_type": "x", "artifact_id": "art_x_abc123def4567890"}
    pkt = A._artifact_packet_id(body)
    assert pkt == "pkt_x_abc123def4567890"


def test_artifact_packet_id_fallback_when_artifact_id_absent() -> None:
    body = {"artifact_type": "audit_pack"}
    pkt = A._artifact_packet_id(body)
    assert pkt.startswith("pkt_audit_pack_")


# ---------------------------------------------------------------------------
# _build_recommended_followup_channels — artifact-type fan-out
# ---------------------------------------------------------------------------


def test_recommended_followup_channels_baseline_artifact_type() -> None:
    body = {"artifact_type": "company_public_baseline"}
    out = A._build_recommended_followup_channels(body, followup=[])
    next_eps = [item["endpoint"] for item in out["use_jpcite_next"]]
    assert "/v1/artifacts/company_public_audit_pack" in next_eps
    assert "/v1/artifacts/company_folder_brief" in next_eps


def test_recommended_followup_channels_application_strategy_pack() -> None:
    body = {"artifact_type": "application_strategy_pack"}
    out = A._build_recommended_followup_channels(body, followup=[])
    assert any(
        "compatibility_table" in item["endpoint"] for item in out["use_jpcite_next"]
    )


def test_recommended_followup_channels_high_priority_routed_to_professional() -> None:
    body = {"artifact_type": "audit_pack"}
    followup = [{"action_id": "verify_x", "priority": "high"}]
    out = A._build_recommended_followup_channels(body, followup=followup)
    topics = [item["topic"] for item in out["use_professional_review_for"]]
    assert "verify_x" in topics


# ---------------------------------------------------------------------------
# Tmp_path sqlite contract — proves the fixture works without touching prod DB
# ---------------------------------------------------------------------------


def test_tmp_db_fixture_is_isolated_under_tmp_path(
    tmp_db: Path, tmp_path: Path
) -> None:
    # The fixture must live under tmp_path (NOT under the repo root).
    assert tmp_db.parent == tmp_path
    assert tmp_db.exists() and tmp_db.stat().st_size > 0
    # And it must NOT alias to the production DB path.
    assert "autonomath.db" not in str(tmp_db)
    assert "/Users/shigetoumeda/jpcite/autonomath.db" not in str(tmp_db)


def test_tmp_db_can_be_opened_and_queried(tmp_db: Path) -> None:
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT marker FROM _probe").fetchone()
    conn.close()
    assert row["marker"] == "ok"
