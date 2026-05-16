"""Stream B: tests for the Evidence Pydantic contract.

The Evidence model binds receipts + claim refs into a single citation envelope
with a fail-closed validator: absence-state evidence must declare an
``absence_observation`` evidence_type and never claim ``supported`` support,
and the model rejects extra fields under StrictModel.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jpintel_mcp.agent_runtime import Evidence
from jpintel_mcp.agent_runtime.contracts import Evidence as EvidenceFromContracts


def _valid_payload() -> dict[str, object]:
    return {
        "evidence_id": "evi_001",
        "claim_ref_ids": ("clm_a",),
        "receipt_ids": ("rcp_x", "rcp_y"),
        "evidence_type": "direct_quote",
        "support_state": "supported",
        "temporal_envelope": "2026-05-16T00:00:00Z/2026-05-17T00:00:00Z",
        "observed_at": "2026-05-16T12:34:56Z",
    }


def test_evidence_is_exported_from_package_and_contracts_module() -> None:
    assert Evidence is EvidenceFromContracts


def test_evidence_roundtrip_preserves_field_values_and_immutable_defaults() -> None:
    payload = _valid_payload()
    evidence = Evidence(**payload)

    dumped = evidence.model_dump()

    assert dumped["evidence_id"] == "evi_001"
    assert dumped["claim_ref_ids"] == ("clm_a",)
    assert dumped["receipt_ids"] == ("rcp_x", "rcp_y")
    assert dumped["evidence_type"] == "direct_quote"
    assert dumped["support_state"] == "supported"
    assert dumped["temporal_envelope"].startswith("2026-05-16")
    assert dumped["observed_at"] == "2026-05-16T12:34:56Z"
    assert dumped["request_time_llm_call_performed"] is False


def test_evidence_is_frozen_strict_model() -> None:
    evidence = Evidence(**_valid_payload())

    with pytest.raises(ValidationError):
        evidence.evidence_id = "mutated"  # type: ignore[misc]


def test_evidence_rejects_extra_fields() -> None:
    payload = _valid_payload()
    payload["unexpected_field"] = "should-be-rejected"

    with pytest.raises(ValidationError):
        Evidence(**payload)


def test_evidence_rejects_empty_claim_refs_or_receipts() -> None:
    payload = _valid_payload()
    payload["claim_ref_ids"] = ()
    with pytest.raises(ValidationError):
        Evidence(**payload)

    payload = _valid_payload()
    payload["receipt_ids"] = ()
    with pytest.raises(ValidationError):
        Evidence(**payload)


def test_evidence_rejects_unknown_evidence_type_or_support_state() -> None:
    payload = _valid_payload()
    payload["evidence_type"] = "made_up_type"
    with pytest.raises(ValidationError):
        Evidence(**payload)

    payload = _valid_payload()
    payload["support_state"] = "definitely_true"
    with pytest.raises(ValidationError):
        Evidence(**payload)


def test_evidence_rejects_request_time_llm_call_true() -> None:
    payload = _valid_payload()
    payload["request_time_llm_call_performed"] = True

    with pytest.raises(ValidationError):
        Evidence(**payload)


def test_absent_support_requires_absence_observation_type() -> None:
    payload = _valid_payload()
    payload["support_state"] = "absent"
    payload["evidence_type"] = "direct_quote"

    with pytest.raises(ValidationError, match="absence_observation"):
        Evidence(**payload)


def test_absence_observation_cannot_claim_supported_state() -> None:
    payload = _valid_payload()
    payload["evidence_type"] = "absence_observation"
    payload["support_state"] = "supported"

    with pytest.raises(ValidationError, match="absence_observation"):
        Evidence(**payload)


def test_absent_state_with_absence_observation_is_accepted() -> None:
    payload = _valid_payload()
    payload["evidence_type"] = "absence_observation"
    payload["support_state"] = "absent"

    evidence = Evidence(**payload)

    assert evidence.support_state == "absent"
    assert evidence.evidence_type == "absence_observation"


def test_partial_and_contested_states_remain_supported_in_enum() -> None:
    for support_state in ("partial", "contested"):
        payload = _valid_payload()
        payload["support_state"] = support_state
        evidence = Evidence(**payload)
        assert evidence.support_state == support_state
