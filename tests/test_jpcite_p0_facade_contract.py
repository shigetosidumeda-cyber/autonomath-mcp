from jpintel_mcp.agent_runtime.defaults import P0_FACADE_TOOLS, build_p0_facade
from jpintel_mcp.agent_runtime.facade_contract import (
    BANNED_P0_FACADE_ALIASES,
    build_p0_facade_contract,
    build_p0_facade_contract_shape,
)


def test_p0_facade_contract_has_canonical_four_names_from_defaults() -> None:
    facade = build_p0_facade()
    contract = build_p0_facade_contract()

    assert tuple(tool["name"] for tool in facade["tools"]) == P0_FACADE_TOOLS
    assert tuple(tool.name for tool in contract) == P0_FACADE_TOOLS
    assert P0_FACADE_TOOLS == (
        "jpcite_route",
        "jpcite_preview_cost",
        "jpcite_execute_packet",
        "jpcite_get_packet",
    )


def test_p0_facade_contract_semantics_and_billing_flags() -> None:
    tools = {tool.name: tool for tool in build_p0_facade_contract()}

    assert tools["jpcite_route"].semantics == "route"
    assert tools["jpcite_route"].billable is False
    assert tools["jpcite_route"].requires_user_consent is False

    assert tools["jpcite_preview_cost"].semantics == "preview"
    assert tools["jpcite_preview_cost"].billable is False
    assert tools["jpcite_preview_cost"].requires_user_consent is False

    assert tools["jpcite_execute_packet"].semantics == "execute"
    assert tools["jpcite_execute_packet"].billable is True
    assert tools["jpcite_execute_packet"].requires_user_consent is True

    assert tools["jpcite_get_packet"].semantics == "get"
    assert tools["jpcite_get_packet"].billable is False
    assert tools["jpcite_get_packet"].requires_user_consent is False


def test_p0_facade_has_no_cost_preview_alias() -> None:
    facade_names = {tool["name"] for tool in build_p0_facade()["tools"]}
    contract_names = {tool.name for tool in build_p0_facade_contract()}

    assert "jpcite_cost_preview" in BANNED_P0_FACADE_ALIASES
    assert "jpcite_cost_preview" not in facade_names
    assert "jpcite_cost_preview" not in contract_names


def test_paid_execute_contract_requires_scoped_cap_token_and_idempotency() -> None:
    shape = build_p0_facade_contract_shape()
    execute = next(tool for tool in shape["tools"] if tool["name"] == "jpcite_execute_packet")

    assert execute["billable"] is True
    assert execute["requires_user_consent"] is True
    assert execute["requires_scoped_cap_token"] is True
    assert execute["requires_idempotency_key"] is True
    assert execute["accepted_artifact_required_for_charge"] is True
    assert execute["no_hit_charge_requires_explicit_consent"] is True
    assert execute["charge_basis"] == "accepted_artifact"
    assert execute["live_billing_wired"] is False
    assert execute["live_wiring_gate"] == "jpcite_execute_packet_live_billing_readiness_gate"
    assert execute["live_wiring_gate_passed"] is False
    assert shape["live_billing_wired"] is False


def test_p0_facade_contract_exposes_failing_live_billing_gate() -> None:
    shape = build_p0_facade_contract_shape()
    gate = shape["live_billing_readiness_gate"]

    assert gate["target_tool"] == "jpcite_execute_packet"
    assert gate["status"] == "blocked"
    assert gate["gate_passed"] is False
    assert gate["live_billing_wired"] is False
    assert gate["failure_mode"] == "fail_closed"
    assert gate["blocked_reason"] == "accepted_artifact_execution_not_wired"
    assert "billing_event_ledger_append_only_wired" in (gate["required_before_live_billing"])
