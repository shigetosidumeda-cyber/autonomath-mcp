"""Inline-only P0 source receipt ledger packet composer."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from jpintel_mcp.agent_runtime.packet_skeletons import get_packet_skeleton
from jpintel_mcp.agent_runtime.source_receipts import build_source_receipt_ledger

PACKET_SCHEMA_VERSION = "jpcite.p0.packet.source_receipt_ledger.v1"


def compose_source_receipt_ledger_packet(
    outcome_contract_id: str = "source_receipt_ledger",
) -> dict[str, Any]:
    """Compose a deterministic source-receipt ledger packet from a P0 skeleton."""

    skeleton = get_packet_skeleton(outcome_contract_id)
    ledger = build_source_receipt_ledger(skeleton)
    return {
        "schema_version": PACKET_SCHEMA_VERSION,
        "packet_kind": "source_receipt_ledger",
        "outcome_contract_id": outcome_contract_id,
        "billable": False,
        "charge_status": "not_charged",
        "accepted_artifact_created": False,
        "paid_packet_body_materialized": False,
        "request_time_llm_call_performed": False,
        "live_source_fetch_performed": False,
        "live_aws_dependency_used": False,
        "skeleton_packet": True,
        "claims": deepcopy(skeleton["claims"]),
        "source_receipts": deepcopy(skeleton["source_receipts"]),
        "known_gaps": deepcopy(skeleton["known_gaps"]),
        "no_hit_semantics": deepcopy(skeleton["no_hit_semantics"]),
        "receipt_ledger": ledger,
    }


__all__ = ["PACKET_SCHEMA_VERSION", "compose_source_receipt_ledger_packet"]
