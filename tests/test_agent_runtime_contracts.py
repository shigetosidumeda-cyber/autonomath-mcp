from pathlib import Path

import pytest

from jpintel_mcp.agent_runtime.contracts import (
    AwsNoopCommandPlan,
    CapabilityMatrix,
    PolicyDecision,
    PrivateFactCapsule,
    ReleaseCapsuleManifest,
    SpendSimulation,
    TeardownSimulation,
)
from jpintel_mcp.agent_runtime.defaults import (
    CAPSULE_ID,
    P0_FACADE_TOOLS,
    build_bootstrap_bundle,
    build_capability_matrix,
    build_execution_state,
    build_noop_aws_command_plan,
    build_outcome_contract_catalog,
    build_release_capsule_manifest,
    build_spend_simulation,
    build_teardown_simulation,
)
from jpintel_mcp.agent_runtime.outcome_catalog import build_outcome_catalog
from scripts.agent_runtime_bootstrap import build_artifact_map


def test_release_capsule_is_static_candidate_without_runtime_aws_or_llm() -> None:
    manifest = build_release_capsule_manifest()

    assert isinstance(manifest, ReleaseCapsuleManifest)
    assert manifest.capsule_id == CAPSULE_ID
    assert manifest.capsule_state == "candidate"
    assert manifest.aws_runtime_dependency_allowed is False
    assert manifest.real_csv_runtime_enabled is False
    assert manifest.request_time_llm_fact_generation_enabled is False
    assert manifest.no_hit_absence_claim_enabled is False


def test_p0_facade_has_exact_four_ordered_tools() -> None:
    matrix = build_capability_matrix()
    bundle = build_bootstrap_bundle()

    assert isinstance(matrix, CapabilityMatrix)
    assert matrix.p0_facade_tools == P0_FACADE_TOOLS
    assert [tool["name"] for tool in bundle["p0_facade"]["tools"]] == list(P0_FACADE_TOOLS)
    assert bundle["p0_facade"]["full_catalog_visible_by_default"] is False


def test_outcome_contract_catalog_covers_outcome_catalog_plus_free_controls() -> None:
    outcome_catalog = build_outcome_catalog()
    outcome_contract_ids = {outcome.outcome_contract_id for outcome in outcome_catalog}
    catalog = build_outcome_contract_catalog()
    contract_ids = [contract.outcome_contract_id for contract in catalog]

    assert len(contract_ids) == len(set(contract_ids))
    assert contract_ids[:2] == ["agent_routing_decision", "cost_preview"]
    assert set(contract_ids) == outcome_contract_ids | {
        "agent_routing_decision",
        "cost_preview",
    }

    contracts_by_id = {contract.outcome_contract_id: contract for contract in catalog}
    assert contracts_by_id["agent_routing_decision"].billable is False
    assert contracts_by_id["cost_preview"].billable is False

    for outcome in outcome_catalog:
        contract = contracts_by_id[outcome.outcome_contract_id]
        assert contract.packet_ids
        if outcome.high_value:
            assert contract.billable is True


def test_capability_matrix_rejects_tool_name_drift() -> None:
    with pytest.raises(ValueError, match="P0 facade tool order/name mismatch"):
        CapabilityMatrix(
            matrix_id="bad",
            generated_from_capsule_id=CAPSULE_ID,
            p0_facade_tools=("jpcite_cost_preview",),
            capabilities=(),
        )


def test_blocked_policy_cannot_compile_to_public_surfaces() -> None:
    with pytest.raises(ValueError, match="blocked policy states"):
        PolicyDecision(
            policy_decision_id="bad-policy",
            policy_state="blocked_terms_unknown",
            source_terms_contract_id="terms",
            administrative_info_class="public_web",
            privacy_taint_level="none",
            public_compile_allowed=True,
        )


def test_private_fact_capsule_cannot_be_public_source_receipt() -> None:
    capsule = PrivateFactCapsule(
        capsule_id="pfc_example",
        provider_family="freee",
        period_start="2026-01-01",
        period_end="2026-03-31",
        row_count_bucket="100-999",
        column_fingerprint_hash="sha256:columns",
        records=(
            {
                "record_id": "pfc_record_1",
                "derived_fact_type": "expense_bucket",
                "value_fingerprint_hash": "sha256:value",
                "confidence_bucket": "high",
            },
        ),
    )

    assert capsule.tenant_scope == "tenant_private"
    assert capsule.raw_csv_retained is False
    assert capsule.raw_csv_logged is False
    assert capsule.raw_csv_sent_to_aws is False
    assert capsule.public_surface_export_allowed is False
    assert capsule.source_receipt_compatible is False
    assert capsule.records[0].public_claim_support is False
    assert capsule.records[0].source_receipt_compatible is False


def test_aws_plan_is_noop_until_canary_ready() -> None:
    plan = build_noop_aws_command_plan()
    spend = build_spend_simulation()
    teardown = build_teardown_simulation()

    assert isinstance(plan, AwsNoopCommandPlan)
    assert isinstance(spend, SpendSimulation)
    assert isinstance(teardown, TeardownSimulation)
    assert plan.aws_profile == "bookyou-recovery"
    assert plan.account_id == "993693061769"
    assert plan.region == "us-east-1"
    assert plan.target_credit_conversion_usd == 19490
    assert plan.cash_bill_guard_enabled is True
    assert plan.live_aws_commands_allowed is False
    assert all(command.live_allowed is False for command in plan.commands)
    assert spend.pass_state is False
    assert teardown.pass_state is False


def test_execution_state_is_resumable_and_blocks_live_aws() -> None:
    state = build_execution_state()

    assert state["loop_mode"] == "continuous_until_plan_complete"
    assert state["current_phase"] == "pre_live_aws_readiness"
    assert state["state"] == "AWS_BLOCKED_PRE_FLIGHT"
    assert state["live_aws_commands_allowed"] is False
    assert state["target_credit_conversion_usd"] == 19490
    assert "scripts/check_openapi_drift.py" in state["last_validated_commands"]
    assert "preflight_scorecard.state != AWS_CANARY_READY" in state["hard_stop_conditions"]


def test_bootstrap_artifact_map_contains_resume_and_schema_outputs(tmp_path: Path) -> None:
    artifact_map = build_artifact_map(tmp_path)
    relative_paths = {str(path.relative_to(tmp_path)) for path in artifact_map}

    assert "site/.well-known/jpcite-release.json" in relative_paths
    assert "site/releases/current/runtime_pointer.json" in relative_paths
    assert "site/releases/rc1-p0-bootstrap/agent_surface/p0_facade.json" in relative_paths
    assert "site/releases/rc1-p0-bootstrap/execution_state.json" in relative_paths
    assert "site/releases/rc1-p0-bootstrap/outcome_catalog.json" in relative_paths
    assert "site/releases/rc1-p0-bootstrap/outcome_contract_catalog.json" in relative_paths
    assert "site/releases/rc1-p0-bootstrap/accounting_csv_profiles.json" in relative_paths
    assert "site/releases/rc1-p0-bootstrap/algorithm_blueprints.json" in relative_paths
    assert "site/releases/rc1-p0-bootstrap/outcome_source_crosswalk.json" in relative_paths
    assert "site/releases/rc1-p0-bootstrap/packet_skeletons.json" in relative_paths
    assert "site/releases/rc1-p0-bootstrap/inline_packets.json" in relative_paths
    assert "site/releases/rc1-p0-bootstrap/public_source_domains.json" in relative_paths
    assert "site/releases/rc1-p0-bootstrap/aws_spend_program.json" in relative_paths
    assert "site/releases/rc1-p0-bootstrap/aws_execution_templates.json" in relative_paths
    assert "docs/_internal/execution/rc1-p0-bootstrap/README.md" in relative_paths
    assert "schemas/jpcir/private_fact_capsule.schema.json" in relative_paths
    assert "schemas/jpcir/_registry.json" in relative_paths


def test_bootstrap_static_outcome_contract_catalog_is_expanded(tmp_path: Path) -> None:
    artifact_map = build_artifact_map(tmp_path)
    static_catalog = artifact_map[
        tmp_path / "site" / "releases" / "rc1-p0-bootstrap" / "outcome_contract_catalog.json"
    ]

    static_contract_ids = [contract["outcome_contract_id"] for contract in static_catalog]
    expected_contract_ids = [
        contract.outcome_contract_id for contract in build_outcome_contract_catalog()
    ]

    assert static_contract_ids == expected_contract_ids
    assert "cashbook_csv_subsidy_fit_screen" in static_contract_ids
    assert "healthcare_regulatory_public_check" in static_contract_ids


def test_bootstrap_bundle_includes_agent_value_planning_catalogs() -> None:
    bundle = build_bootstrap_bundle()

    assert bundle["outcome_catalog"]["request_time_llm_dependency"] is False
    assert bundle["accounting_csv_profiles"]["schema_version"] == (
        "jpcite.accounting_csv_profiles.p0.v1"
    )
    assert bundle["algorithm_blueprints"]["llm_allowed"] is False
    assert bundle["algorithm_blueprints"]["network_allowed"] is False
    assert bundle["outcome_source_crosswalk"]["schema_version"] == (
        "jpcite.outcome_source_crosswalk.p0.v1"
    )
    assert bundle["packet_skeletons"]["schema_version"] == ("jpcite.packet_skeleton_catalog.p0.v1")
    assert bundle["packet_skeletons"]["paid_packet_body_materialized"] is False
    assert len(bundle["packet_skeletons"]["skeletons"]) == len(build_outcome_catalog())
    assert bundle["inline_packets"]["schema_version"] == "jpcite.inline_packet_catalog.p0.v1"
    assert bundle["inline_packets"]["billable"] is False
    assert bundle["inline_packets"]["paid_packet_body_materialized"] is False
    assert bundle["inline_packets"]["packets"]["outcome_catalog_summary"][
        "deliverable_count"
    ] == len(build_outcome_catalog())
    assert (
        bundle["inline_packets"]["packets"]["source_receipt_ledger"]["receipt_ledger"][
            "public_claims_release_allowed"
        ]
        is True
    )
    assert bundle["public_source_domains"]["collection_enabled_initially"] is False
    assert bundle["public_source_domains"]["playwright_screenshot_max_px"] == 1600
    assert bundle["aws_spend_program"]["target_credit_spend_usd"] == 19490
    assert bundle["aws_spend_program"]["planned_target_sum_usd"] == 19490
    assert bundle["aws_spend_program"]["live_execution_allowed"] is False
    assert bundle["aws_execution_templates"]["target_credit_spend_usd"] == 19490
    assert bundle["aws_execution_templates"]["planned_target_sum_usd"] == 19490
    assert bundle["aws_execution_templates"]["live_execution_allowed"] is False
