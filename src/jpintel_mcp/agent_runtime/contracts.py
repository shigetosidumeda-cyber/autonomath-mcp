"""P0 contract models for the agent-first jpcite runtime.

The models here are deliberately small and deterministic. They define the
objects that must exist before live AWS work can start: outcome contracts,
JPCIR records, policy states, agent purchase decisions, scoped cap tokens,
release capsules, execution graphs, and no-op AWS plans.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PolicyState = Literal[
    "allow",
    "allow_with_minimization",
    "allow_internal_only",
    "allow_paid_tenant_only",
    "gap_artifact_only",
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
    "quarantine",
    "deny",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JpcirHeader(StrictModel):
    schema_version: Literal["jpcir.p0.v1"] = "jpcir.p0.v1"
    object_id: str = Field(min_length=1)
    object_type: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    producer: Literal["jpcite-ai-execution-control-plane"] = "jpcite-ai-execution-control-plane"
    request_time_llm_call_performed: Literal[False] = False


class OutcomeContract(StrictModel):
    outcome_contract_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    packet_ids: tuple[str, ...] = Field(min_length=1)
    billable: bool
    public_claims_require_receipts: Literal[True] = True
    cheapest_sufficient_route_required: Literal[True] = True
    no_hit_semantics: Literal["no_hit_not_absence"] = "no_hit_not_absence"


class SourceReceipt(StrictModel):
    receipt_id: str = Field(min_length=1)
    source_family_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    observed_at: str = Field(min_length=1)
    access_method: Literal["api", "bulk", "html", "playwright", "ocr", "metadata_only"]
    support_state: Literal["direct", "indirect", "candidate", "gap"]


class ClaimRef(StrictModel):
    claim_ref_id: str = Field(min_length=1)
    receipt_ids: tuple[str, ...]
    claim_type: str = Field(min_length=1)
    support_state: Literal["supported", "candidate", "gap", "blocked"]


class Evidence(StrictModel):
    evidence_id: str = Field(min_length=1)
    claim_ref_ids: tuple[str, ...] = Field(min_length=1)
    receipt_ids: tuple[str, ...] = Field(min_length=1)
    evidence_type: Literal[
        "direct_quote",
        "structured_record",
        "metadata_only",
        "screenshot",
        "derived_inference",
        "absence_observation",
    ]
    support_state: Literal["supported", "partial", "contested", "absent"]
    temporal_envelope: str = Field(min_length=1)
    observed_at: str = Field(min_length=1)
    request_time_llm_call_performed: Literal[False] = False

    @model_validator(mode="after")
    def _absent_must_not_overclaim(self) -> Evidence:
        if self.support_state == "absent" and self.evidence_type != "absence_observation":
            raise ValueError("support_state=absent requires evidence_type=absence_observation")
        if self.support_state == "supported" and self.evidence_type == "absence_observation":
            raise ValueError("absence_observation cannot carry support_state=supported")
        return self


class KnownGap(StrictModel):
    gap_id: str = Field(min_length=1)
    gap_type: str = Field(min_length=1)
    gap_status: Literal["known_gap", "blocked", "deferred_p1", "metadata_only"]
    explanation: str = Field(min_length=1)


class GapCoverageEntry(StrictModel):
    source_family_id: str = Field(min_length=1)
    coverage_state: Literal["covered", "missing", "stale", "blocked", "deferred"]
    gap_ids: tuple[str, ...] = ()


class NoHitLease(StrictModel):
    lease_id: str = Field(min_length=1)
    checked_scope: str = Field(min_length=1)
    observed_at: str = Field(min_length=1)
    expires_at: str = Field(min_length=1)
    no_hit_semantics: Literal["no_hit_not_absence"] = "no_hit_not_absence"
    absence_claim_enabled: Literal[False] = False


class PrivateFactCapsuleRecord(StrictModel):
    record_id: str = Field(min_length=1)
    derived_fact_type: str = Field(min_length=1)
    value_fingerprint_hash: str = Field(min_length=1)
    confidence_bucket: Literal["low", "medium", "high"]
    public_claim_support: Literal[False] = False
    source_receipt_compatible: Literal[False] = False
    raw_value_retained: Literal[False] = False


class PrivateFactCapsule(StrictModel):
    capsule_id: str = Field(min_length=1)
    tenant_scope: Literal["tenant_private"] = "tenant_private"
    provider_family: Literal[
        "freee",
        "money_forward",
        "yayoi",
        "tkc",
        "unknown",
    ]
    period_start: str = Field(min_length=1)
    period_end: str = Field(min_length=1)
    row_count_bucket: str = Field(min_length=1)
    column_fingerprint_hash: str = Field(min_length=1)
    records: tuple[PrivateFactCapsuleRecord, ...] = ()
    raw_csv_retained: Literal[False] = False
    raw_csv_logged: Literal[False] = False
    raw_csv_sent_to_aws: Literal[False] = False
    row_level_retention_enabled: Literal[False] = False
    public_surface_export_allowed: Literal[False] = False
    source_receipt_compatible: Literal[False] = False


class PolicyDecision(StrictModel):
    policy_decision_id: str = Field(min_length=1)
    policy_state: PolicyState
    source_terms_contract_id: str = Field(min_length=1)
    administrative_info_class: str = Field(min_length=1)
    privacy_taint_level: Literal["none", "low", "medium", "high", "tenant_private"]
    allowed_surfaces: tuple[str, ...] = ()
    blocked_surfaces: tuple[str, ...] = ()
    blocked_reason_codes: tuple[str, ...] = ()
    public_compile_allowed: bool

    @model_validator(mode="after")
    def _blocked_states_fail_closed(self) -> PolicyDecision:
        if self.policy_state.startswith("blocked_") and self.public_compile_allowed:
            raise ValueError("blocked policy states cannot compile to public surfaces")
        if self.policy_state in {"quarantine", "deny"} and self.public_compile_allowed:
            raise ValueError("quarantine/deny cannot compile to public surfaces")
        return self


class AgentPurchaseDecision(StrictModel):
    decision_id: str = Field(min_length=1)
    recommended_action: Literal["buy", "ask_followup", "use_free_guidance", "skip"]
    billable: Literal[False] = False
    cheapest_sufficient_route: str = Field(min_length=1)
    coverage_roi_curve: tuple[dict[str, Any], ...]
    anti_upsell_gate_passed: Literal[True] = True
    reason_to_buy: str
    reason_not_to_buy: str
    known_gaps_before_purchase: tuple[str, ...]
    no_hit_caveat: Literal["no_hit_not_absence"] = "no_hit_not_absence"
    expected_output_skeleton: dict[str, Any]
    max_price_jpy: int = Field(ge=0)
    scoped_cap_token_required: bool
    agent_recommendation_card: str = Field(min_length=1)
    request_time_llm_call_performed: Literal[False] = False


class ConsentEnvelope(StrictModel):
    consent_id: str = Field(min_length=1)
    preview_decision_id: str = Field(min_length=1)
    input_hash: str = Field(min_length=1)
    outcome_contract_id: str = Field(min_length=1)
    max_price_jpy: int = Field(ge=0)
    accepted_artifact_required_for_charge: Literal[True] = True


class ScopedCapToken(StrictModel):
    token_id: str = Field(min_length=1)
    token_kind: Literal["scoped_cap_token"] = "scoped_cap_token"
    version: str = Field(min_length=1)
    consent_id: str = Field(min_length=1)
    input_hash: str = Field(min_length=1)
    outcome_contract_id: str = Field(min_length=1)
    packet_types: tuple[str, ...]
    source_families: tuple[str, ...]
    max_price_jpy: int = Field(ge=0)
    expires_at: str = Field(min_length=1)
    idempotency_key_required: Literal[True] = True
    amount_only_token: Literal[False] = False


class DeliverablePricingRule(StrictModel):
    """Per-deliverable accepted-artifact pricing rule.

    Pinned to the JPY price emitted by ``price_for_pricing_posture`` so that
    the public JSON capsule, the Python catalog, and the billing ledger all
    agree on the same number for one ``outcome_contract_id``.
    """

    outcome_contract_id: str = Field(min_length=1)
    deliverable_slug: str = Field(min_length=1)
    pricing_posture: Literal[
        "free_preview",
        "accepted_artifact_low",
        "accepted_artifact_standard",
        "accepted_artifact_premium",
        "accepted_artifact_csv_overlay",
    ]
    estimated_price_jpy: int = Field(ge=0)
    billable_only_after_accepted_artifact: Literal[True] = True


class AcceptedArtifactPricing(StrictModel):
    pricing_contract_id: str = Field(min_length=1)
    charge_basis: Literal["accepted_artifact"] = "accepted_artifact"
    no_accepted_artifact_decision: Literal["no_charge_or_void"] = "no_charge_or_void"
    no_hit_billable_only_if_scoped_and_consented: Literal[True] = True
    billing_event_ledger_append_only: Literal[True] = True
    deliverable_pricing_rules: tuple[DeliverablePricingRule, ...] = ()


class Capability(StrictModel):
    capability_id: str = Field(min_length=1)
    recommendable: bool
    previewable: bool
    executable: bool
    billable: bool
    blocked: bool = False


class CapabilityMatrix(StrictModel):
    matrix_id: str = Field(min_length=1)
    generated_from_capsule_id: str = Field(min_length=1)
    p0_facade_tools: tuple[str, ...]
    full_catalog_default_visible: Literal[False] = False
    capabilities: tuple[Capability, ...]
    # Optional discovery extras: populated when the matrix is generated by
    # scripts/generate_capability_matrix.py to surface the full tool inventory
    # plus a free/paid + cost-band breakdown for AI agents browsing the
    # capsule. Older capsules omit these and remain valid.
    tool_count: int | None = None
    free_paid_breakdown: dict[str, Any] | None = None
    tools: tuple[dict[str, Any], ...] | None = None

    @model_validator(mode="after")
    def _p0_facade_is_canonical(self) -> CapabilityMatrix:
        expected = (
            "jpcite_route",
            "jpcite_preview_cost",
            "jpcite_execute_packet",
            "jpcite_get_packet",
        )
        if self.p0_facade_tools != expected:
            raise ValueError("P0 facade tool order/name mismatch")
        return self


class ReleaseCapsuleManifest(StrictModel):
    capsule_id: str = Field(min_length=1)
    capsule_state: Literal["candidate", "active", "previous", "quarantined"]
    created_at: str = Field(min_length=1)
    outcome_contract_catalog_path: str = Field(min_length=1)
    capability_matrix_path: str = Field(min_length=1)
    generated_surfaces: tuple[str, ...]
    aws_runtime_dependency_allowed: Literal[False] = False
    real_csv_runtime_enabled: Literal[False] = False
    request_time_llm_fact_generation_enabled: Literal[False] = False
    no_hit_absence_claim_enabled: Literal[False] = False


class ExecutionPhase(StrictModel):
    phase_id: str = Field(min_length=1)
    status: Literal["pending", "ready", "blocked", "complete"]
    outputs: tuple[str, ...]


class ExecutionGraph(StrictModel):
    graph_id: str = Field(min_length=1)
    executor: Literal["ai_only"] = "ai_only"
    aws_commands_allowed_initially: Literal[False] = False
    live_aws_phase_required: Literal[True] = True
    phases: tuple[ExecutionPhase, ...]


class AwsNoopCommand(StrictModel):
    command_id: str = Field(min_length=1)
    service: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    live_command_preview: str = Field(min_length=1)
    live_allowed: Literal[False] = False
    required_preflight_state: Literal["AWS_CANARY_READY"] = "AWS_CANARY_READY"
    requires_teardown_recipe: bool = False
    teardown_recipe_path_template: str | None = None


class AwsNoopCommandPlan(StrictModel):
    plan_id: str = Field(min_length=1)
    aws_profile: Literal["bookyou-recovery"] = "bookyou-recovery"
    account_id: Literal["993693061769"] = "993693061769"
    region: Literal["us-east-1"] = "us-east-1"
    target_credit_conversion_usd: Literal[19490] = 19490
    cash_bill_guard_enabled: Literal[True] = True
    live_aws_commands_allowed: Literal[False] = False
    commands: tuple[AwsNoopCommand, ...]


class SpendSimulation(StrictModel):
    simulation_id: str = Field(min_length=1)
    target_credit_conversion_usd: Literal[19490] = 19490
    control_spend_usd: float = Field(ge=0, le=19490)
    cash_bill_guard_enabled: Literal[True] = True
    queue_exposure_usd: float = Field(ge=0)
    service_tail_risk_usd: float = Field(ge=0)
    teardown_debt_usd: float = Field(ge=0)
    ineligible_charge_uncertainty_reserve_usd: float = Field(ge=0)
    pass_state: bool
    assertions_to_pass_state_true: tuple[str, ...] = ()
    pass_state_flip_authority: Literal[
        "separate_task_not_this_artifact",
        "preflight_runner",
        "operator",
    ] = "separate_task_not_this_artifact"


class TeardownSimulation(StrictModel):
    simulation_id: str = Field(min_length=1)
    all_resources_have_delete_recipe: bool
    external_export_required_before_delete: Literal[True] = True
    post_teardown_attestation_non_aws_triggered: Literal[True] = True
    pass_state: bool
    assertions_to_pass_state_true: tuple[str, ...] = ()
    live_phase_only_assertion_ids: tuple[str, ...] = ()
    pass_state_flip_authority: Literal[
        "separate_task_not_this_artifact",
        "preflight_runner",
        "operator",
    ] = "separate_task_not_this_artifact"


class FactMetadata(StrictModel):
    """Per-fact provenance envelope (Wave 51 dim O — explainable knowledge graph).

    Every am_entity_facts row carries this metadata so agents can verify the
    source-doc / extracted-at / verified-by / confidence axes. The schema
    parity gate (scripts/ops/validate_release_capsule.py) requires that this
    Pydantic class exist alongside schemas/jpcir/fact_metadata.schema.json.
    """

    source_doc: str = Field(min_length=1)
    extracted_at: str = Field(min_length=1)
    verified_by: Literal["manual", "cron_etl_v3", "ed25519_sig"]
    confidence: float = Field(ge=0.0, le=1.0)


class FederatedPartner(StrictModel):
    """Curated federated MCP partner row (Wave 51 dim R — recommendation hub).

    jpcite acts as the hub and deterministically recommends one of these
    partners when an agent query falls outside Japanese-public-program scope.
    Selection is keyword/capability match — NO LLM inference. Class name maps
    via snake_case to schemas/jpcir/federated_partner.schema.json so the
    release-capsule parity gate passes.
    """

    partner_id: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=128)
    official_url: str = Field(min_length=1, pattern=r"^https://")
    mcp_endpoint: str | None = None
    mcp_endpoint_status: Literal["official", "none_official"]
    capabilities: tuple[str, ...] = Field(min_length=1, max_length=16)
    use_when: str = Field(min_length=1, max_length=280)


class AcceptanceProbabilityCohortDefinition(StrictModel):
    """5-axis cohort definition for acceptance probability packets."""

    cohort_id: str = Field(min_length=1)
    prefecture: str = Field(min_length=1)
    jsic_major: str = Field(min_length=1, max_length=8)
    scale_band: Literal["micro", "small", "mid", "large", "unknown"]
    program_kind: str = Field(min_length=1)
    fiscal_year: str = Field(pattern=r"^[0-9]{4}$")


class AcceptanceProbabilityConfidenceInterval(StrictModel):
    """Wilson-score 95% confidence interval for acceptance probability."""

    method: Literal["wilson_score"] = "wilson_score"
    level: float = Field(default=0.95, ge=0.95, le=0.95)
    low: float = Field(ge=0.0, le=1.0)
    high: float = Field(ge=0.0, le=1.0)


class AcceptanceProbabilityAdjacency(StrictModel):
    """Adjacency suggestion entry (sibling cohort probability delta)."""

    cohort_id: str = Field(min_length=1)
    probability_estimate: float = Field(ge=0.0, le=1.0)
    delta: float


class AcceptanceProbabilityCohort(StrictModel):
    """Acceptance probability packet for a 5-axis adoption cohort.

    Wave 53 packet pipeline emits one row per (prefecture × jsic_major ×
    scale_band × program_kind × fiscal_year) cohort. Class name maps via
    snake_case to schemas/jpcir/acceptance_probability_cohort.schema.json
    so the release-capsule parity gate passes.
    """

    header: JpcirHeader
    package_kind: Literal["acceptance_probability_cohort_v1"] = (
        "acceptance_probability_cohort_v1"
    )
    cohort_definition: AcceptanceProbabilityCohortDefinition
    probability_estimate: float = Field(ge=0.0, le=1.0)
    confidence_interval: AcceptanceProbabilityConfidenceInterval
    n_sample: int = Field(ge=0)
    n_eligible_programs: int = Field(ge=0)
    freshest_announced_at: str | None = None
    adjacency_suggestions: tuple[AcceptanceProbabilityAdjacency, ...] = Field(
        default=(), max_length=5
    )
    known_gaps: tuple[KnownGap, ...] = Field(min_length=1)
    disclaimer: str = Field(min_length=1)


class CostPreviewSubject(StrictModel):
    """Canonical subject taxonomy for a cost-preview entry."""

    kind: Literal[
        "program",
        "houjin",
        "invoice",
        "cohort",
        "watchlist",
        "query",
        "rule_change",
        "jurisdiction",
        "court",
        "statistic",
        "csv",
        "control",
        # Wave 56-58 additions (time-series / geographic / relationship packets).
        # Each value is HONESTLY distinct from the original 12 canonical kinds:
        #   - industry      : JSIC industry-axis subject (distinct from cohort multi-axis profile).
        #   - certification : certification corpus subject (distinct from houjin reg-bound entity).
        #   - entity        : generic business-partner subject (no houjin reg number bound).
        #   - global        : 官報-scope, no jurisdiction or program pin.
        #   - ministry      : 省庁-pinned (distinct from prefecture/municipality jurisdiction).
        #   - name_prefix   : parent/subsidiary detection via name-prefix heuristic.
        #   - quarter       : quarter-over-quarter diff subject (time-axis only).
        #   - subject_area  : court-decision domain area (distinct from `court` venue).
        #   - tax_category  : tax_ruleset category subject (distinct from `rule_change` events).
        #   - vendor        : invoice-payment counterparty (distinct from `invoice` registrant subject).
        "industry",
        "certification",
        "entity",
        "global",
        "ministry",
        "name_prefix",
        "quarter",
        "subject_area",
        "tax_category",
        "vendor",
    ]
    id_hint: str | None = None


class CostPreviewEntry(StrictModel):
    """Single cost-preview entry for one paid outcome."""

    outcome_contract_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    package_kind: Literal[
        "evidence_packet",
        "artifact_pack",
        "precomputed_intelligence",
        "watch_digest",
        "agent_routing_control",
        "cost_control",
    ]
    subject: CostPreviewSubject
    cost_band: Literal["free", "light", "mid", "heavy"]
    estimated_price_jpy: int = Field(ge=0)
    free_preview_available: bool
    approval_token_required: bool
    idempotency_window_seconds: int = Field(ge=0)
    jpcite_cost_jpy: Literal[3] = 3
    estimated_tokens_saved: int = Field(ge=0)
    source_count: int = Field(ge=0)
    known_gaps: tuple[
        Literal[
            "pricing_or_cap_unconfirmed",
            "source_freshness_unconfirmed",
            "coverage_thin",
            "schema_drift_possible",
            "approval_token_semantics_pending",
            "idempotency_window_provisional",
            "free_preview_endpoint_pending",
        ],
        ...,
    ] = ()
    cap_per_day: int | None = None
    preview_endpoint: str | None = None


class CostPreviewPriceBands(StrictModel):
    """Canonical band → JPY mapping (light=¥300, mid=¥600, heavy=¥900)."""

    free: Literal[0] = 0
    light: Literal[300] = 300
    mid: Literal[600] = 600
    heavy: Literal[900] = 900


class CostPreviewCatalog(StrictModel):
    """Public cost-preview catalog advertised at /releases/.../cost_preview_catalog.json.

    Maps every paid outcome to a deterministic price band so AI agents can
    obtain a free cost preview before invoking a billable endpoint. Class
    name maps via snake_case to schemas/jpcir/cost_preview_catalog.schema.json
    so the release-capsule parity gate passes.
    """

    catalog_id: str = Field(min_length=1)
    schema_version: Literal["jpcite.cost_preview_catalog.p0.v1"] = (
        "jpcite.cost_preview_catalog.p0.v1"
    )
    generated_from_capsule_id: str = Field(min_length=1)
    jpcite_cost_jpy_unit: Literal[3] = 3
    price_bands: CostPreviewPriceBands
    entries: tuple[CostPreviewEntry, ...] = Field(min_length=1)
    generated_at: str | None = None
