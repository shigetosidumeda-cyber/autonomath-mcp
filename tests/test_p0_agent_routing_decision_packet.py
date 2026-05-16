from __future__ import annotations

import json

from jpintel_mcp.agent_runtime.pricing_policy import build_execute_input_hash
from jpintel_mcp.services.packets.agent_routing_decision import (
    PACKET_SCHEMA_VERSION,
    compose_agent_routing_decision_packet,
)


def test_agent_routing_decision_packet_routes_and_stays_free() -> None:
    packet = compose_agent_routing_decision_packet(
        goal="補助金の候補を根拠付きで確認したい",
        input_kind="subsidy",
        max_price_jpy=900,
    )

    assert packet["schema_version"] == PACKET_SCHEMA_VERSION
    assert packet["packet_kind"] == "agent_routing_decision"
    assert packet["recommended_outcome_contract_id"] == "application_strategy"
    assert packet["estimated_price_jpy"] == 900
    assert packet["max_price_jpy"] == 900
    assert packet["cap_passed"] is True
    assert packet["execute_input_hash"] == build_execute_input_hash(
        "application_strategy",
        900,
    )
    assert packet["billable"] is False
    assert packet["charge_status"] == "not_charged"
    assert packet["accepted_artifact_created"] is False
    assert packet["request_time_llm_call_performed"] is False
    assert packet["live_source_fetch_performed"] is False
    assert packet["live_aws_dependency_used"] is False
    assert packet["receipt_ledger"]["public_claims_release_allowed"] is True
    assert packet["receipt_ledger"]["issues"] == []


def test_agent_routing_decision_packet_recommends_adjustment_when_cap_blocks() -> None:
    packet = compose_agent_routing_decision_packet(
        goal="会社の公的情報を確認したい",
        input_kind="company",
        max_price_jpy=0,
    )

    assert packet["recommended_outcome_contract_id"] == "company_public_baseline"
    assert packet["estimated_price_jpy"] == 600
    assert packet["cap_passed"] is False
    assert packet["recommended_next_action"] == "adjust_price_or_scope"
    assert packet["billable"] is False


def test_agent_routing_decision_packet_is_deterministic() -> None:
    first = compose_agent_routing_decision_packet(
        goal="invoice",
        input_kind="invoice",
        max_price_jpy=300,
    )
    second = compose_agent_routing_decision_packet(
        goal="invoice",
        input_kind="invoice",
        max_price_jpy=300,
    )

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
