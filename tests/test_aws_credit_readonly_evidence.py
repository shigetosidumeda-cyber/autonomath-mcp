import ast
import json
from pathlib import Path

from jpintel_mcp.agent_runtime.aws_credit_simulation import (
    GATE_BLOCKED,
    GATE_READY,
    build_preflight_simulation,
    exposure_inputs_from_mapping,
)
from scripts.ops import aws_credit_collect_readonly_evidence as collect

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ops" / "aws_credit_collect_readonly_evidence.py"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "aws_credit" / "readonly_evidence"


def test_helper_code_has_no_live_aws_execution_imports_or_calls() -> None:
    forbidden_imports = {"boto3", "botocore", "subprocess", "requests", "urllib3"}
    forbidden_attr_calls = {("os", "system"), ("pty", "spawn")}
    forbidden_name_calls = {"popen"}

    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"), filename=str(SCRIPT_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = {alias.name.split(".", maxsplit=1)[0] for alias in node.names}
            assert imported.isdisjoint(forbidden_imports)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".", maxsplit=1)[0] not in forbidden_imports
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name):
                assert (owner.id, node.func.attr) not in forbidden_attr_calls
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id.lower() not in forbidden_name_calls


def test_readonly_command_plan_contains_no_mutating_aws_verbs() -> None:
    plan = collect.readonly_command_plan()

    collect.assert_readonly_command_plan(plan)
    assert plan
    for command in plan:
        argv = tuple(command["argv"])
        assert argv[0] == "aws"
        assert command["mutates_aws"] is False
        assert collect.MUTATING_AWS_CLI_VERBS.isdisjoint(argv)


def test_default_mode_prints_plan_without_running_aws(capsys) -> None:
    exit_code = collect.main([])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Read-only AWS evidence command plan:" in output
    assert "aws sts get-caller-identity" in output
    assert "does not execute AWS commands" in output


def test_dry_run_json_prints_plan_without_preflight_or_evidence(capsys) -> None:
    exit_code = collect.main(["--dry-run-json"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["live_aws_commands_executed_by_helper"] is False
    assert output["read_only_command_plan"]
    assert "preflight" not in output
    assert "evidence" not in output


def test_captured_aws_inventory_alone_fails_closed() -> None:
    payload = collect.build_preflight_report_from_files(
        sts_json=FIXTURE_DIR / "sts_get_caller_identity.json",
        budgets_json=FIXTURE_DIR / "budgets_describe_budgets.json",
        tagging_json=FIXTURE_DIR / "tagging_get_resources.json",
        configured_region_file=FIXTURE_DIR / "configured_region.txt",
    )

    assert payload["evidence"]["evidence_files_supplied"] is True
    assert payload["evidence"]["evidence_complete"] is False
    assert payload["evidence"]["live_aws_commands_executed_by_helper"] is False
    assert payload["evidence"]["budget_guard"]["alerts_confirmed"] is False
    assert payload["evidence"]["tagging_inventory"]["missing_required_tag_keys_by_resource"] == {}
    assert payload["preflight"]["gate_state"] == GATE_BLOCKED


def test_parsed_complete_evidence_feeds_existing_preflight_model_to_ready() -> None:
    payload = collect.build_preflight_report_from_files(
        sts_json=FIXTURE_DIR / "sts_get_caller_identity.json",
        budgets_json=FIXTURE_DIR / "budgets_describe_budgets.json",
        tagging_json=FIXTURE_DIR / "tagging_get_resources.json",
        configured_region_file=FIXTURE_DIR / "configured_region.txt",
        operator_evidence_json=FIXTURE_DIR / "operator_assertions.json",
    )
    evidence = payload["evidence"]

    report = build_preflight_simulation(
        canary_conditions=evidence["canary_conditions"],
        exposure_inputs=exposure_inputs_from_mapping(evidence),
        inspection_evidence=evidence,
    )

    assert evidence["evidence_complete"] is True
    assert evidence["tagging_inventory"]["unexpected_data_class_values"] == {}
    assert payload["preflight"]["gate_state"] == GATE_READY
    assert report["gate_state"] == GATE_READY
