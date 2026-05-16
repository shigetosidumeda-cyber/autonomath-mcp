"""Inline-only P0 outcome catalog summary packet composer."""

from __future__ import annotations

from jpintel_mcp.agent_runtime.outcome_catalog import (
    CATALOG_VERSION,
    NO_HIT_SEMANTICS,
    build_outcome_catalog,
)
from jpintel_mcp.agent_runtime.outcome_routing import packet_ids_for_entry
from jpintel_mcp.agent_runtime.pricing_policy import price_for_pricing_posture
from jpintel_mcp.agent_runtime.source_receipts import (
    build_source_receipt_ledger,
    known_gap,
    public_claim,
    source_receipt,
)

PACKET_SCHEMA_VERSION = "jpcite.p0.packet.outcome_catalog_summary.v1"


def compose_outcome_catalog_summary_packet() -> dict[str, object]:
    """Compose a deterministic free packet summarizing all P0 outcomes."""

    catalog = build_outcome_catalog()
    receipt_id = "src_static_outcome_catalog_p0"
    claims = (
        public_claim(
            "claim_outcome_catalog_count",
            "The P0 outcome catalog exposes 14 agent-facing deliverables.",
            (receipt_id,),
        ),
        public_claim(
            "claim_outcome_catalog_no_live_runtime",
            "The outcome catalog is static and does not require request-time LLM, network, or AWS execution.",
            (receipt_id,),
        ),
    )
    receipts = (
        source_receipt(
            receipt_id,
            "jpcite_outcome_catalog",
            "metadata:site/releases/rc1-p0-bootstrap/outcome_catalog.json",
            access_method="static_registry",
        ),
    )
    known_gaps = (
        known_gap(
            "gap_paid_artifact_execution_not_wired",
            "accepted_artifact_execution_not_wired",
            "This free catalog packet describes purchasable outcomes; it does not materialize paid artifacts.",
        ),
    )
    deliverables = [
        {
            "deliverable_slug": entry.deliverable_slug,
            "display_name": entry.display_name,
            "outcome_contract_id": entry.outcome_contract_id,
            "packet_ids": list(packet_ids_for_entry(entry)),
            "user_segments": list(entry.user_segments),
            "use_case_tags": list(entry.use_case_tags),
            "pricing_posture": entry.pricing_posture,
            "estimated_price_jpy": price_for_pricing_posture(entry.pricing_posture),
            "billing_posture": entry.billing_posture,
            "input_requirement": entry.input_requirement,
            "requires_user_csv": entry.requires_user_csv,
            "cached_official_public_sources_sufficient": (
                entry.cached_official_public_sources_sufficient
            ),
            "evidence_dependency_types": list(entry.evidence_dependency_types),
        }
        for entry in catalog
    ]
    packet: dict[str, object] = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "packet_kind": "outcome_catalog_summary",
        "outcome_contract_id": "outcome_catalog_summary",
        "catalog_schema_version": CATALOG_VERSION,
        "billable": False,
        "charge_status": "not_charged",
        "accepted_artifact_created": False,
        "paid_packet_body_materialized": False,
        "request_time_llm_call_performed": False,
        "live_source_fetch_performed": False,
        "live_aws_dependency_used": False,
        "deliverable_count": len(deliverables),
        "deliverables": deliverables,
        "claims": list(claims),
        "source_receipts": list(receipts),
        "known_gaps": list(known_gaps),
        "no_hit_semantics": {
            "mode": NO_HIT_SEMANTICS,
            "absence_claim_enabled": False,
        },
        "agent_guidance": {
            "recommended_first_action": "Use jpcite_route or jpcite_preview_cost before asking the user to accept a paid artifact.",
            "must_preserve_fields": [
                "outcome_contract_id",
                "estimated_price_jpy",
                "requires_user_csv",
                "source_receipts",
                "known_gaps",
                "no_hit_semantics",
            ],
        },
    }
    packet["receipt_ledger"] = build_source_receipt_ledger(packet)
    return packet


__all__ = ["PACKET_SCHEMA_VERSION", "compose_outcome_catalog_summary_packet"]
