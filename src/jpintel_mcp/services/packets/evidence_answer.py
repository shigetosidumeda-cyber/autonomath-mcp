"""Inline-only P0 evidence answer packet composer."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from jpintel_mcp.agent_runtime.packet_skeletons import get_packet_skeleton
from jpintel_mcp.agent_runtime.source_receipts import build_source_receipt_ledger

PACKET_SCHEMA_VERSION = "jpcite.p0.packet.evidence_answer.v1"


def compose_evidence_answer_packet(question: str | None = None) -> dict[str, Any]:
    """Compose a deterministic evidence-answer packet from the P0 skeleton."""

    skeleton = get_packet_skeleton("evidence_answer")
    ledger = build_source_receipt_ledger(skeleton)
    return {
        "schema_version": PACKET_SCHEMA_VERSION,
        "packet_kind": "evidence_answer",
        "outcome_contract_id": "evidence_answer",
        "question": (question or "").strip()[:500] or None,
        "answer": deepcopy(skeleton["answer"]),
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


__all__ = ["PACKET_SCHEMA_VERSION", "compose_evidence_answer_packet"]
