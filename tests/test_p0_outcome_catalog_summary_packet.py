from __future__ import annotations

from jpintel_mcp.agent_runtime.outcome_catalog import build_outcome_catalog
from jpintel_mcp.agent_runtime.source_receipts import source_receipt_contract_issues
from jpintel_mcp.services.packets.inline_registry import (
    compose_inline_packet,
    inline_packet_registry_shape,
)
from jpintel_mcp.services.packets.outcome_catalog_summary import (
    compose_outcome_catalog_summary_packet,
)


def test_outcome_catalog_summary_is_free_static_and_receipt_backed() -> None:
    packet = compose_outcome_catalog_summary_packet()

    assert packet["packet_kind"] == "outcome_catalog_summary"
    assert packet["billable"] is False
    assert packet["charge_status"] == "not_charged"
    assert packet["accepted_artifact_created"] is False
    assert packet["paid_packet_body_materialized"] is False
    assert packet["request_time_llm_call_performed"] is False
    assert packet["live_source_fetch_performed"] is False
    assert packet["live_aws_dependency_used"] is False
    assert packet["deliverable_count"] == len(build_outcome_catalog()) == 14
    assert len(packet["deliverables"]) == 14
    assert {item["outcome_contract_id"] for item in packet["deliverables"]} == {
        entry.outcome_contract_id for entry in build_outcome_catalog()
    }
    assert source_receipt_contract_issues(packet) == ()
    assert packet["receipt_ledger"]["public_claims_release_allowed"] is True
    assert packet["receipt_ledger"]["issues"] == []


def test_outcome_catalog_summary_is_advertised_as_inline_packet() -> None:
    packet = compose_inline_packet("outcome_catalog_summary")
    alias_packet = compose_inline_packet("p0_outcome_catalog_summary")
    registry = inline_packet_registry_shape()

    assert packet is not None
    assert alias_packet is not None
    assert packet["packet_kind"] == "outcome_catalog_summary"
    assert alias_packet["packet_kind"] == "outcome_catalog_summary"
    assert "outcome_catalog_summary" in registry["packet_ids"]
    assert registry["recommended_free_first"][0] == "outcome_catalog_summary"
