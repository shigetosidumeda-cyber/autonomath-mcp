"""Deterministic bootstrap data for the jpcite agent-first runtime."""

from __future__ import annotations

from typing import Any

from jpintel_mcp.agent_runtime.accounting_csv_profiles import (
    build_accounting_csv_profile_catalog_shape,
)
from jpintel_mcp.agent_runtime.algorithm_blueprints import (
    build_algorithm_blueprint_catalog_shape,
)
from jpintel_mcp.agent_runtime.aws_execution_templates import (
    build_aws_execution_template_catalog,
)
from jpintel_mcp.agent_runtime.aws_spend_program import build_aws_spend_program
from jpintel_mcp.agent_runtime.contracts import (
    AcceptedArtifactPricing,
    AgentPurchaseDecision,
    AwsNoopCommand,
    AwsNoopCommandPlan,
    Capability,
    CapabilityMatrix,
    ConsentEnvelope,
    DeliverablePricingRule,
    ExecutionGraph,
    ExecutionPhase,
    JpcirHeader,
    OutcomeContract,
    ReleaseCapsuleManifest,
    ScopedCapToken,
    SpendSimulation,
    TeardownSimulation,
)
from jpintel_mcp.agent_runtime.outcome_catalog import (
    build_outcome_catalog,
    build_outcome_catalog_shape,
)
from jpintel_mcp.agent_runtime.outcome_source_crosswalk import (
    build_outcome_source_crosswalk_shape,
)
from jpintel_mcp.agent_runtime.pricing_policy import price_for_pricing_posture
from jpintel_mcp.agent_runtime.public_source_domains import (
    build_public_source_domain_catalog_shape,
)

CAPSULE_ID = "rc1-p0-bootstrap-2026-05-15"
CAPSULE_CREATED_AT = "2026-05-15T00:00:00+09:00"
TARGET_AWS_CREDIT_USD = 19490

P0_FACADE_TOOLS = (
    "jpcite_route",
    "jpcite_preview_cost",
    "jpcite_execute_packet",
    "jpcite_get_packet",
)

OUTCOME_CONTRACT_PACKET_IDS = {
    "company_public_baseline": (
        "company_profile",
        "source_receipts",
        "known_gaps",
    ),
    "invoice_registrant_public_check": (
        "invoice_registration_status",
        "source_receipts",
        "known_gaps",
    ),
    "application_strategy": (
        "normalized_applicant_profile",
        "ranked_candidates",
        "fit_signals",
        "questions_for_professional",
        "known_gaps",
    ),
    "regulation_change_watch": (
        "change_diff",
        "affected_workflows",
        "source_receipts",
    ),
    "local_government_permit_obligation_map": (
        "jurisdiction_profile",
        "permit_obligations",
        "source_receipts",
        "known_gaps",
    ),
    "court_enforcement_citation_pack": (
        "court_citations",
        "enforcement_notices",
        "claim_refs",
        "known_gaps",
    ),
    "public_statistics_market_context": (
        "statistics_snapshot",
        "market_context",
        "source_receipts",
        "known_gaps",
    ),
    "client_monthly_review": (
        "client_priority_queue",
        "this_month_watch_items",
        "deadline_risks",
        "questions_for_client",
        "office_tasks",
    ),
    "csv_overlay_public_check": (
        "csv_summary",
        "public_checks",
        "redacted_findings",
    ),
    "cashbook_csv_subsidy_fit_screen": (
        "cashbook_summary",
        "program_fit_signals",
        "questions_for_professional",
        "known_gaps",
    ),
    "source_receipt_ledger": (
        "receipt_ledger",
        "claim_graph",
        "coverage_gaps",
    ),
    "evidence_answer": (
        "answer",
        "claim_refs",
        "no_hit_lease",
        "known_gaps",
    ),
    "foreign_investor_japan_public_entry_brief": (
        "entry_brief",
        "disclosure_context",
        "regulatory_baseline",
        "known_gaps",
    ),
    "healthcare_regulatory_public_check": (
        "healthcare_notice_check",
        "regulatory_baseline",
        "local_requirements",
        "known_gaps",
    ),
}


def build_jpcir_header(object_id: str, object_type: str) -> JpcirHeader:
    return JpcirHeader(
        object_id=object_id,
        object_type=object_type,
        created_at=CAPSULE_CREATED_AT,
    )


def build_outcome_contract_catalog() -> tuple[OutcomeContract, ...]:
    free_contracts = (
        OutcomeContract(
            outcome_contract_id="agent_routing_decision",
            display_name="Agent routing decision",
            packet_ids=("route_decision",),
            billable=False,
        ),
        OutcomeContract(
            outcome_contract_id="cost_preview",
            display_name="Cost preview before purchase",
            packet_ids=("cost_preview",),
            billable=False,
        ),
    )

    paid_contracts = []
    for outcome in build_outcome_catalog():
        packet_ids = OUTCOME_CONTRACT_PACKET_IDS.get(outcome.outcome_contract_id)
        if packet_ids is None:
            raise ValueError(
                f"missing packet ids for outcome contract: {outcome.outcome_contract_id}"
            )
        paid_contracts.append(
            OutcomeContract(
                outcome_contract_id=outcome.outcome_contract_id,
                display_name=outcome.display_name,
                packet_ids=packet_ids,
                billable=outcome.high_value
                and outcome.billing_posture != "not_billable_preview_only",
            )
        )

    return (*free_contracts, *paid_contracts)


def build_capability_matrix() -> CapabilityMatrix:
    return CapabilityMatrix(
        matrix_id=f"{CAPSULE_ID}:capability-matrix",
        generated_from_capsule_id=CAPSULE_ID,
        p0_facade_tools=P0_FACADE_TOOLS,
        capabilities=(
            Capability(
                capability_id="jpcite_route",
                recommendable=True,
                previewable=False,
                executable=True,
                billable=False,
            ),
            Capability(
                capability_id="jpcite_preview_cost",
                recommendable=True,
                previewable=True,
                executable=True,
                billable=False,
            ),
            Capability(
                capability_id="jpcite_execute_packet",
                recommendable=True,
                previewable=False,
                executable=True,
                billable=True,
            ),
            Capability(
                capability_id="jpcite_get_packet",
                recommendable=True,
                previewable=False,
                executable=True,
                billable=False,
            ),
        ),
    )


def build_release_capsule_manifest() -> ReleaseCapsuleManifest:
    return ReleaseCapsuleManifest(
        capsule_id=CAPSULE_ID,
        capsule_state="candidate",
        created_at=CAPSULE_CREATED_AT,
        outcome_contract_catalog_path="/releases/rc1-p0-bootstrap/outcome_contract_catalog.json",
        capability_matrix_path="/releases/rc1-p0-bootstrap/capability_matrix.json",
        generated_surfaces=(
            "/.well-known/jpcite-release.json",
            "/releases/current/runtime_pointer.json",
            "/releases/rc1-p0-bootstrap/agent_surface/p0_facade.json",
            "/releases/rc1-p0-bootstrap/release_capsule_manifest.json",
            "/releases/rc1-p0-bootstrap/accounting_csv_profiles.json",
            "/releases/rc1-p0-bootstrap/algorithm_blueprints.json",
            "/releases/rc1-p0-bootstrap/aws_execution_templates.json",
            "/releases/rc1-p0-bootstrap/aws_spend_program.json",
            "/releases/rc1-p0-bootstrap/execution_graph.json",
            "/releases/rc1-p0-bootstrap/execution_state.json",
            "/releases/rc1-p0-bootstrap/inline_packets.json",
            "/releases/rc1-p0-bootstrap/noop_aws_command_plan.json",
            "/releases/rc1-p0-bootstrap/outcome_catalog.json",
            "/releases/rc1-p0-bootstrap/outcome_source_crosswalk.json",
            "/releases/rc1-p0-bootstrap/packet_skeletons.json",
            "/releases/rc1-p0-bootstrap/preflight_scorecard.json",
            "/releases/rc1-p0-bootstrap/public_source_domains.json",
        ),
    )


def build_accepted_artifact_pricing() -> AcceptedArtifactPricing:
    rules: list[DeliverablePricingRule] = []
    for entry in build_outcome_catalog():
        price_jpy = price_for_pricing_posture(entry.pricing_posture)
        if price_jpy is None:
            raise ValueError(
                f"unknown pricing posture for {entry.deliverable_slug}: {entry.pricing_posture}"
            )
        rules.append(
            DeliverablePricingRule(
                outcome_contract_id=entry.outcome_contract_id,
                deliverable_slug=entry.deliverable_slug,
                pricing_posture=entry.pricing_posture,
                estimated_price_jpy=price_jpy,
            )
        )
    return AcceptedArtifactPricing(
        pricing_contract_id=f"{CAPSULE_ID}:accepted-artifact-pricing",
        deliverable_pricing_rules=tuple(rules),
    )


def build_agent_purchase_decision() -> AgentPurchaseDecision:
    return AgentPurchaseDecision(
        decision_id=f"{CAPSULE_ID}:free-preview-decision",
        recommended_action="ask_followup",
        cheapest_sufficient_route="jpcite_preview_cost",
        coverage_roi_curve=(
            {"coverage": 0.35, "price_jpy": 0, "decision": "use_free_guidance"},
            {"coverage": 0.72, "price_jpy": 300, "decision": "buy_if_time_sensitive"},
            {"coverage": 0.9, "price_jpy": 900, "decision": "buy"},
        ),
        reason_to_buy="Buy only when the requested artifact needs cited public-source evidence or private CSV overlay checks.",
        reason_not_to_buy="Do not buy if free guidance is enough or the source coverage is below the accepted-artifact threshold.",
        known_gaps_before_purchase=("source_freshness_not_live_until_capsule_activation",),
        expected_output_skeleton={
            "artifact_id": "string",
            "outcome_contract_id": "string",
            "claims": [{"text": "string", "claim_ref_id": "string"}],
            "source_receipts": ["receipt_id"],
            "known_gaps": ["gap_id"],
            "no_hit_lease": "no_hit_not_absence",
        },
        max_price_jpy=0,
        scoped_cap_token_required=True,
        agent_recommendation_card=(
            "Preview first. Execute a paid packet only after the user accepts "
            "the outcome, max price, source families, and no-hit caveat."
        ),
    )


def build_consent_envelope() -> ConsentEnvelope:
    return ConsentEnvelope(
        consent_id=f"{CAPSULE_ID}:example-consent",
        preview_decision_id=f"{CAPSULE_ID}:free-preview-decision",
        input_hash="sha256:example-input-hash",
        outcome_contract_id="company_public_baseline",
        max_price_jpy=300,
    )


def build_scoped_cap_token() -> ScopedCapToken:
    return ScopedCapToken(
        token_id=f"{CAPSULE_ID}:example-scoped-cap-token",
        version="p0.v1",
        consent_id=f"{CAPSULE_ID}:example-consent",
        input_hash="sha256:example-input-hash",
        outcome_contract_id="company_public_baseline",
        packet_types=("company_profile", "source_receipts", "known_gaps"),
        source_families=("gBizINFO", "nta_invoice", "edinet", "egov"),
        max_price_jpy=300,
        expires_at="2026-05-16T00:00:00+09:00",
    )


def build_execution_graph() -> ExecutionGraph:
    return ExecutionGraph(
        graph_id=f"{CAPSULE_ID}:execution-graph",
        phases=(
            ExecutionPhase(
                phase_id="p0_contract_surface",
                status="ready",
                outputs=(
                    "outcome_contract_catalog.json",
                    "capability_matrix.json",
                    "p0_facade.json",
                ),
            ),
            ExecutionPhase(
                phase_id="ai_execution_resume_control",
                status="ready",
                outputs=(
                    "runtime_pointer.json",
                    "preflight_scorecard.json",
                    "docs/_internal/execution/rc1-p0-bootstrap/README.md",
                ),
            ),
            ExecutionPhase(
                phase_id="policy_trust_csv_boundaries",
                status="pending",
                outputs=(
                    "policy_decision_catalog.json",
                    "csv_private_overlay_contract.json",
                ),
            ),
            ExecutionPhase(
                phase_id="agent_billing_accepted_artifact",
                status="pending",
                outputs=(
                    "accepted_artifact_pricing.json",
                    "billing_event_ledger_schema.json",
                ),
            ),
            ExecutionPhase(
                phase_id="aws_noop_preflight",
                status="blocked",
                outputs=(
                    "noop_aws_command_plan.json",
                    "spend_simulation.json",
                    "teardown_simulation.json",
                ),
            ),
            ExecutionPhase(
                phase_id="aws_live_artifact_factory",
                status="blocked",
                outputs=(
                    "source_receipt_lake",
                    "public_packet_factory",
                    "post_teardown_attestation",
                ),
            ),
        ),
    )


def build_noop_aws_command_plan() -> AwsNoopCommandPlan:
    return AwsNoopCommandPlan(
        plan_id=f"{CAPSULE_ID}:aws-noop-command-plan",
        commands=(
            AwsNoopCommand(
                command_id="aws_identity_budget_inventory",
                service="sts/budgets/ce",
                intent="Verify account, credit/budget visibility, and cash-bill guard before any resource creation.",
                live_command_preview=(
                    "aws sts get-caller-identity --profile bookyou-recovery && "
                    "aws budgets describe-budgets --profile bookyou-recovery"
                ),
            ),
            AwsNoopCommand(
                command_id="artifact_lake_dry_run",
                service="s3/glue/athena",
                intent="Plan immutable source receipt storage and query catalog without creating buckets or tables.",
                live_command_preview=(
                    "aws s3api create-bucket --bucket jpcite-source-receipts-<run-id> "
                    "--region us-east-1 --profile bookyou-recovery"
                ),
            ),
            AwsNoopCommand(
                command_id="batch_playwright_dry_run",
                service="batch/ecs/ecr/cloudwatch",
                intent="Plan browser capture workers for official public sources with terms gates and capped queues.",
                live_command_preview=(
                    "aws batch submit-job --job-name jpcite-playwright-<run-id> "
                    "--profile bookyou-recovery"
                ),
            ),
            AwsNoopCommand(
                command_id="bedrock_ocr_embedding_dry_run",
                service="bedrock/textract/opensearch",
                intent="Plan extraction, OCR, embeddings, and search indexing only after cost eligibility is proven.",
                live_command_preview=(
                    "aws bedrock-runtime invoke-model --model-id <eligible-model> "
                    "--profile bookyou-recovery"
                ),
            ),
            AwsNoopCommand(
                command_id="teardown_attestation_dry_run",
                service="resource-groups-tagging-api/cloudwatch/logs",
                intent="Plan deletion, export, and post-teardown attestation before live jobs can start.",
                live_command_preview=(
                    "aws resourcegroupstaggingapi get-resources "
                    "--tag-filters Key=jpcite-run-id,Values=<run-id> "
                    "--profile bookyou-recovery"
                ),
            ),
        ),
    )


def build_spend_simulation() -> SpendSimulation:
    return SpendSimulation(
        simulation_id=f"{CAPSULE_ID}:spend-simulation",
        control_spend_usd=0,
        queue_exposure_usd=0,
        service_tail_risk_usd=0,
        teardown_debt_usd=0,
        ineligible_charge_uncertainty_reserve_usd=19490,
        pass_state=False,
    )


def build_teardown_simulation() -> TeardownSimulation:
    return TeardownSimulation(
        simulation_id=f"{CAPSULE_ID}:teardown-simulation",
        all_resources_have_delete_recipe=True,
        pass_state=False,
        live_phase_only_assertion_ids=(
            "operator_signed_unlock_present",
            "run_id_tag_inventory_empty",
        ),
    )


def build_p0_facade() -> dict[str, Any]:
    return {
        "schema_version": "jpcite.agent_facade.p0.v1",
        "capsule_id": CAPSULE_ID,
        "default_visibility": "p0_facade_only",
        "full_catalog_visible_by_default": False,
        "tools": [
            {
                "name": "jpcite_route",
                "billable": False,
                "purpose": "Choose the cheapest sufficient route and return whether a paid packet is justified.",
                "requires_user_consent": False,
            },
            {
                "name": "jpcite_preview_cost",
                "billable": False,
                "purpose": "Return max price, likely coverage, known gaps, and no-hit caveat before purchase.",
                "requires_user_consent": False,
            },
            {
                "name": "jpcite_execute_packet",
                "billable": True,
                "purpose": "Create an accepted artifact only with a scoped cap token and idempotency key.",
                "requires_user_consent": True,
            },
            {
                "name": "jpcite_get_packet",
                "billable": False,
                "purpose": "Retrieve an already-created packet, source receipts, and known gaps.",
                "requires_user_consent": False,
            },
        ],
        "billing_invariant": "charge_only_after_accepted_artifact",
        "aws_runtime_dependency_allowed": False,
        "request_time_llm_fact_generation_enabled": False,
    }


def build_preflight_scorecard() -> dict[str, Any]:
    return {
        "schema_version": "jpcite.preflight_scorecard.p0.v1",
        "capsule_id": CAPSULE_ID,
        "state": "AWS_BLOCKED_PRE_FLIGHT",
        "target_credit_conversion_usd": TARGET_AWS_CREDIT_USD,
        "cash_bill_guard_enabled": True,
        "live_aws_commands_allowed": False,
        "blocking_gates": [
            "policy_trust_csv_boundaries",
            "accepted_artifact_billing_contract",
            "aws_budget_cash_guard_canary",
            "spend_simulation_pass_state",
            "teardown_simulation_pass_state",
        ],
        "resume_rule": (
            "Any AI session may continue local contract implementation, but must "
            "not run live AWS commands until this state becomes AWS_CANARY_READY."
        ),
    }


def build_execution_state() -> dict[str, Any]:
    return {
        "schema_version": "jpcite.execution_state.p0.v1",
        "capsule_id": CAPSULE_ID,
        "updated_at": CAPSULE_CREATED_AT,
        "loop_mode": "continuous_until_plan_complete",
        "current_phase": "pre_live_aws_readiness",
        "state": "AWS_BLOCKED_PRE_FLIGHT",
        "live_aws_commands_allowed": False,
        "aws_profile": "bookyou-recovery",
        "aws_account_id": "993693061769",
        "aws_region": "us-east-1",
        "target_credit_conversion_usd": TARGET_AWS_CREDIT_USD,
        "last_validated_commands": [
            "scripts/check_agent_runtime_contracts.py",
            "scripts/ops/validate_release_capsule.py",
            "scripts/ops/check_jpcir_schema_fixtures.py",
            "scripts/ops/aws_credit_local_preflight.py --warn-only",
            "scripts/check_openapi_drift.py",
            "scripts/check_mcp_drift.py",
            "scripts/probe_runtime_distribution.py",
        ],
        "next_resume_actions": [
            "complete read-only AWS identity/budget/inventory inspection gate",
            "prove budget and cash-bill guards before any resource creation",
            "prove every planned AWS resource type has a delete recipe",
            "keep P0 facade and accepted-artifact billing gates green",
        ],
        "hard_stop_conditions": [
            "preflight_scorecard.state != AWS_CANARY_READY",
            "preflight_scorecard.live_aws_commands_allowed is not true",
            "spend_simulation.pass_state is not true",
            "teardown_simulation.pass_state is not true",
            "cash_bill_guard_enabled is not true",
        ],
    }


def build_runtime_pointer() -> dict[str, Any]:
    return {
        "schema_version": "jpcite.runtime_pointer.p0.v1",
        "active_capsule_id": CAPSULE_ID,
        "active_capsule_manifest": "/releases/rc1-p0-bootstrap/release_capsule_manifest.json",
        "capsule_state": "candidate",
        "live_aws_commands_allowed": False,
        "aws_runtime_dependency_allowed": False,
        "next_resume_doc": "docs/_internal/execution/rc1-p0-bootstrap/README.md",
    }


def build_well_known_release(manifest_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": "jpcite.well_known_release.p0.v1",
        "capsule_id": CAPSULE_ID,
        "capsule_state": "candidate",
        "manifest_path": "/releases/rc1-p0-bootstrap/release_capsule_manifest.json",
        "manifest_sha256": manifest_sha256,
        "p0_facade_path": "/releases/rc1-p0-bootstrap/agent_surface/p0_facade.json",
        "runtime_pointer_path": "/releases/current/runtime_pointer.json",
        "live_aws_commands_allowed": False,
    }


def build_bootstrap_bundle() -> dict[str, Any]:
    """Return all deterministic P0 bootstrap objects in JSON-ready form."""

    from jpintel_mcp.agent_runtime.packet_skeletons import (  # noqa: PLC0415
        build_public_packet_skeleton_catalog_shape,
    )
    from jpintel_mcp.services.packets.inline_registry import (  # noqa: PLC0415
        build_inline_packet_catalog_shape,
    )

    objects = {
        "jpcir_header": build_jpcir_header(CAPSULE_ID, "release_capsule"),
        "release_capsule_manifest": build_release_capsule_manifest(),
        "outcome_contract_catalog": build_outcome_contract_catalog(),
        "capability_matrix": build_capability_matrix(),
        "accepted_artifact_pricing": build_accepted_artifact_pricing(),
        "agent_purchase_decision": build_agent_purchase_decision(),
        "consent_envelope_example": build_consent_envelope(),
        "scoped_cap_token_example": build_scoped_cap_token(),
        "execution_graph": build_execution_graph(),
        "noop_aws_command_plan": build_noop_aws_command_plan(),
        "spend_simulation": build_spend_simulation(),
        "teardown_simulation": build_teardown_simulation(),
    }
    dumped: dict[str, Any] = {}
    for key, value in objects.items():
        if isinstance(value, tuple):
            dumped[key] = [item.model_dump(mode="json") for item in value]
        else:
            dumped[key] = value.model_dump(mode="json")  # type: ignore[attr-defined]
    dumped["p0_facade"] = build_p0_facade()
    dumped["preflight_scorecard"] = build_preflight_scorecard()
    dumped["execution_state"] = build_execution_state()
    dumped["runtime_pointer"] = build_runtime_pointer()
    dumped["outcome_catalog"] = build_outcome_catalog_shape()
    dumped["accounting_csv_profiles"] = build_accounting_csv_profile_catalog_shape()
    dumped["algorithm_blueprints"] = build_algorithm_blueprint_catalog_shape()
    dumped["public_source_domains"] = build_public_source_domain_catalog_shape()
    dumped["aws_spend_program"] = build_aws_spend_program()
    dumped["aws_execution_templates"] = build_aws_execution_template_catalog()
    dumped["outcome_source_crosswalk"] = build_outcome_source_crosswalk_shape()
    dumped["packet_skeletons"] = build_public_packet_skeleton_catalog_shape()
    dumped["inline_packets"] = build_inline_packet_catalog_shape()
    return dumped
