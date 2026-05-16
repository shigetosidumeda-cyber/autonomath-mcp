import ast
import json
from pathlib import Path

from jpintel_mcp.agent_runtime.aws_credit_simulation import (
    AWS_ACCOUNT_ID,
    AWS_PROFILE,
    AWS_REGION,
    GATE_BLOCKED,
    GATE_READY,
    REQUIRED_BUDGET_GUARDS,
    REQUIRED_CANARY_CONDITIONS,
    REQUIRED_TAG_KEYS,
    TARGET_CREDIT_CONVERSION_USD,
    build_preflight_simulation,
    exposure_inputs_from_mapping,
)
from scripts.ops.aws_credit_local_preflight import build_report, main

REPO_ROOT = Path(__file__).resolve().parents[1]
OWNED_CODE = (
    REPO_ROOT / "src" / "jpintel_mcp" / "agent_runtime" / "aws_credit_simulation.py",
    REPO_ROOT / "scripts" / "ops" / "aws_credit_local_preflight.py",
)
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "aws_credit"


def test_owned_preflight_code_has_no_forbidden_imports_or_calls() -> None:
    forbidden_imports = {"boto3", "botocore", "subprocess", "requests", "urllib3"}
    forbidden_calls = {("os", "system")}

    for path in OWNED_CODE:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name.split(".", maxsplit=1)[0] for alias in node.names}
                assert imported.isdisjoint(forbidden_imports), path
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".", maxsplit=1)[0] not in forbidden_imports
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                if isinstance(owner, ast.Name):
                    assert (owner.id, node.func.attr) not in forbidden_calls


def test_blocked_by_default_without_canary_conditions() -> None:
    report = build_preflight_simulation()

    assert report["profile"] == AWS_PROFILE
    assert report["account_id"] == AWS_ACCOUNT_ID
    assert report["region"] == AWS_REGION
    assert report["target_credit_conversion_usd"] == TARGET_CREDIT_CONVERSION_USD
    assert report["gate_state"] == GATE_BLOCKED
    assert report["live_aws_commands_allowed"] is False
    assert tuple(report["missing_canary_conditions"]) == REQUIRED_CANARY_CONDITIONS
    assert report["exposure"]["queued_exposure_usd"] > 0
    assert report["exposure"]["teardown_debt_usd"] > 0
    assert report["exposure"]["ineligible_charge_uncertainty_reserve_usd"] > 0
    assert report["exposure"]["untagged_penalty_usd"] > 0
    assert report["exposure"]["stale_penalty_usd"] > 0
    assert report["account_identity"]["confirmed"] is False
    assert report["budget_guard"]["confirmed"] is False
    assert report["tagging_policy"]["confirmed"] is False
    assert report["teardown"]["all_resources_have_delete_recipe"] is False


def test_read_only_command_plan_contains_no_mutating_aws_actions() -> None:
    report = build_preflight_simulation()
    mutating_cli_verbs = {
        "cancel",
        "create",
        "delete",
        "detach",
        "invoke",
        "put",
        "run",
        "start",
        "stop",
        "submit",
        "terminate",
        "update",
    }

    assert report["live_aws_commands_allowed"] is False
    for command in report["read_only_command_plan"]:
        assert command["mutates_aws"] is False
        argv = tuple(command["argv"])
        assert argv[0] == "aws"
        assert not any(part in mutating_cli_verbs for part in argv)


def test_cli_report_is_blocked_by_default_fixture() -> None:
    report = build_report(FIXTURE_DIR / "blocked_default.json")

    assert report["gate_state"] == GATE_BLOCKED
    assert report["missing_canary_conditions"]
    assert report["account_identity"]["account_id_matches"] is False
    assert report["budget_guard"]["missing_budget_names"] == REQUIRED_BUDGET_GUARDS
    assert report["tagging_policy"]["missing_tag_keys"] == REQUIRED_TAG_KEYS


def test_cli_exit_codes_are_blocked_unless_warn_only() -> None:
    assert main(["--input", str(FIXTURE_DIR / "blocked_default.json"), "--warn-only"]) == 0
    assert main(["--input", str(FIXTURE_DIR / "blocked_default.json")]) == 1


def test_gate_ready_only_when_all_canaries_and_teardown_recipes_are_present() -> None:
    report = build_report(FIXTURE_DIR / "canary_ready.json")

    assert report["gate_state"] == GATE_READY
    assert report["missing_canary_conditions"] == ()
    assert report["account_identity"]["confirmed"] is True
    assert report["budget_guard"]["confirmed"] is True
    assert report["tagging_policy"]["confirmed"] is True
    assert report["teardown"]["all_resources_have_delete_recipe"] is True
    assert report["teardown"]["missing_recipe_refs"] == ()
    assert report["live_aws_commands_allowed"] is False


def test_identity_profile_or_region_mismatch_blocks_even_with_canaries() -> None:
    payload = json_payload(FIXTURE_DIR / "canary_ready.json")
    payload["aws_config"]["region"] = "ap-northeast-1"

    report = build_preflight_simulation(
        canary_conditions=payload["canary_conditions"],
        exposure_inputs=exposure_inputs_from_mapping(payload),
        inspection_evidence=payload,
    )

    assert report["gate_state"] == GATE_BLOCKED
    assert report["account_identity"]["account_id_matches"] is True
    assert report["account_identity"]["profile_matches"] is True
    assert report["account_identity"]["region_matches"] is False


def json_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
