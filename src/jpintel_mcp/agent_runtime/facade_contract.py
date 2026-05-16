"""Machine-checkable P0 facade contract.

This module derives the public P0 facade shape from ``agent_runtime.defaults``
and adds planning-only execution requirements. It intentionally does not call
or wire live billing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from jpintel_mcp.agent_runtime.billing_contract import (
    build_live_billing_readiness_gate,
)
from jpintel_mcp.agent_runtime.defaults import P0_FACADE_TOOLS, build_p0_facade

FacadeSemantics = Literal["route", "preview", "execute", "get"]

BANNED_P0_FACADE_ALIASES = ("jpcite_cost_preview",)

_TOOL_SEMANTICS: dict[str, FacadeSemantics] = {
    "jpcite_route": "route",
    "jpcite_preview_cost": "preview",
    "jpcite_execute_packet": "execute",
    "jpcite_get_packet": "get",
}


@dataclass(frozen=True)
class P0FacadeToolContract:
    name: str
    semantics: FacadeSemantics
    billable: bool
    requires_user_consent: bool
    requires_scoped_cap_token: bool = False
    requires_idempotency_key: bool = False
    live_billing_wired: bool = False
    accepted_artifact_required_for_charge: bool = False
    no_hit_charge_requires_explicit_consent: bool = False
    charge_basis: Literal["accepted_artifact"] | None = None
    live_wiring_gate: str | None = None
    live_wiring_gate_passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_p0_facade_contract() -> tuple[P0FacadeToolContract, ...]:
    """Return the canonical planning contract for the four P0 facade tools."""

    facade = build_p0_facade()
    facade_tools = facade["tools"]
    names = tuple(tool["name"] for tool in facade_tools)

    if names != P0_FACADE_TOOLS:
        raise ValueError("P0 facade tool order/name mismatch")
    if any(alias in names for alias in BANNED_P0_FACADE_ALIASES):
        raise ValueError("P0 facade contains banned alias")

    contracts: list[P0FacadeToolContract] = []
    readiness_gate = build_live_billing_readiness_gate()
    for tool in facade_tools:
        name = tool["name"]
        semantics = _TOOL_SEMANTICS[name]
        is_execute = semantics == "execute"
        contracts.append(
            P0FacadeToolContract(
                name=name,
                semantics=semantics,
                billable=tool["billable"],
                requires_user_consent=tool["requires_user_consent"],
                requires_scoped_cap_token=is_execute,
                requires_idempotency_key=is_execute,
                accepted_artifact_required_for_charge=is_execute,
                no_hit_charge_requires_explicit_consent=is_execute,
                charge_basis="accepted_artifact" if is_execute else None,
                live_wiring_gate=readiness_gate.gate_id if is_execute else None,
                live_wiring_gate_passed=readiness_gate.gate_passed,
            )
        )

    return tuple(contracts)


def build_p0_facade_contract_shape() -> dict[str, Any]:
    """Return a JSON-ready contract shape for tests and planning artifacts."""

    return {
        "schema_version": "jpcite.agent_facade_contract.p0.v1",
        "tools": [tool.to_dict() for tool in build_p0_facade_contract()],
        "banned_aliases": list(BANNED_P0_FACADE_ALIASES),
        "live_billing_wired": False,
        "live_billing_readiness_gate": build_live_billing_readiness_gate().model_dump(mode="json"),
    }
