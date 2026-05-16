from __future__ import annotations

from jpintel_mcp.services.packets.source_receipt_ledger import (
    PACKET_SCHEMA_VERSION,
    compose_source_receipt_ledger_packet,
)


def test_source_receipt_ledger_packet_wraps_existing_skeleton_contract() -> None:
    packet = compose_source_receipt_ledger_packet("company_public_baseline")

    assert packet["schema_version"] == PACKET_SCHEMA_VERSION
    assert packet["packet_kind"] == "source_receipt_ledger"
    assert packet["outcome_contract_id"] == "company_public_baseline"
    assert packet["billable"] is False
    assert packet["charge_status"] == "not_charged"
    assert packet["accepted_artifact_created"] is False
    assert packet["paid_packet_body_materialized"] is False
    assert packet["request_time_llm_call_performed"] is False
    assert packet["live_source_fetch_performed"] is False
    assert packet["live_aws_dependency_used"] is False
    assert packet["skeleton_packet"] is True
    assert packet["receipt_ledger"]["claim_count"] == len(packet["claims"])
    assert packet["receipt_ledger"]["source_receipt_count"] == len(packet["source_receipts"])
    assert packet["receipt_ledger"]["public_claims_release_allowed"] is True
    assert packet["receipt_ledger"]["issues"] == []


def test_source_receipt_ledger_packet_is_mutation_isolated() -> None:
    packet = compose_source_receipt_ledger_packet("evidence_answer")
    packet["claims"][0]["text"] = "mutated"

    fresh = compose_source_receipt_ledger_packet("evidence_answer")

    assert fresh["claims"][0]["text"] == "Answer claim placeholder tied to official evidence."
