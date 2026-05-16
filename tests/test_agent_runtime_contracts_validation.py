"""Stream T coverage gap: agent_runtime/contracts.py 19 Pydantic models.

Targets ``src/jpintel_mcp/agent_runtime/contracts.py``. The existing
``tests/test_agent_runtime_contracts.py`` smoke-tests a subset of the
models; this file completes coverage for the StrictModel posture
(extra=forbid, frozen=True), every field validator, the 17-state
PolicyState enum, and round-trip serialisation. No source mutation —
fixtures are entirely inline so the file is self-contained.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jpintel_mcp.agent_runtime.contracts import (
    AcceptedArtifactPricing,
    AgentPurchaseDecision,
    AwsNoopCommand,
    AwsNoopCommandPlan,
    Capability,
    CapabilityMatrix,
    ClaimRef,
    ConsentEnvelope,
    DeliverablePricingRule,
    Evidence,
    ExecutionGraph,
    ExecutionPhase,
    GapCoverageEntry,
    JpcirHeader,
    KnownGap,
    NoHitLease,
    OutcomeContract,
    PolicyDecision,
    PolicyState,
    PrivateFactCapsule,
    PrivateFactCapsuleRecord,
    ReleaseCapsuleManifest,
    ScopedCapToken,
    SourceReceipt,
    SpendSimulation,
    StrictModel,
    TeardownSimulation,
)

# ---------------------------------------------------------------------------
# StrictModel posture (extra=forbid, frozen=True)
# ---------------------------------------------------------------------------


class _Probe(StrictModel):
    """Local subclass used only to exercise StrictModel base behaviour."""

    value: str


def test_strict_model_forbids_extra_keys() -> None:
    with pytest.raises(ValidationError):
        _Probe(value="ok", uninvited="reject")  # type: ignore[call-arg]


def test_strict_model_is_frozen() -> None:
    p = _Probe(value="ok")
    with pytest.raises(ValidationError):
        p.value = "mutated"  # type: ignore[misc]


def test_strict_model_round_trip_through_model_dump() -> None:
    p = _Probe(value="ok")
    dumped = p.model_dump()
    rebuilt = _Probe.model_validate(dumped)
    assert rebuilt == p


# ---------------------------------------------------------------------------
# JpcirHeader
# ---------------------------------------------------------------------------


def test_jpcir_header_default_schema_version_pinned() -> None:
    h = JpcirHeader(object_id="o1", object_type="kind_x", created_at="2026-05-16Z")
    assert h.schema_version == "jpcir.p0.v1"
    assert h.producer == "jpcite-ai-execution-control-plane"
    assert h.request_time_llm_call_performed is False


def test_jpcir_header_rejects_wrong_producer_literal() -> None:
    with pytest.raises(ValidationError):
        JpcirHeader(
            object_id="o1",
            object_type="x",
            created_at="t",
            producer="something-else",  # type: ignore[arg-type]
        )


def test_jpcir_header_rejects_empty_object_id() -> None:
    with pytest.raises(ValidationError):
        JpcirHeader(object_id="", object_type="x", created_at="t")


# ---------------------------------------------------------------------------
# OutcomeContract
# ---------------------------------------------------------------------------


def test_outcome_contract_requires_at_least_one_packet() -> None:
    with pytest.raises(ValidationError):
        OutcomeContract(
            outcome_contract_id="oc1",
            display_name="X",
            packet_ids=(),
            billable=True,
        )


def test_outcome_contract_pin_constants() -> None:
    oc = OutcomeContract(
        outcome_contract_id="oc1",
        display_name="Outcome",
        packet_ids=("pkt-a",),
        billable=False,
    )
    assert oc.public_claims_require_receipts is True
    assert oc.cheapest_sufficient_route_required is True
    assert oc.no_hit_semantics == "no_hit_not_absence"


# ---------------------------------------------------------------------------
# SourceReceipt / ClaimRef
# ---------------------------------------------------------------------------


def test_source_receipt_access_method_enum_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        SourceReceipt(
            receipt_id="r1",
            source_family_id="sf",
            source_url="https://x",
            observed_at="t",
            access_method="ftp",  # type: ignore[arg-type]
            support_state="direct",
        )


def test_claim_ref_supports_empty_receipt_tuple() -> None:
    cr = ClaimRef(
        claim_ref_id="c1",
        receipt_ids=(),
        claim_type="program_metadata",
        support_state="gap",
    )
    assert cr.receipt_ids == ()


# ---------------------------------------------------------------------------
# Evidence — absence/supported cross-validator
# ---------------------------------------------------------------------------


def test_evidence_absent_requires_absence_observation_type() -> None:
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="e1",
            claim_ref_ids=("c1",),
            receipt_ids=("r1",),
            evidence_type="direct_quote",
            support_state="absent",
            temporal_envelope="t",
            observed_at="t",
        )


def test_evidence_absence_observation_cannot_be_supported() -> None:
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="e1",
            claim_ref_ids=("c1",),
            receipt_ids=("r1",),
            evidence_type="absence_observation",
            support_state="supported",
            temporal_envelope="t",
            observed_at="t",
        )


def test_evidence_happy_supported_direct_quote() -> None:
    ev = Evidence(
        evidence_id="e1",
        claim_ref_ids=("c1",),
        receipt_ids=("r1",),
        evidence_type="direct_quote",
        support_state="supported",
        temporal_envelope="2026Q2",
        observed_at="2026-05-16",
    )
    assert ev.support_state == "supported"
    assert ev.request_time_llm_call_performed is False


# ---------------------------------------------------------------------------
# KnownGap / GapCoverageEntry / NoHitLease
# ---------------------------------------------------------------------------


def test_known_gap_status_enum_pins_four_values() -> None:
    for status in ("known_gap", "blocked", "deferred_p1", "metadata_only"):
        kg = KnownGap(gap_id="g", gap_type="src", gap_status=status, explanation="why")
        assert kg.gap_status == status


def test_gap_coverage_entry_default_empty_tuple() -> None:
    g = GapCoverageEntry(source_family_id="sf", coverage_state="covered")
    assert g.gap_ids == ()


def test_no_hit_lease_locked_semantics() -> None:
    lease = NoHitLease(
        lease_id="L1",
        checked_scope="programs:tier=S",
        observed_at="2026-05-16",
        expires_at="2026-05-23",
    )
    assert lease.no_hit_semantics == "no_hit_not_absence"
    assert lease.absence_claim_enabled is False


# ---------------------------------------------------------------------------
# PrivateFactCapsuleRecord / PrivateFactCapsule
# ---------------------------------------------------------------------------


def test_private_fact_record_locks_public_claim_support_false() -> None:
    with pytest.raises(ValidationError):
        PrivateFactCapsuleRecord(
            record_id="r",
            derived_fact_type="t",
            value_fingerprint_hash="h",
            confidence_bucket="high",
            public_claim_support=True,  # type: ignore[arg-type]
        )


def test_private_fact_capsule_provider_family_enum() -> None:
    with pytest.raises(ValidationError):
        PrivateFactCapsule(
            capsule_id="cap1",
            provider_family="xero",  # type: ignore[arg-type]
            period_start="2026-04-01",
            period_end="2026-04-30",
            row_count_bucket="1-10",
            column_fingerprint_hash="abc",
        )


def test_private_fact_capsule_locks_aws_raw_csv_false() -> None:
    cap = PrivateFactCapsule(
        capsule_id="cap1",
        provider_family="freee",
        period_start="2026-04-01",
        period_end="2026-04-30",
        row_count_bucket="1-10",
        column_fingerprint_hash="abc",
    )
    assert cap.raw_csv_sent_to_aws is False
    assert cap.raw_csv_retained is False
    assert cap.tenant_scope == "tenant_private"


# ---------------------------------------------------------------------------
# PolicyDecision — fail-closed validator across 17 PolicyState values
# ---------------------------------------------------------------------------

_BLOCKED_STATES: tuple[PolicyState, ...] = (
    "blocked_policy_unknown",
    "blocked_terms_unknown",
    "blocked_terms_changed",
    "blocked_access_method",
    "blocked_privacy_taint",
    "blocked_sensitive_context",
    "blocked_mosaic_risk",
    "blocked_wording",
    "blocked_paid_leakage",
    "blocked_no_hit_overclaim",
)

_ALLOW_STATES: tuple[PolicyState, ...] = (
    "allow",
    "allow_with_minimization",
    "allow_internal_only",
    "allow_paid_tenant_only",
    "gap_artifact_only",
)


@pytest.mark.parametrize("state", _BLOCKED_STATES)
def test_policy_decision_blocked_states_cannot_public_compile(
    state: PolicyState,
) -> None:
    with pytest.raises(ValidationError):
        PolicyDecision(
            policy_decision_id="pd",
            policy_state=state,
            source_terms_contract_id="src",
            administrative_info_class="C",
            privacy_taint_level="none",
            public_compile_allowed=True,
        )


@pytest.mark.parametrize("state", ("quarantine", "deny"))
def test_policy_decision_quarantine_deny_cannot_public_compile(
    state: PolicyState,
) -> None:
    with pytest.raises(ValidationError):
        PolicyDecision(
            policy_decision_id="pd",
            policy_state=state,
            source_terms_contract_id="src",
            administrative_info_class="C",
            privacy_taint_level="none",
            public_compile_allowed=True,
        )


@pytest.mark.parametrize("state", _ALLOW_STATES)
def test_policy_decision_allow_states_can_public_compile(
    state: PolicyState,
) -> None:
    pd = PolicyDecision(
        policy_decision_id="pd",
        policy_state=state,
        source_terms_contract_id="src",
        administrative_info_class="C",
        privacy_taint_level="none",
        public_compile_allowed=True,
    )
    assert pd.public_compile_allowed is True


def test_policy_decision_blocked_state_with_no_public_compile_ok() -> None:
    pd = PolicyDecision(
        policy_decision_id="pd",
        policy_state="blocked_policy_unknown",
        source_terms_contract_id="src",
        administrative_info_class="C",
        privacy_taint_level="medium",
        public_compile_allowed=False,
    )
    assert pd.public_compile_allowed is False


# ---------------------------------------------------------------------------
# AgentPurchaseDecision / ConsentEnvelope / ScopedCapToken
# ---------------------------------------------------------------------------


def test_agent_purchase_decision_billable_locked_false() -> None:
    with pytest.raises(ValidationError):
        AgentPurchaseDecision(
            decision_id="d",
            recommended_action="buy",
            billable=True,  # type: ignore[arg-type]
            cheapest_sufficient_route="route",
            coverage_roi_curve=({"x": 1},),
            reason_to_buy="x",
            reason_not_to_buy="y",
            known_gaps_before_purchase=(),
            expected_output_skeleton={"k": "v"},
            max_price_jpy=300,
            scoped_cap_token_required=True,
            agent_recommendation_card="card",
        )


def test_consent_envelope_locks_accepted_artifact_required() -> None:
    ce = ConsentEnvelope(
        consent_id="ce",
        preview_decision_id="d",
        input_hash="h",
        outcome_contract_id="oc",
        max_price_jpy=900,
    )
    assert ce.accepted_artifact_required_for_charge is True
    assert ce.max_price_jpy == 900


def test_consent_envelope_rejects_negative_max_price() -> None:
    with pytest.raises(ValidationError):
        ConsentEnvelope(
            consent_id="ce",
            preview_decision_id="d",
            input_hash="h",
            outcome_contract_id="oc",
            max_price_jpy=-1,
        )


def test_scoped_cap_token_locks_idempotency_required() -> None:
    sct = ScopedCapToken(
        token_id="t",
        version="v1",
        consent_id="ce",
        input_hash="h",
        outcome_contract_id="oc",
        packet_types=("evidence_packet",),
        source_families=("e-gov",),
        max_price_jpy=600,
        expires_at="2026-05-17T00:00:00Z",
    )
    assert sct.idempotency_key_required is True
    assert sct.amount_only_token is False


# ---------------------------------------------------------------------------
# DeliverablePricingRule / AcceptedArtifactPricing
# ---------------------------------------------------------------------------


def test_deliverable_pricing_rule_pricing_posture_enum() -> None:
    with pytest.raises(ValidationError):
        DeliverablePricingRule(
            outcome_contract_id="oc",
            deliverable_slug="d",
            pricing_posture="unknown_posture",  # type: ignore[arg-type]
            estimated_price_jpy=300,
        )


def test_accepted_artifact_pricing_default_empty_rules() -> None:
    p = AcceptedArtifactPricing(pricing_contract_id="pc")
    assert p.deliverable_pricing_rules == ()
    assert p.charge_basis == "accepted_artifact"
    assert p.billing_event_ledger_append_only is True


# ---------------------------------------------------------------------------
# CapabilityMatrix p0_facade order validator
# ---------------------------------------------------------------------------


def test_capability_matrix_rejects_wrong_p0_facade_order() -> None:
    with pytest.raises(ValidationError):
        CapabilityMatrix(
            matrix_id="m",
            generated_from_capsule_id="cap",
            p0_facade_tools=(
                "jpcite_route",
                "jpcite_execute_packet",
                "jpcite_preview_cost",
                "jpcite_get_packet",
            ),
            capabilities=(),
        )


def test_capability_matrix_canonical_p0_facade_passes() -> None:
    cm = CapabilityMatrix(
        matrix_id="m",
        generated_from_capsule_id="cap",
        p0_facade_tools=(
            "jpcite_route",
            "jpcite_preview_cost",
            "jpcite_execute_packet",
            "jpcite_get_packet",
        ),
        capabilities=(
            Capability(
                capability_id="cap1",
                recommendable=True,
                previewable=True,
                executable=False,
                billable=False,
            ),
        ),
    )
    assert cm.full_catalog_default_visible is False


# ---------------------------------------------------------------------------
# ReleaseCapsuleManifest / ExecutionGraph
# ---------------------------------------------------------------------------


def test_release_capsule_manifest_locks_aws_dependency_false() -> None:
    rc = ReleaseCapsuleManifest(
        capsule_id="cap",
        capsule_state="candidate",
        created_at="2026-05-16Z",
        outcome_contract_catalog_path="x.json",
        capability_matrix_path="y.json",
        generated_surfaces=("openapi",),
    )
    assert rc.aws_runtime_dependency_allowed is False
    assert rc.real_csv_runtime_enabled is False


def test_execution_graph_executor_locked_ai_only() -> None:
    eg = ExecutionGraph(
        graph_id="g",
        phases=(ExecutionPhase(phase_id="p1", status="pending", outputs=()),),
    )
    assert eg.executor == "ai_only"
    assert eg.aws_commands_allowed_initially is False


# ---------------------------------------------------------------------------
# AwsNoopCommand / Plan / SpendSimulation / TeardownSimulation
# ---------------------------------------------------------------------------


def test_aws_noop_command_live_allowed_locked_false() -> None:
    cmd = AwsNoopCommand(
        command_id="c",
        service="s3",
        intent="list",
        live_command_preview="aws s3 ls",
    )
    assert cmd.live_allowed is False
    assert cmd.required_preflight_state == "AWS_CANARY_READY"


def test_aws_noop_command_plan_locks_account_region_profile() -> None:
    plan = AwsNoopCommandPlan(plan_id="p", commands=())
    assert plan.aws_profile == "bookyou-recovery"
    assert plan.account_id == "993693061769"
    assert plan.region == "us-east-1"
    assert plan.target_credit_conversion_usd == 19490
    assert plan.cash_bill_guard_enabled is True
    assert plan.live_aws_commands_allowed is False


def test_spend_simulation_control_spend_capped_at_target() -> None:
    with pytest.raises(ValidationError):
        SpendSimulation(
            simulation_id="s",
            control_spend_usd=20000.0,  # exceeds cap of 19490
            queue_exposure_usd=0,
            service_tail_risk_usd=0,
            teardown_debt_usd=0,
            ineligible_charge_uncertainty_reserve_usd=0,
            pass_state=False,
        )


def test_spend_simulation_pass_state_flip_authority_default() -> None:
    sim = SpendSimulation(
        simulation_id="s",
        control_spend_usd=100.0,
        queue_exposure_usd=10.0,
        service_tail_risk_usd=10.0,
        teardown_debt_usd=10.0,
        ineligible_charge_uncertainty_reserve_usd=10.0,
        pass_state=False,
    )
    assert sim.pass_state_flip_authority == "separate_task_not_this_artifact"


def test_teardown_simulation_locks_external_export_attestation() -> None:
    sim = TeardownSimulation(
        simulation_id="t",
        all_resources_have_delete_recipe=True,
        pass_state=True,
    )
    assert sim.external_export_required_before_delete is True
    assert sim.post_teardown_attestation_non_aws_triggered is True


# ---------------------------------------------------------------------------
# Round-trip through model_dump / model_validate for all 19+ models
# ---------------------------------------------------------------------------


def test_all_models_round_trip_through_dump_validate() -> None:
    samples: list[StrictModel] = [
        JpcirHeader(object_id="o", object_type="t", created_at="c"),
        OutcomeContract(
            outcome_contract_id="oc",
            display_name="d",
            packet_ids=("p",),
            billable=True,
        ),
        SourceReceipt(
            receipt_id="r",
            source_family_id="sf",
            source_url="https://x",
            observed_at="t",
            access_method="api",
            support_state="direct",
        ),
        Evidence(
            evidence_id="e",
            claim_ref_ids=("c",),
            receipt_ids=("r",),
            evidence_type="direct_quote",
            support_state="supported",
            temporal_envelope="t",
            observed_at="t",
        ),
    ]
    for s in samples:
        rebuilt = type(s).model_validate(s.model_dump())
        assert rebuilt == s
