from __future__ import annotations

import base64
import json

import pytest

from jpintel_mcp.agent_runtime.billing_contract import (
    ArtifactBillingFact,
    ScopedCapTokenParseError,
    authorize_execute,
    billing_idempotency_key,
    build_live_billing_readiness_gate,
    parse_scoped_cap_token,
    preview_free,
    settle_artifact_charge,
)

TOKEN = {
    "token_kind": "scoped_cap_token",
    "input_hash": "sha256:request",
    "outcome_contract_id": "company_public_baseline",
    "max_price_jpy": 300,
    "idempotency_key_required": True,
    "amount_only_token": False,
}


def test_preview_is_free_and_never_billable() -> None:
    decision = preview_free(
        outcome_contract_id="company_public_baseline",
        input_hash="sha256:request",
        estimated_price_jpy=300,
    )

    assert decision.phase == "preview"
    assert decision.action == "preview_free"
    assert decision.billable is False
    assert decision.charge_allowed is False
    assert decision.charge_jpy == 0


def test_execute_requires_scoped_cap_token_and_idempotency_key() -> None:
    missing_token = authorize_execute(
        scoped_cap_token=None,
        idempotency_key="idem-1",
        outcome_contract_id="company_public_baseline",
        input_hash="sha256:request",
        price_jpy=300,
    )
    missing_idempotency = authorize_execute(
        scoped_cap_token=TOKEN,
        idempotency_key=None,
        outcome_contract_id="company_public_baseline",
        input_hash="sha256:request",
        price_jpy=300,
    )

    assert missing_token.action == "reject"
    assert missing_token.reject_reason == "missing_scoped_cap_token"
    assert missing_idempotency.action == "reject"
    assert missing_idempotency.reject_reason == "missing_idempotency_key"


def test_execute_rejects_scope_mismatch_and_price_above_cap() -> None:
    wrong_scope = authorize_execute(
        scoped_cap_token=TOKEN,
        idempotency_key="idem-1",
        outcome_contract_id="source_receipt_ledger",
        input_hash="sha256:request",
        price_jpy=300,
    )
    too_expensive = authorize_execute(
        scoped_cap_token=TOKEN,
        idempotency_key="idem-1",
        outcome_contract_id="company_public_baseline",
        input_hash="sha256:request",
        price_jpy=301,
    )

    assert wrong_scope.action == "reject"
    assert wrong_scope.reject_reason == "token_outcome_scope_mismatch"
    assert too_expensive.action == "reject"
    assert too_expensive.reject_reason == "token_price_cap_exceeded"


def test_execute_rejects_input_hash_mismatch() -> None:
    decision = authorize_execute(
        scoped_cap_token=TOKEN,
        idempotency_key="idem-1",
        outcome_contract_id="company_public_baseline",
        input_hash="sha256:other-request",
        price_jpy=300,
    )

    assert decision.action == "reject"
    assert decision.reject_reason == "token_input_scope_mismatch"
    assert decision.charge_allowed is False


def test_parse_scoped_cap_token_accepts_json_and_rejects_amount_only_tokens() -> None:
    parsed = parse_scoped_cap_token(json.dumps(TOKEN))

    assert parsed.outcome_contract_id == "company_public_baseline"
    with pytest.raises(ScopedCapTokenParseError, match="invalid scoped cap token"):
        parse_scoped_cap_token(json.dumps({**TOKEN, "amount_only_token": True}))


def test_parse_scoped_cap_token_accepts_base64url_json() -> None:
    encoded = (
        base64.urlsafe_b64encode(json.dumps(TOKEN).encode("utf-8")).decode("ascii").rstrip("=")
    )

    parsed = parse_scoped_cap_token(encoded)

    assert parsed.input_hash == "sha256:request"
    assert parsed.max_price_jpy == 300


def test_accepted_artifact_is_the_only_normal_charge_trigger() -> None:
    decision = settle_artifact_charge(
        scoped_cap_token=TOKEN,
        idempotency_key="idem-1",
        artifact=ArtifactBillingFact(
            artifact_id="artifact-1",
            outcome_contract_id="company_public_baseline",
            input_hash="sha256:request",
            state="accepted",
            accepted_by_user=True,
            price_jpy=300,
        ),
    )

    assert decision.action == "charge"
    assert decision.billable is True
    assert decision.charge_allowed is True
    assert decision.charge_jpy == 300
    assert decision.artifact_id == "artifact-1"


def test_settlement_requires_cap_token_and_idempotency_even_for_accepted_artifact() -> None:
    artifact = ArtifactBillingFact(
        artifact_id="artifact-1",
        outcome_contract_id="company_public_baseline",
        input_hash="sha256:request",
        state="accepted",
        accepted_by_user=True,
        price_jpy=300,
    )

    missing_token = settle_artifact_charge(
        scoped_cap_token=None,
        idempotency_key="idem-1",
        artifact=artifact,
    )
    missing_idempotency = settle_artifact_charge(
        scoped_cap_token=TOKEN,
        idempotency_key=None,
        artifact=artifact,
    )

    assert missing_token.action == "reject"
    assert missing_token.charge_allowed is False
    assert missing_token.reject_reason == "missing_scoped_cap_token"
    assert missing_idempotency.action == "reject"
    assert missing_idempotency.charge_allowed is False
    assert missing_idempotency.reject_reason == "missing_idempotency_key"


def test_missing_artifact_and_unaccepted_artifacts_do_not_charge() -> None:
    missing = settle_artifact_charge(
        scoped_cap_token=TOKEN,
        idempotency_key="idem-1",
        artifact={
            "outcome_contract_id": "company_public_baseline",
            "input_hash": "sha256:request",
            "state": "missing",
            "price_jpy": 300,
        },
    )
    draft = settle_artifact_charge(
        scoped_cap_token=TOKEN,
        idempotency_key="idem-1",
        artifact={
            "artifact_id": "artifact-draft",
            "outcome_contract_id": "company_public_baseline",
            "input_hash": "sha256:request",
            "state": "draft",
            "accepted_by_user": False,
            "price_jpy": 300,
        },
    )
    accepted_but_not_user_accepted = settle_artifact_charge(
        scoped_cap_token=TOKEN,
        idempotency_key="idem-1",
        artifact={
            "artifact_id": "artifact-pending-acceptance",
            "outcome_contract_id": "company_public_baseline",
            "input_hash": "sha256:request",
            "state": "accepted",
            "accepted_by_user": False,
            "price_jpy": 300,
        },
    )

    assert missing.action == "no_charge"
    assert missing.reject_reason == "accepted_artifact_missing"
    assert missing.charge_jpy == 0
    assert draft.action == "no_charge"
    assert draft.reject_reason == "artifact_not_accepted"
    assert draft.charge_jpy == 0
    assert accepted_but_not_user_accepted.action == "no_charge"
    assert accepted_but_not_user_accepted.reject_reason == "artifact_not_accepted"
    assert accepted_but_not_user_accepted.charge_jpy == 0


@pytest.mark.parametrize(
    ("token_scope", "artifact_scope", "consented"),
    [
        (None, "gbizinfo:corp:123", True),
        ("gbizinfo:corp:123", "gbizinfo:corp:123", False),
        ("gbizinfo:corp:123", "gbizinfo:corp:999", True),
    ],
)
def test_no_hit_does_not_charge_without_scope_match_and_explicit_consent(
    token_scope: str | None,
    artifact_scope: str,
    consented: bool,
) -> None:
    token = TOKEN if token_scope is None else {**TOKEN, "no_hit_charge_scope": token_scope}

    decision = settle_artifact_charge(
        scoped_cap_token=token,
        idempotency_key="idem-1",
        artifact={
            "artifact_id": "artifact-no-hit",
            "outcome_contract_id": "company_public_baseline",
            "input_hash": "sha256:request",
            "state": "no_hit",
            "accepted_by_user": True,
            "price_jpy": 300,
            "no_hit_scope": artifact_scope,
            "no_hit_charge_consented": consented,
        },
    )

    assert decision.action == "no_charge"
    assert decision.reject_reason == "no_hit_requires_explicit_scope_and_consent"
    assert decision.charge_allowed is False
    assert decision.charge_jpy == 0


def test_no_hit_charges_only_when_scoped_and_consented() -> None:
    no_hit_scoped_and_consented = settle_artifact_charge(
        scoped_cap_token={**TOKEN, "no_hit_charge_scope": "gbizinfo:corp:123"},
        idempotency_key="idem-1",
        artifact={
            "artifact_id": "artifact-no-hit",
            "outcome_contract_id": "company_public_baseline",
            "input_hash": "sha256:request",
            "state": "no_hit",
            "accepted_by_user": True,
            "price_jpy": 300,
            "no_hit_scope": "gbizinfo:corp:123",
            "no_hit_charge_consented": True,
        },
    )

    assert no_hit_scoped_and_consented.action == "charge"
    assert no_hit_scoped_and_consented.charge_jpy == 300


def test_no_hit_artifact_requires_artifact_id_before_charge_decision() -> None:
    with pytest.raises(ValueError, match="no-hit artifacts require artifact_id"):
        settle_artifact_charge(
            scoped_cap_token={**TOKEN, "no_hit_charge_scope": "gbizinfo:corp:123"},
            idempotency_key="idem-1",
            artifact={
                "outcome_contract_id": "company_public_baseline",
                "input_hash": "sha256:request",
                "state": "no_hit",
                "accepted_by_user": True,
                "price_jpy": 300,
                "no_hit_scope": "gbizinfo:corp:123",
                "no_hit_charge_consented": True,
            },
        )


def test_billing_idempotency_key_is_stable_and_requires_all_parts() -> None:
    key = billing_idempotency_key(
        scoped_cap_token_id="token-1",
        artifact_id="artifact-1",
        idempotency_key="idem-1",
    )

    assert key == "accepted_artifact:token-1:artifact-1:idem-1"
    with pytest.raises(ValueError, match="required"):
        billing_idempotency_key(
            scoped_cap_token_id="token-1",
            artifact_id="",
            idempotency_key="idem-1",
        )


def test_live_billing_readiness_gate_fails_closed_until_artifact_wiring_exists() -> None:
    gate = build_live_billing_readiness_gate()

    assert gate.target_tool == "jpcite_execute_packet"
    assert gate.status == "blocked"
    assert gate.gate_passed is False
    assert gate.live_billing_wired is False
    assert gate.failure_mode == "fail_closed"
    assert gate.charge_basis == "accepted_artifact"
    assert "accepted_artifact_store_wired" in gate.required_before_live_billing
    assert "settlement_path_calls_settle_artifact_charge" in (gate.required_before_live_billing)
