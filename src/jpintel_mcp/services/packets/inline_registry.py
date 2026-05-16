"""Registry for free inline P0 packets exposed before paid execution exists."""

from __future__ import annotations

from typing import Any

from jpintel_mcp.services.packets.evidence_answer import compose_evidence_answer_packet
from jpintel_mcp.services.packets.outcome_catalog_summary import (
    compose_outcome_catalog_summary_packet,
)
from jpintel_mcp.services.packets.source_receipt_ledger import (
    compose_source_receipt_ledger_packet,
)

INLINE_PACKET_CATALOG_SCHEMA_VERSION = "jpcite.inline_packet_catalog.p0.v1"
INLINE_PACKET_ALIASES = {
    "source_receipt_ledger": "source_receipt_ledger",
    "p0_source_receipt_ledger": "source_receipt_ledger",
    "evidence_answer": "evidence_answer",
    "p0_evidence_answer": "evidence_answer",
    "outcome_catalog_summary": "outcome_catalog_summary",
    "p0_outcome_catalog_summary": "outcome_catalog_summary",
}
INLINE_PACKET_IDS = tuple(sorted(INLINE_PACKET_ALIASES))


def compose_inline_packet(packet_id: str) -> dict[str, Any] | None:
    """Compose a free inline packet by public alias."""

    packet_kind = INLINE_PACKET_ALIASES.get(packet_id.strip())
    if packet_kind == "source_receipt_ledger":
        return compose_source_receipt_ledger_packet()
    if packet_kind == "evidence_answer":
        return compose_evidence_answer_packet()
    if packet_kind == "outcome_catalog_summary":
        return compose_outcome_catalog_summary_packet()
    return None


def inline_packet_registry_shape() -> dict[str, Any]:
    """Return a small discovery shape suitable for REST/MCP route responses."""

    return {
        "available": True,
        "billable": False,
        "charge_status": "not_charged",
        "accepted_artifact_created": False,
        "paid_packet_body_materialized": False,
        "packet_ids": list(INLINE_PACKET_IDS),
        "recommended_free_first": [
            "outcome_catalog_summary",
            "source_receipt_ledger",
            "evidence_answer",
        ],
    }


def build_inline_packet_catalog_shape() -> dict[str, Any]:
    """Return static free inline packets for release-capsule discovery."""

    packet_ids = ("outcome_catalog_summary", "source_receipt_ledger", "evidence_answer")
    packets = {packet_id: compose_inline_packet(packet_id) for packet_id in packet_ids}
    return {
        "schema_version": INLINE_PACKET_CATALOG_SCHEMA_VERSION,
        "catalog_kind": "free_inline_static_packets",
        "available": True,
        "billable": False,
        "charge_status": "not_charged",
        "accepted_artifact_created": False,
        "paid_packet_body_materialized": False,
        "request_time_llm_call_performed": False,
        "live_source_fetch_performed": False,
        "live_aws_dependency_used": False,
        "packet_ids": list(packet_ids),
        "alias_ids": list(INLINE_PACKET_IDS),
        "packets": packets,
    }


__all__ = [
    "INLINE_PACKET_CATALOG_SCHEMA_VERSION",
    "INLINE_PACKET_ALIASES",
    "INLINE_PACKET_IDS",
    "build_inline_packet_catalog_shape",
    "compose_inline_packet",
    "inline_packet_registry_shape",
]
