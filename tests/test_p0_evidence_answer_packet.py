from __future__ import annotations

from jpintel_mcp.services.packets.evidence_answer import (
    PACKET_SCHEMA_VERSION,
    compose_evidence_answer_packet,
)


def test_evidence_answer_packet_is_inline_only_and_receipt_backed() -> None:
    packet = compose_evidence_answer_packet("この制度の根拠を確認したい")

    assert packet["schema_version"] == PACKET_SCHEMA_VERSION
    assert packet["packet_kind"] == "evidence_answer"
    assert packet["outcome_contract_id"] == "evidence_answer"
    assert packet["question"] == "この制度の根拠を確認したい"
    assert packet["answer"]["text"].startswith("Deterministic answer placeholder")
    assert packet["billable"] is False
    assert packet["charge_status"] == "not_charged"
    assert packet["accepted_artifact_created"] is False
    assert packet["paid_packet_body_materialized"] is False
    assert packet["request_time_llm_call_performed"] is False
    assert packet["live_source_fetch_performed"] is False
    assert packet["live_aws_dependency_used"] is False
    assert packet["receipt_ledger"]["public_claims_release_allowed"] is True
    assert packet["receipt_ledger"]["issues"] == []
    assert packet["no_hit_semantics"]["absence_claim_enabled"] is False


def test_evidence_answer_packet_limits_question_without_affecting_claims() -> None:
    packet = compose_evidence_answer_packet("x" * 800)

    assert len(packet["question"]) == 500
    assert all(claim["visibility"] == "public" for claim in packet["claims"])
