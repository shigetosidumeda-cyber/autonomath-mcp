"""Inline-only P0 agent routing decision packet composer."""

from __future__ import annotations

from typing import Any

from jpintel_mcp.agent_runtime.outcome_catalog import build_outcome_catalog
from jpintel_mcp.agent_runtime.pricing_policy import (
    build_execute_input_hash,
    cap_passes,
    normalize_price_cap,
    price_for_pricing_posture,
)
from jpintel_mcp.agent_runtime.source_receipts import (
    build_source_receipt_ledger,
    known_gap,
    public_claim,
    source_receipt,
)

PACKET_SCHEMA_VERSION = "jpcite.p0.packet.agent_routing_decision.v1"
DEFAULT_OUTCOME_CONTRACT_ID = "evidence_answer"

_INPUT_KIND_ROUTE_HINTS: dict[str, tuple[str, ...]] = {
    "company": ("company", "registry", "invoice"),
    "invoice": ("invoice", "tax"),
    "subsidy": ("subsidy", "grant", "application"),
    "regulation": ("law", "regulation", "change"),
    "source_receipts": ("source_receipt", "claim_graph"),
    "csv_counterparty": ("csv", "counterparty", "invoice", "company"),
    "csv_subsidy": ("csv", "cashbook", "subsidy", "grant"),
    "healthcare": ("healthcare", "regulatory"),
    "foreign_investor": ("foreign", "investor", "japan"),
}


def compose_agent_routing_decision_packet(
    *,
    goal: str,
    input_kind: str = "evidence",
    outcome_contract_id: str | None = None,
    max_price_jpy: int | None = None,
) -> dict[str, Any]:
    """Compose a deterministic routing decision packet with receipt backing."""

    outcome = _resolve_outcome(input_kind=input_kind, outcome_contract_id=outcome_contract_id)
    price_jpy = price_for_pricing_posture(outcome["pricing_posture"])
    if price_jpy is None:
        raise ValueError(f"unknown pricing posture: {outcome['pricing_posture']}")
    normalized_cap = normalize_price_cap(max_price_jpy)
    cap_ok = cap_passes(price_jpy, max_price_jpy)
    claims = [
        public_claim(
            "claim_routing_decision",
            "Routing decision was derived from the static P0 outcome catalog.",
            ("sr_p0_outcome_catalog",),
        ),
        public_claim(
            "claim_price_preview",
            "Estimated price is selected from the deterministic P0 pricing policy.",
            ("sr_p0_pricing_policy",),
        ),
    ]
    receipts = [
        source_receipt(
            "sr_p0_outcome_catalog",
            "jpcite_p0_outcome_catalog",
            "metadata:p0-outcome-catalog",
        ),
        source_receipt(
            "sr_p0_pricing_policy",
            "jpcite_p0_pricing_policy",
            "metadata:p0-pricing-policy",
        ),
    ]
    gaps = [
        known_gap(
            "gap_live_execution_not_wired",
            "execution_boundary",
            "This P0 packet is a deterministic routing decision; paid artifact execution is not wired.",
        )
    ]
    packet = {
        "schema_version": "jpcite.packet_skeleton.p0.v1",
        "outcome_contract_id": outcome["outcome_contract_id"],
        "claims": claims,
        "source_receipts": receipts,
        "known_gaps": gaps,
        "no_hit_semantics": {
            "rule": "no_hit_not_absence",
            "absence_claim_enabled": False,
            "wording": "No hit is reported as an observed search result only, not as proof of absence.",
        },
    }
    return {
        "schema_version": PACKET_SCHEMA_VERSION,
        "packet_kind": "agent_routing_decision",
        "goal": goal.strip()[:500],
        "input_kind": input_kind,
        "recommended_outcome_contract_id": outcome["outcome_contract_id"],
        "deliverable_slug": outcome["deliverable_slug"],
        "estimated_price_jpy": price_jpy,
        "max_price_jpy": normalized_cap,
        "cap_passed": cap_ok,
        "execute_input_hash": build_execute_input_hash(
            outcome["outcome_contract_id"],
            max_price_jpy,
        ),
        "requires_user_csv": outcome["requires_user_csv"],
        "evidence_dependency_types": outcome["evidence_dependency_types"],
        "recommended_next_action": (
            "call_jpcite_preview_cost" if cap_ok else "adjust_price_or_scope"
        ),
        "billable": False,
        "charge_status": "not_charged",
        "accepted_artifact_created": False,
        "paid_packet_body_materialized": False,
        "request_time_llm_call_performed": False,
        "live_source_fetch_performed": False,
        "live_aws_dependency_used": False,
        "claims": claims,
        "source_receipts": receipts,
        "known_gaps": gaps,
        "no_hit_semantics": packet["no_hit_semantics"],
        "receipt_ledger": build_source_receipt_ledger(packet),
    }


def _resolve_outcome(
    *,
    input_kind: str,
    outcome_contract_id: str | None,
) -> dict[str, Any]:
    catalog = build_outcome_catalog()
    by_id = {entry.outcome_contract_id: entry for entry in catalog}
    if outcome_contract_id and outcome_contract_id in by_id:
        return by_id[outcome_contract_id].to_dict()

    normalized_kind = input_kind.strip().lower().replace("-", "_")
    terms = _INPUT_KIND_ROUTE_HINTS.get(normalized_kind, (normalized_kind,))
    best_score = -1
    best = by_id[DEFAULT_OUTCOME_CONTRACT_ID]
    for entry in catalog:
        haystack = (
            " ".join(
                (
                    entry.deliverable_slug,
                    entry.display_name,
                    entry.outcome_contract_id,
                    entry.input_requirement,
                    *entry.use_case_tags,
                    *entry.evidence_dependency_types,
                )
            )
            .lower()
            .replace("-", "_")
        )
        score = sum(1 for term in terms if term in haystack)
        if "csv" in normalized_kind:
            score += 2 if entry.requires_user_csv else -1
        if score > best_score:
            best_score = score
            best = entry
    return best.to_dict()


__all__ = [
    "DEFAULT_OUTCOME_CONTRACT_ID",
    "PACKET_SCHEMA_VERSION",
    "compose_agent_routing_decision_packet",
]
