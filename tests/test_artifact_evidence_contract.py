from __future__ import annotations

import json
import sqlite3
from typing import Any

from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.artifacts import (
    _attach_common_artifact_envelope,
    _build_compatibility_artifact,
    _refresh_artifact_id,
    _stable_artifact_id,
)


def test_common_artifact_envelope_is_additive_and_source_linked() -> None:
    body: dict[str, Any] = {
        "artifact_id": "art_compatibility_table_abc123",
        "artifact_type": "compatibility_table",
        "summary": {"total_pairs": 1, "all_pairs_status": "requires_review"},
        "sections": [{"section_id": "compatibility_pairs", "rows": []}],
        "sources": [
            {
                "source_url": "https://example.test/rule",
                "source_kind": "exclusion_rules",
                "used_in": ["sections[0].rows[0]"],
            }
        ],
        "known_gaps": ["source_missing:pair_001"],
    }

    artifact_id = body["artifact_id"]
    _attach_common_artifact_envelope(body)

    assert body["artifact_id"] == artifact_id
    assert "billing_metadata" not in body
    assert body["packet_id"] == "pkt_compatibility_table_abc123"
    assert body["_evidence"]["source_count"] == 1
    assert body["_evidence"]["source_refs"][0]["source_url"] == "https://example.test/rule"
    assert body["_evidence"]["known_gap_count"] == 2
    assert all(isinstance(gap, dict) for gap in body["known_gaps"])
    source_gap = next(gap for gap in body["known_gaps"] if gap.get("gap_id") == "source_missing")
    assert source_gap["severity"] == "review"
    assert source_gap["message"] == "source_missing:pair_001"
    assert source_gap["source_fields"] == ["known_gaps"]
    assert "source_missing" in body["_evidence"]["known_gap_refs"]
    assert any(
        isinstance(gap, dict) and gap.get("gap_id") == "source_receipt_missing_fields"
        for gap in body["known_gaps"]
    )
    assert body["billing_note"] == body["agent_routing"]["pricing_note"]
    assert body["copy_paste_parts"]
    assert body["markdown_display"].startswith("# compatibility_table")
    assert body["recommended_followup"]


def test_common_artifact_envelope_adds_claim_coverage_gaps_without_changing_id() -> None:
    body: dict[str, Any] = {
        "artifact_id": "art_application_strategy_pack_claims",
        "artifact_type": "application_strategy_pack",
        "summary": {"candidate_count": 2},
        "sections": [
            {
                "section_id": "ranked_candidates",
                "rows": [
                    {
                        "unified_id": "UNI-source-linked",
                        "recommendation": "primary_candidate",
                        "match_reasons": ["fits profile"],
                        "source_url": "https://example.test/program/source-linked",
                    },
                    {
                        "unified_id": "UNI-unsupported",
                        "recommendation": "review_first",
                        "match_reasons": ["profile match without source"],
                    },
                ],
            }
        ],
        "sources": [
            {
                "source_url": "https://example.test/program/source-linked",
                "used_in": ["sections[0].rows[0].source_url"],
            }
        ],
        "known_gaps": [],
    }

    artifact_id = body["artifact_id"]
    _attach_common_artifact_envelope(body)

    assert body["artifact_id"] == artifact_id
    claim_coverage = body["_evidence"]["claim_coverage"]
    assert claim_coverage["claim_count"] == 2
    assert claim_coverage["source_linked_claim_count"] == 1
    assert claim_coverage["unsupported_claim_count"] == 1
    assert any(
        gap.get("gap_id") == "unsupported_claim"
        and gap.get("section") == "ranked_candidates"
        and gap.get("row_ref") == "UNI-unsupported"
        and gap.get("severity") == "warning"
        for gap in body["known_gaps"]
    )


def test_copy_surfaces_do_not_emit_prohibited_certainty_terms() -> None:
    body: dict[str, Any] = {
        "artifact_id": "art_houjin_dd_pack_def456",
        "artifact_type": "houjin_dd_pack",
        "summary": {"houjin_bangou": "1234567890123"},
        "sections": [],
        "sources": [],
        "known_gaps": [
            {
                "gap_id": "empty_enforcement",
                "section": "enforcement",
                "message": "空欄は安全性の証明ではありません。",
            }
        ],
    }

    _attach_common_artifact_envelope(body)

    copy_surfaces = {
        "copy_paste_parts": body["copy_paste_parts"],
        "markdown_display": body["markdown_display"],
        "recommended_followup": body["recommended_followup"],
    }
    rendered = json.dumps(copy_surfaces, ensure_ascii=False)
    for term in ("安全", "処分なし", "申請可", "監査済み"):
        assert term not in rendered


def test_compatibility_table_artifact_id_includes_corpus_snapshot() -> None:
    body = _build_compatibility_artifact(
        {
            "program_ids": ["p1", "p2"],
            "total_pairs": 1,
            "all_pairs_status": "requires_review",
            "pairs": [
                {
                    "program_a": "p1",
                    "program_b": "p2",
                    "verdict": "requires_review",
                    "confidence": 0.5,
                    "rule_chain": [],
                }
            ],
        }
    )
    display_only_id = body["artifact_id"]

    conn = sqlite3.connect(":memory:")
    try:
        attach_corpus_snapshot(body, conn)
    finally:
        conn.close()
    _refresh_artifact_id(body)

    assert body["corpus_snapshot_id"]
    assert body["corpus_checksum"]
    assert body["artifact_id"] != display_only_id
    material = {
        key: value
        for key, value in body.items()
        if key not in {"artifact_id", "audit_seal", "packet_id"}
    }
    assert body["artifact_id"] == _stable_artifact_id(
        "compatibility_table",
        material,
    )
