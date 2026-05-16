import ast
from pathlib import Path

from jpintel_mcp.agent_runtime.aws_spend_program import (
    ARTIFACT_GENERATION,
    LIVE_EXECUTION_BLOCKED_STATE,
    OFFICIAL_PUBLIC_DATA_COLLECTION,
    REQUIRED_HARD_STOPS,
    REQUIRED_OUTPUT_CONNECTIONS,
    REQUIRED_PREFLIGHT_EVIDENCE,
    STAGED_NON_MUTATING_BATCHES,
    TARGET_CREDIT_SPEND_USD,
    build_aws_spend_program,
    hard_stop_overrun_detected,
    missing_preflight_evidence,
    planned_target_sum_usd,
    preflight_evidence_passes,
    total_hard_stop_usd,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OWNED_CODE = (
    REPO_ROOT / "src" / "jpintel_mcp" / "agent_runtime" / "aws_spend_program.py",
    REPO_ROOT / "tests" / "test_aws_spend_program.py",
)


def test_spend_program_target_sum_is_exact_and_not_overrun() -> None:
    blueprint = build_aws_spend_program()

    assert TARGET_CREDIT_SPEND_USD == 19490
    assert planned_target_sum_usd() == 19490
    assert total_hard_stop_usd() == 19490
    assert blueprint["planned_target_sum_usd"] == 19490
    assert blueprint["total_hard_stop_usd"] == 19490
    assert hard_stop_overrun_detected() is False
    assert blueprint["target_sum_rule"] == "sum(batch.spend_envelope.planned_usd) == 19490"
    assert "exceed 19490" in blueprint["no_overrun_rule"]


def test_batches_are_staged_non_mutating_execution_envelopes() -> None:
    blueprint = build_aws_spend_program()
    batches = blueprint["batches"]

    assert [batch["stage_name"] for batch in batches] == [
        "Preflight evidence lock",
        "Official source inventory",
        "Public collection capture",
        "OCR normalization and search build",
        "Claim graph and packet factory",
        "Quality evaluation and gap review",
        "Release artifact packaging",
        "Teardown attestation",
    ]
    assert len(batches) == len(STAGED_NON_MUTATING_BATCHES)
    assert batches[-1]["cumulative_planned_usd"] == 19490
    assert batches[-1]["remaining_target_after_stage_usd"] == 0
    for batch in batches:
        envelope = batch["spend_envelope"]
        assert batch["execution_mode"] == "offline_non_mutating_blueprint"
        assert batch["mutates_live_aws"] is False
        assert batch["aws_calls_allowed"] is False
        assert batch["subprocess_allowed"] is False
        assert batch["network_calls_allowed"] is False
        assert envelope["planned_usd"] == envelope["hard_stop_usd"]
        assert envelope["soft_stop_usd"] <= envelope["hard_stop_usd"]
        assert batch["data_asset_outputs"]
        assert batch["stop_conditions"]


def test_required_hard_stops_are_present_and_connected_to_batches() -> None:
    blueprint = build_aws_spend_program()
    rule_ids = {rule["rule_id"] for rule in blueprint["hard_stop_rules"]}
    batch_stop_ids = {
        condition for batch in blueprint["batches"] for condition in batch["stop_conditions"]
    }

    assert tuple(blueprint["preflight_evidence"]["missing"]) == REQUIRED_PREFLIGHT_EVIDENCE
    assert rule_ids == set(REQUIRED_HARD_STOPS)
    assert set(REQUIRED_HARD_STOPS) <= batch_stop_ids
    assert "preflight_evidence_missing" in batch_stop_ids
    assert "budget_cash_guard_missing" in batch_stop_ids
    assert "stage_hard_stop_would_exceed_target" in batch_stop_ids
    assert "missing_teardown_recipe_or_attestation" in batch_stop_ids


def test_live_execution_is_blocked_until_preflight_evidence_passes() -> None:
    blocked = build_aws_spend_program()

    assert blocked["live_execution_allowed"] is False
    assert blocked["live_execution_gate_state"] == LIVE_EXECUTION_BLOCKED_STATE
    assert blocked["preflight_evidence_passed"] is False
    assert missing_preflight_evidence() == REQUIRED_PREFLIGHT_EVIDENCE
    assert preflight_evidence_passes() is False

    passing_evidence = dict.fromkeys(REQUIRED_PREFLIGHT_EVIDENCE, True)
    ready = build_aws_spend_program(preflight_evidence=passing_evidence)

    assert ready["preflight_evidence_passed"] is True
    assert ready["preflight_evidence"]["missing"] == []
    assert preflight_evidence_passes(passing_evidence) is True
    assert ready["live_execution_allowed"] is False
    assert "separate operator unlock" in ready["live_execution_rule"]


def test_teardown_attestations_are_required_for_closeout() -> None:
    blueprint = build_aws_spend_program()
    top_level_attestations = {item["attestation_id"] for item in blueprint["teardown_attestations"]}
    batch_attestations = {
        item for batch in blueprint["batches"] for item in batch["teardown_attestations"]
    }

    assert top_level_attestations <= batch_attestations
    assert "delete_recipe_present_for_every_resource_class" in batch_attestations
    assert "tagged_resource_inventory_empty_or_explained" in batch_attestations
    assert "post_teardown_cost_meter_reviewed" in batch_attestations


def test_outputs_connect_public_collection_to_artifact_generation() -> None:
    blueprint = build_aws_spend_program()
    connections = set(blueprint["data_asset_output_connections"])

    assert set(REQUIRED_OUTPUT_CONNECTIONS) <= connections
    assert OFFICIAL_PUBLIC_DATA_COLLECTION in connections
    assert ARTIFACT_GENERATION in connections
    assert blueprint["official_public_source_families"]

    all_outputs = [
        output for batch in blueprint["batches"] for output in batch["data_asset_outputs"]
    ]
    assert any(
        output["connection"] == OFFICIAL_PUBLIC_DATA_COLLECTION
        and output["source_scope"] == "official_public_sources_only"
        for output in all_outputs
    )
    assert any(
        output["connection"] == ARTIFACT_GENERATION and "artifact" in output["artifact_kind"]
        for output in all_outputs
    )
    assert {
        "official_source_registry",
        "source_receipt_ledger",
        "evidence_packet_manifest",
        "public_packet_pages",
    } <= {output["asset_id"] for output in all_outputs}


def test_owned_spend_program_code_has_no_mutating_imports_or_calls() -> None:
    forbidden_imports = {
        "aiohttp",
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
        "urllib3",
    }
    forbidden_calls = {
        ("os", "system"),
        ("subprocess", "Popen"),
        ("subprocess", "call"),
        ("subprocess", "check_call"),
        ("subprocess", "check_output"),
        ("subprocess", "run"),
    }

    for path in OWNED_CODE:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name.split(".", maxsplit=1)[0] for alias in node.names}
                assert imported.isdisjoint(forbidden_imports), path
            if isinstance(node, ast.ImportFrom) and node.module:
                imported = node.module.split(".", maxsplit=1)[0]
                assert imported not in forbidden_imports, path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                if isinstance(owner, ast.Name):
                    assert (owner.id, node.func.attr) not in forbidden_calls, path
