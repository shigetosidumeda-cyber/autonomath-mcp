"""Pure accepted-artifact billing contract for agent runtime execution.

This module is intentionally deterministic: no database, Stripe, network,
clock, randomness, or mutable process state. Callers pass the current request
facts in and receive a contract decision describing whether execution or
charging is allowed.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from collections.abc import Mapping

ArtifactState = Literal["missing", "draft", "accepted", "no_hit"]
BillingPhase = Literal["preview", "execute", "settle"]
BillingAction = Literal["preview_free", "authorize_execute", "charge", "no_charge", "reject"]
LIVE_BILLING_READINESS_GATE_ID: Literal["jpcite_execute_packet_live_billing_readiness_gate"] = (
    "jpcite_execute_packet_live_billing_readiness_gate"
)
RejectReason = Literal[
    "none",
    "missing_scoped_cap_token",
    "missing_idempotency_key",
    "token_outcome_scope_mismatch",
    "token_input_scope_mismatch",
    "token_price_cap_exceeded",
    "amount_only_token_rejected",
    "accepted_artifact_missing",
    "artifact_not_accepted",
    "no_hit_requires_explicit_scope_and_consent",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScopedCapTokenView(StrictModel):
    """Minimal token surface required by the accepted-artifact contract."""

    token_kind: Literal["scoped_cap_token"] = "scoped_cap_token"
    input_hash: str = Field(min_length=1)
    outcome_contract_id: str = Field(min_length=1)
    max_price_jpy: int = Field(ge=0)
    idempotency_key_required: Literal[True] = True
    amount_only_token: Literal[False] = False
    no_hit_charge_scope: str | None = None

    @classmethod
    def from_token(cls, token: Mapping[str, Any] | BaseModel) -> ScopedCapTokenView:
        keys = cls.model_fields.keys()
        data = token.model_dump() if isinstance(token, BaseModel) else dict(token)
        return cls.model_validate({key: data[key] for key in keys if key in data})


class ScopedCapTokenParseError(ValueError):
    """Raised when an execute guard token cannot be decoded as a scoped cap token."""


class ArtifactBillingFact(StrictModel):
    artifact_id: str | None = None
    outcome_contract_id: str = Field(min_length=1)
    input_hash: str = Field(min_length=1)
    state: ArtifactState
    accepted_by_user: bool = False
    price_jpy: int = Field(default=0, ge=0)
    no_hit_scope: str | None = None
    no_hit_charge_consented: bool = False

    @model_validator(mode="after")
    def _chargeable_artifacts_have_ids(self) -> ArtifactBillingFact:
        if self.state in {"accepted", "no_hit"} and not self.artifact_id:
            raise ValueError("accepted and no-hit artifacts require artifact_id")
        return self


class BillingContractDecision(StrictModel):
    phase: BillingPhase
    action: BillingAction
    billable: bool
    charge_allowed: bool
    charge_jpy: int = Field(ge=0)
    idempotency_key: str | None = None
    artifact_id: str | None = None
    reject_reason: RejectReason = "none"
    preview_is_free: Literal[True] = True
    execute_requires_scoped_cap_token: Literal[True] = True
    execute_requires_idempotency_key: Literal[True] = True
    accepted_artifact_required_for_charge: Literal[True] = True
    missing_artifact_is_free: Literal[True] = True
    unscoped_no_hit_is_free: Literal[True] = True
    no_hit_charge_requires_explicit_consent: Literal[True] = True
    live_billing_wired: Literal[False] = False
    live_wiring_gate: Literal["jpcite_execute_packet_live_billing_readiness_gate"] = (
        LIVE_BILLING_READINESS_GATE_ID
    )


class LiveBillingReadinessGate(StrictModel):
    """Failing gate that must change before live billing can be wired."""

    gate_id: Literal["jpcite_execute_packet_live_billing_readiness_gate"] = (
        LIVE_BILLING_READINESS_GATE_ID
    )
    target_tool: Literal["jpcite_execute_packet"] = "jpcite_execute_packet"
    status: Literal["blocked"] = "blocked"
    gate_passed: Literal[False] = False
    live_billing_wired: Literal[False] = False
    failure_mode: Literal["fail_closed"] = "fail_closed"
    charge_basis: Literal["accepted_artifact"] = "accepted_artifact"
    required_before_live_billing: tuple[str, ...] = (
        "accepted_artifact_store_wired",
        "settlement_path_calls_settle_artifact_charge",
        "billing_event_ledger_append_only_wired",
        "scoped_cap_token_and_idempotency_enforced_at_execute",
        "no_hit_charge_scope_and_explicit_consent_enforced",
        "replay_uses_billing_idempotency_key",
    )
    blocked_reason: Literal["accepted_artifact_execution_not_wired"] = (
        "accepted_artifact_execution_not_wired"
    )


def build_live_billing_readiness_gate() -> LiveBillingReadinessGate:
    """Return the explicit fail-closed gate for future live billing work."""

    return LiveBillingReadinessGate()


def parse_scoped_cap_token(token_text: str) -> ScopedCapTokenView:
    """Decode a header/tool token into the minimal scoped cap token view.

    The P0 facade accepts either compact JSON or base64url-encoded JSON so
    HTTP callers can avoid awkward quoting in headers.
    """

    text = token_text.strip()
    if not text:
        raise ScopedCapTokenParseError("empty scoped cap token")

    try:
        data = json.loads(text) if text.startswith("{") else _loads_base64url_json(text)
        if not isinstance(data, dict):
            raise ScopedCapTokenParseError("scoped cap token must decode to an object")
        return ScopedCapTokenView.from_token(data)
    except ScopedCapTokenParseError:
        raise
    except (TypeError, ValueError) as exc:
        raise ScopedCapTokenParseError("invalid scoped cap token") from exc


def preview_free(
    *,
    outcome_contract_id: str,
    input_hash: str,
    estimated_price_jpy: int,
) -> BillingContractDecision:
    """Return the free preview decision before any paid execution attempt."""

    ArtifactBillingFact(
        outcome_contract_id=outcome_contract_id,
        input_hash=input_hash,
        state="draft",
        price_jpy=estimated_price_jpy,
    )
    return BillingContractDecision(
        phase="preview",
        action="preview_free",
        billable=False,
        charge_allowed=False,
        charge_jpy=0,
    )


def authorize_execute(
    *,
    scoped_cap_token: Mapping[str, Any] | BaseModel | None,
    idempotency_key: str | None,
    outcome_contract_id: str,
    input_hash: str,
    price_jpy: int,
) -> BillingContractDecision:
    """Authorize execution only when token scope and idempotency are present."""

    if scoped_cap_token is None:
        return _reject("execute", "missing_scoped_cap_token", idempotency_key)
    if not idempotency_key:
        return _reject("execute", "missing_idempotency_key", idempotency_key)

    token = ScopedCapTokenView.from_token(scoped_cap_token)
    reject_reason = _token_reject_reason(
        token=token,
        outcome_contract_id=outcome_contract_id,
        input_hash=input_hash,
        price_jpy=price_jpy,
    )
    if reject_reason != "none":
        return _reject("execute", reject_reason, idempotency_key)

    return BillingContractDecision(
        phase="execute",
        action="authorize_execute",
        billable=False,
        charge_allowed=False,
        charge_jpy=0,
        idempotency_key=idempotency_key,
    )


def settle_artifact_charge(
    *,
    scoped_cap_token: Mapping[str, Any] | BaseModel | None,
    idempotency_key: str | None,
    artifact: ArtifactBillingFact | Mapping[str, Any],
) -> BillingContractDecision:
    """Decide whether the produced artifact may be charged.

    Charging is allowed only after an accepted artifact. Missing artifacts,
    drafts, and unscoped no-hit results resolve to explicit no-charge decisions.
    """

    fact = (
        artifact
        if isinstance(artifact, ArtifactBillingFact)
        else ArtifactBillingFact.model_validate(dict(artifact))
    )
    authorized = authorize_execute(
        scoped_cap_token=scoped_cap_token,
        idempotency_key=idempotency_key,
        outcome_contract_id=fact.outcome_contract_id,
        input_hash=fact.input_hash,
        price_jpy=fact.price_jpy,
    )
    if authorized.action == "reject":
        return BillingContractDecision(
            phase="settle",
            action="reject",
            billable=False,
            charge_allowed=False,
            charge_jpy=0,
            idempotency_key=idempotency_key,
            artifact_id=fact.artifact_id,
            reject_reason=authorized.reject_reason,
        )

    token = ScopedCapTokenView.from_token(scoped_cap_token or {})
    if fact.state == "missing":
        return _no_charge(
            artifact=fact,
            idempotency_key=idempotency_key,
            reject_reason="accepted_artifact_missing",
        )
    if fact.state == "draft" or not fact.accepted_by_user:
        return _no_charge(
            artifact=fact,
            idempotency_key=idempotency_key,
            reject_reason="artifact_not_accepted",
        )
    if fact.state == "no_hit" and not _no_hit_charge_allowed(fact, token):
        return _no_charge(
            artifact=fact,
            idempotency_key=idempotency_key,
            reject_reason="no_hit_requires_explicit_scope_and_consent",
        )

    return BillingContractDecision(
        phase="settle",
        action="charge",
        billable=True,
        charge_allowed=True,
        charge_jpy=fact.price_jpy,
        idempotency_key=idempotency_key,
        artifact_id=fact.artifact_id,
    )


def billing_idempotency_key(
    *,
    scoped_cap_token_id: str,
    artifact_id: str,
    idempotency_key: str,
) -> str:
    """Stable ledger key for callers that need deterministic deduplication."""

    if not scoped_cap_token_id or not artifact_id or not idempotency_key:
        raise ValueError("scoped_cap_token_id, artifact_id, and idempotency_key are required")
    return f"accepted_artifact:{scoped_cap_token_id}:{artifact_id}:{idempotency_key}"


def _token_reject_reason(
    *,
    token: ScopedCapTokenView,
    outcome_contract_id: str,
    input_hash: str,
    price_jpy: int,
) -> RejectReason:
    if token.amount_only_token:
        return "amount_only_token_rejected"
    if token.outcome_contract_id != outcome_contract_id:
        return "token_outcome_scope_mismatch"
    if token.input_hash != input_hash:
        return "token_input_scope_mismatch"
    if price_jpy > token.max_price_jpy:
        return "token_price_cap_exceeded"
    return "none"


def _loads_base64url_json(text: str) -> Any:
    padding = "=" * (-len(text) % 4)
    try:
        decoded = base64.urlsafe_b64decode((text + padding).encode("ascii"))
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise ScopedCapTokenParseError("scoped cap token is not base64url") from exc

    try:
        return json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScopedCapTokenParseError("scoped cap token is not JSON") from exc


def _no_hit_charge_allowed(fact: ArtifactBillingFact, token: ScopedCapTokenView) -> bool:
    return bool(
        fact.accepted_by_user
        and fact.no_hit_charge_consented
        and fact.no_hit_scope
        and token.no_hit_charge_scope
        and fact.no_hit_scope == token.no_hit_charge_scope
    )


def _reject(
    phase: BillingPhase,
    reject_reason: RejectReason,
    idempotency_key: str | None,
) -> BillingContractDecision:
    return BillingContractDecision(
        phase=phase,
        action="reject",
        billable=False,
        charge_allowed=False,
        charge_jpy=0,
        idempotency_key=idempotency_key,
        reject_reason=reject_reason,
    )


def _no_charge(
    *,
    artifact: ArtifactBillingFact,
    idempotency_key: str | None,
    reject_reason: RejectReason,
) -> BillingContractDecision:
    return BillingContractDecision(
        phase="settle",
        action="no_charge",
        billable=False,
        charge_allowed=False,
        charge_jpy=0,
        idempotency_key=idempotency_key,
        artifact_id=artifact.artifact_id,
        reject_reason=reject_reason,
    )


__all__ = [
    "ArtifactBillingFact",
    "BillingContractDecision",
    "LIVE_BILLING_READINESS_GATE_ID",
    "LiveBillingReadinessGate",
    "ScopedCapTokenParseError",
    "ScopedCapTokenView",
    "authorize_execute",
    "billing_idempotency_key",
    "build_live_billing_readiness_gate",
    "parse_scoped_cap_token",
    "preview_free",
    "settle_artifact_charge",
]
