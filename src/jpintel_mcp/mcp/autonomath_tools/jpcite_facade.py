"""P0 jpcite facade tools for agent-first routing.

These tools expose the small public facade described by the release capsule.
They are deterministic and do not call AWS, external LLMs, billing providers,
or the database. The execute path is fail-closed until accepted-artifact
billing is wired.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.agent_runtime.billing_contract import (
    ScopedCapTokenParseError,
    authorize_execute,
    build_live_billing_readiness_gate,
    parse_scoped_cap_token,
)
from jpintel_mcp.agent_runtime.defaults import (
    build_agent_purchase_decision,
    build_bootstrap_bundle,
)
from jpintel_mcp.agent_runtime.outcome_routing import (
    outcome_contract_ids,
    preview_for_outcome,
    resolve_outcome_entry,
)
from jpintel_mcp.agent_runtime.packet_skeletons import get_packet_skeleton
from jpintel_mcp.agent_runtime.pricing_policy import build_execute_input_hash
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp
from jpintel_mcp.services.packets.inline_registry import (
    compose_inline_packet,
    inline_packet_registry_shape,
)

_ENABLED = get_flag("JPCITE_P0_FACADE_MCP_ENABLED", "AUTONOMATH_P0_FACADE_MCP_ENABLED", "1") == "1"


def _outcome_contract_ids() -> tuple[str, ...]:
    return outcome_contract_ids()


def _resolve_outcome_contract_id(
    input_kind: str | None,
    outcome_contract_id: str | None = None,
) -> str:
    entry = resolve_outcome_entry(
        input_kind=input_kind,
        outcome_contract_id=outcome_contract_id,
        strict_outcome_contract_id=False,
    )
    if entry is None:
        return (outcome_contract_id or "").strip()
    return entry.outcome_contract_id


def _execute_input_hash(outcome_contract_id: str, max_price_jpy: int | None) -> str:
    return build_execute_input_hash(outcome_contract_id, max_price_jpy)


def _preview_for_outcome(outcome_contract_id: str, max_price_jpy: int | None) -> dict[str, Any]:
    return preview_for_outcome(outcome_contract_id, max_price_jpy)


def _impl_jpcite_route(
    goal: str,
    input_kind: str = "evidence",
    outcome_contract_id: str | None = None,
    max_price_jpy: int | None = None,
) -> dict[str, Any]:
    resolved_outcome = _resolve_outcome_contract_id(input_kind, outcome_contract_id)
    preview = _preview_for_outcome(resolved_outcome, max_price_jpy)
    purchase_decision = build_agent_purchase_decision()
    next_tool = "jpcite_preview_cost" if preview["status"] == "preview_ready" else "jpcite_route"
    return {
        "schema_version": "jpcite.p0.route.v1",
        "status": "route_ready",
        "billable": False,
        "charge_status": "not_charged",
        "goal": goal.strip()[:500],
        "input_kind": input_kind,
        "recommended_tool": next_tool,
        "recommended_outcome_contract_id": resolved_outcome,
        "preview": preview,
        "reason_to_buy": purchase_decision.reason_to_buy,
        "reason_not_to_buy": purchase_decision.reason_not_to_buy,
        "anti_upsell_gate_passed": True,
        "free_inline_packets": inline_packet_registry_shape(),
        "no_hit_caveat": "no_hit_not_absence",
        "next_action": (
            "call_jpcite_preview_cost"
            if next_tool == "jpcite_preview_cost"
            else "adjust_price_or_scope"
        ),
    }


def _impl_jpcite_preview_cost(
    outcome_contract_id: str = "evidence_answer",
    max_price_jpy: int | None = None,
) -> dict[str, Any]:
    preview = _preview_for_outcome(outcome_contract_id.strip(), max_price_jpy)
    preview["free_inline_packets"] = inline_packet_registry_shape()
    return preview


def _impl_jpcite_execute_packet(
    outcome_contract_id: str,
    scoped_cap_token: str | None = None,
    idempotency_key: str | None = None,
    max_price_jpy: int | None = None,
) -> dict[str, Any]:
    preview = _preview_for_outcome(outcome_contract_id.strip(), max_price_jpy)
    missing: list[str] = []
    if not (scoped_cap_token or "").strip():
        missing.append("scoped_cap_token")
    if not (idempotency_key or "").strip():
        missing.append("idempotency_key")
    if missing:
        return {
            "schema_version": "jpcite.p0.execute_packet.v1",
            "status": "blocked_missing_purchase_guard",
            "billable": False,
            "charge_status": "not_charged",
            "outcome_contract_id": outcome_contract_id,
            "missing": tuple(missing),
            "preview": preview,
            "required_next_action": "call_jpcite_preview_cost_then_collect_user_consent",
            "no_hit_caveat": "no_hit_not_absence",
        }

    if preview["status"] != "preview_ready":
        return {
            "schema_version": "jpcite.p0.execute_packet.v1",
            "status": "blocked_preview_not_ready",
            "error": preview["status"],
            "billable": False,
            "charge_status": "not_charged",
            "outcome_contract_id": outcome_contract_id,
            "preview": preview,
            "scoped_cap_token_received": True,
            "idempotency_key_received": True,
            "accepted_artifact_created": False,
            "required_next_action": "call_jpcite_preview_cost_then_adjust_scope_or_cap",
            "no_hit_caveat": "no_hit_not_absence",
        }

    try:
        token = parse_scoped_cap_token(scoped_cap_token or "")
    except ScopedCapTokenParseError as exc:
        return {
            "schema_version": "jpcite.p0.execute_packet.v1",
            "status": "blocked_invalid_scoped_cap_token",
            "error": "invalid_scoped_cap_token",
            "message": str(exc),
            "billable": False,
            "charge_status": "not_charged",
            "outcome_contract_id": outcome_contract_id,
            "preview": preview,
            "accepted_artifact_created": False,
            "no_hit_caveat": "no_hit_not_absence",
        }

    billing_authorization = authorize_execute(
        scoped_cap_token=token,
        idempotency_key=(idempotency_key or "").strip(),
        outcome_contract_id=outcome_contract_id.strip(),
        input_hash=preview["execute_input_hash"],
        price_jpy=int(preview.get("estimated_price_jpy") or 0),
    )
    if billing_authorization.action == "reject":
        return {
            "schema_version": "jpcite.p0.execute_packet.v1",
            "status": "blocked_purchase_guard_rejected",
            "error": billing_authorization.reject_reason,
            "billable": False,
            "charge_status": "not_charged",
            "outcome_contract_id": outcome_contract_id,
            "preview": preview,
            "scoped_cap_token_received": True,
            "idempotency_key_received": True,
            "accepted_artifact_created": False,
            "billing_authorization": billing_authorization.model_dump(mode="json"),
            "required_next_action": "call_jpcite_preview_cost_then_collect_user_consent",
            "no_hit_caveat": "no_hit_not_absence",
        }

    return {
        "schema_version": "jpcite.p0.execute_packet.v1",
        "status": "blocked_accepted_artifact_billing_not_wired",
        "billable": False,
        "charge_status": "not_charged",
        "outcome_contract_id": outcome_contract_id,
        "preview": preview,
        "scoped_cap_token_received": True,
        "idempotency_key_received": True,
        "accepted_artifact_created": False,
        "billing_authorization": billing_authorization.model_dump(mode="json"),
        "required_next_gate": "accepted_artifact_billing_contract",
        "live_billing_readiness_gate": build_live_billing_readiness_gate().model_dump(mode="json"),
        "no_hit_caveat": "no_hit_not_absence",
    }


def _impl_jpcite_get_packet(packet_id: str) -> dict[str, Any]:
    bundle = build_bootstrap_bundle()
    if packet_id == bundle["release_capsule_manifest"]["capsule_id"]:
        return {
            "schema_version": "jpcite.p0.get_packet.v1",
            "status": "capsule_contract_packet",
            "billable": False,
            "charge_status": "not_charged",
            "packet_id": packet_id,
            "packet": {
                "release_capsule_manifest": bundle["release_capsule_manifest"],
                "capability_matrix": bundle["capability_matrix"],
                "preflight_scorecard": bundle["preflight_scorecard"],
            },
            "no_hit_caveat": "no_hit_not_absence",
        }
    inline_packet = _compose_inline_packet(packet_id)
    if inline_packet is not None:
        return {
            "schema_version": "jpcite.p0.get_packet.v1",
            "status": "inline_static_packet",
            "billable": False,
            "charge_status": "not_charged",
            "packet_id": packet_id,
            "accepted_artifact_created": False,
            "paid_packet_body_materialized": False,
            "packet": inline_packet,
            "no_hit_caveat": "no_hit_not_absence",
        }
    skeleton_entry = resolve_outcome_entry(
        outcome_contract_id=packet_id,
        strict_outcome_contract_id=True,
    )
    if skeleton_entry is not None:
        return {
            "schema_version": "jpcite.p0.get_packet.v1",
            "status": "static_packet_skeleton",
            "billable": False,
            "charge_status": "not_charged",
            "packet_id": packet_id,
            "outcome_contract_id": skeleton_entry.outcome_contract_id,
            "deliverable_slug": skeleton_entry.deliverable_slug,
            "accepted_artifact_created": False,
            "paid_packet_body_materialized": False,
            "packet": get_packet_skeleton(skeleton_entry.outcome_contract_id),
            "known_gaps": ("paid_artifact_body_not_materialized",),
            "no_hit_caveat": "no_hit_not_absence",
        }
    return {
        "schema_version": "jpcite.p0.get_packet.v1",
        "status": "packet_not_found_or_not_materialized",
        "billable": False,
        "charge_status": "not_charged",
        "packet_id": packet_id,
        "known_gaps": ("packet_store_not_live_until_accepted_artifact_gate",),
        "no_hit_caveat": "no_hit_not_absence",
    }


def _compose_inline_packet(packet_id: str) -> dict[str, Any] | None:
    return compose_inline_packet(packet_id)


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def jpcite_route(
        goal: Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description="User goal or artifact request to route through the P0 facade.",
            ),
        ],
        input_kind: Annotated[
            str,
            Field(
                description=(
                    "Routing hint such as company, invoice, subsidy, local_government, "
                    "court, statistics, monthly_review, csv_counterparty, csv_subsidy, "
                    "foreign_investor, healthcare, evidence, source_receipts, csv_overlay, "
                    "or regulation_watch."
                ),
            ),
        ] = "evidence",
        outcome_contract_id: Annotated[
            str | None,
            Field(description="Optional outcome contract id when already known."),
        ] = None,
        max_price_jpy: Annotated[
            int | None,
            Field(ge=0, description="Optional user price cap in JPY."),
        ] = None,
    ) -> dict[str, Any]:
        """Route a user request to the cheapest sufficient P0 jpcite action. Free, deterministic, no external calls."""
        return _impl_jpcite_route(
            goal=goal,
            input_kind=input_kind,
            outcome_contract_id=outcome_contract_id,
            max_price_jpy=max_price_jpy,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def jpcite_preview_cost(
        outcome_contract_id: Annotated[
            str,
            Field(description="Outcome contract id to price before any purchase."),
        ] = "evidence_answer",
        max_price_jpy: Annotated[
            int | None,
            Field(ge=0, description="Optional user price cap in JPY."),
        ] = None,
    ) -> dict[str, Any]:
        """Preview price, known gaps, consent needs, and no-hit caveat before a paid packet. Free."""
        return _impl_jpcite_preview_cost(
            outcome_contract_id=outcome_contract_id,
            max_price_jpy=max_price_jpy,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def jpcite_execute_packet(
        outcome_contract_id: Annotated[
            str,
            Field(description="Outcome contract id accepted by the user."),
        ],
        scoped_cap_token: Annotated[
            str | None,
            Field(description="Scoped cap token created after preview and user consent."),
        ] = None,
        idempotency_key: Annotated[
            str | None,
            Field(description="Caller idempotency key for eventual accepted-artifact creation."),
        ] = None,
        max_price_jpy: Annotated[
            int | None,
            Field(ge=0, description="Accepted max price in JPY."),
        ] = None,
    ) -> dict[str, Any]:
        """Fail-closed execute entrypoint. It does not charge until accepted-artifact billing is wired."""
        return _impl_jpcite_execute_packet(
            outcome_contract_id=outcome_contract_id,
            scoped_cap_token=scoped_cap_token,
            idempotency_key=idempotency_key,
            max_price_jpy=max_price_jpy,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def jpcite_get_packet(
        packet_id: Annotated[
            str,
            Field(min_length=1, max_length=200, description="Packet id or release capsule id."),
        ],
    ) -> dict[str, Any]:
        """Retrieve a P0 packet if materialized. Free and deterministic; no absence claim is made."""
        return _impl_jpcite_get_packet(packet_id=packet_id)
