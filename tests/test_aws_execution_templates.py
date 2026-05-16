import ast
from pathlib import Path

from jpintel_mcp.agent_runtime.aws_execution_templates import (
    BUDGET_GUARD_ATTESTATION_FIELDS,
    BUDGET_GUARD_TEMPLATE_IDS,
    LIVE_EXECUTION_BLOCKED_STATE,
    LIVE_EXECUTION_UNLOCKED_STATE,
    REQUIRED_OPERATOR_UNLOCK_FIELDS,
    REQUIRED_TAG_KEYS,
    RISK_ACCEPTANCE_FIELDS,
    SOURCE_POLICY_ATTESTATION_FIELDS,
    STAGED_QUEUE_MANIFESTS,
    TAG_POLICY_ATTESTATION_FIELDS,
    TARGET_CREDIT_SPEND_USD,
    TEARDOWN_RECIPE_ATTESTATION_FIELDS,
    build_aws_execution_template_catalog,
    build_operator_unlock_manifest_template,
    missing_teardown_recipe_resource_classes,
    operator_unlock_complete,
    planned_queue_target_usd,
    resource_classes_requiring_delete_recipe,
    resource_classes_with_delete_recipe,
    stage_ids,
    template_ids,
    validate_operator_unlock,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OWNED_CODE = (
    REPO_ROOT / "src" / "jpintel_mcp" / "agent_runtime" / "aws_execution_templates.py",
    REPO_ROOT / "tests" / "test_aws_execution_templates.py",
)


def test_owned_execution_template_code_has_no_boto_subprocess_or_network_imports() -> None:
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
    forbidden_attr_calls = {
        ("os", "system"),
        ("subprocess", "Popen"),
        ("subprocess", "call"),
        ("subprocess", "check_call"),
        ("subprocess", "check_output"),
        ("subprocess", "run"),
    }
    forbidden_name_calls = {"popen"}

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
                    assert (owner.id, node.func.attr) not in forbidden_attr_calls, path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id.lower() not in forbidden_name_calls, path


def test_catalog_is_data_only_and_target_remains_19490() -> None:
    catalog = build_aws_execution_template_catalog()

    assert TARGET_CREDIT_SPEND_USD == 19490
    assert planned_queue_target_usd() == 19490
    assert catalog["target_credit_spend_usd"] == 19490
    assert catalog["planned_target_sum_usd"] == 19490
    assert catalog["data_only"] is True
    assert catalog["no_aws_execution_performed"] is True
    assert catalog["network_calls_allowed"] is False
    assert catalog["subprocess_allowed"] is False
    assert catalog["live_execution_allowed_by_default"] is False
    assert catalog["live_execution_allowed"] is False
    assert catalog["live_execution_gate_state"] == LIVE_EXECUTION_BLOCKED_STATE
    assert len(catalog["staged_queue_manifests"]) == len(STAGED_QUEUE_MANIFESTS)
    assert catalog["staged_queue_manifests"][-1]["cumulative_planned_usd"] == 19490
    assert catalog["staged_queue_manifests"][-1]["remaining_target_after_stage_usd"] == 0


def test_budget_guard_templates_and_tag_policy_requirements_are_present() -> None:
    catalog = build_aws_execution_template_catalog()
    known_guard_refs = set(template_ids()) | {"operator_unlock_manifest"}
    budget_template_ids = {
        template["template_id"] for template in catalog["budget_guard_templates"]
    }
    tag_policy_keys = {requirement["tag_key"] for requirement in catalog["tag_policy_requirements"]}

    assert budget_template_ids == set(BUDGET_GUARD_TEMPLATE_IDS)
    assert {
        "budget_credit_gross_burn_guard",
        "budget_paid_cash_exposure_backstop",
        "budget_action_operator_stopline",
        "cost_anomaly_monitor_guard",
    } <= budget_template_ids
    assert tag_policy_keys == set(REQUIRED_TAG_KEYS)
    assert catalog["required_tag_keys"] == list(REQUIRED_TAG_KEYS)
    for template in catalog["execution_templates"]:
        assert set(template["guard_refs"]) <= known_guard_refs
    for manifest in catalog["staged_queue_manifests"]:
        assert set(manifest["guard_refs"]) <= known_guard_refs


def test_every_template_and_manifest_includes_required_tags() -> None:
    catalog = build_aws_execution_template_catalog()

    for template in catalog["execution_templates"]:
        _assert_required_tags(template["required_tags"])
    for manifest in catalog["staged_queue_manifests"]:
        _assert_required_tags(manifest["required_tags"])
    for recipe in catalog["teardown_recipes"]:
        _assert_required_tags(recipe["required_tags"])


def test_every_resource_class_has_delete_recipe() -> None:
    catalog = build_aws_execution_template_catalog()
    required_classes = set(resource_classes_requiring_delete_recipe())
    recipe_classes = set(resource_classes_with_delete_recipe())
    catalog_recipe_classes = {recipe["resource_class"] for recipe in catalog["teardown_recipes"]}

    assert missing_teardown_recipe_resource_classes() == ()
    assert required_classes
    assert required_classes <= recipe_classes
    assert required_classes <= catalog_recipe_classes


def test_mutating_operations_are_templates_not_commands() -> None:
    catalog = build_aws_execution_template_catalog()
    forbidden_command_keys = {"argv", "args", "command", "commands", "shell"}

    for template in catalog["execution_templates"]:
        assert forbidden_command_keys.isdisjoint(template)
        assert template["data_only"] is True
        assert template["live_execution_allowed"] is False
        for mutation in template["mutation_templates"]:
            assert forbidden_command_keys.isdisjoint(mutation)
            assert mutation["executable"] is False
            assert mutation["rendered_command"] is None
            assert "${" in mutation["operation_template"]

    for recipe in catalog["teardown_recipes"]:
        assert forbidden_command_keys.isdisjoint(recipe)
        assert recipe["data_only"] is True
        assert recipe["live_execution_allowed"] is False
        for mutation in recipe["delete_step_templates"] + recipe["verification_templates"]:
            assert forbidden_command_keys.isdisjoint(mutation)
            assert mutation["executable"] is False
            assert mutation["rendered_command"] is None
            assert "${" in mutation["operation_template"]


def test_live_execution_requires_complete_future_operator_unlock_object() -> None:
    default_catalog = build_aws_execution_template_catalog()
    incomplete_unlock = build_operator_unlock_manifest_template()

    assert operator_unlock_complete() is False
    assert operator_unlock_complete(incomplete_unlock) is False
    assert default_catalog["live_execution_allowed"] is False
    assert default_catalog["operator_unlock_validation"]["complete"] is False

    complete_unlock = _complete_unlock_manifest()
    unlocked_catalog = build_aws_execution_template_catalog(
        operator_unlock=complete_unlock,
    )

    assert operator_unlock_complete(complete_unlock) is True
    assert validate_operator_unlock(complete_unlock)["complete"] is True
    assert unlocked_catalog["live_execution_allowed"] is True
    assert unlocked_catalog["live_execution_gate_state"] == LIVE_EXECUTION_UNLOCKED_STATE
    assert unlocked_catalog["no_aws_execution_performed"] is True
    assert all(
        template["live_execution_allowed"] is False
        for template in unlocked_catalog["execution_templates"]
    )


def test_operator_unlock_manifest_schema_declares_required_contract() -> None:
    catalog = build_aws_execution_template_catalog()
    schema = catalog["operator_unlock_manifest_schema"]
    unlock_template = catalog["operator_unlock_template"]

    assert schema["schema_version"] == "jpcite.aws_operator_unlock_manifest.p0.v1"
    assert tuple(schema["required"]) == REQUIRED_OPERATOR_UNLOCK_FIELDS
    assert unlock_template["target_credit_spend_usd"] == 19490
    assert unlock_template["approved_stage_ids"] == []
    assert unlock_template["approved_template_ids"] == []
    assert set(unlock_template["budget_guard_attestation"]) == set(BUDGET_GUARD_ATTESTATION_FIELDS)
    assert set(unlock_template["tag_policy_attestation"]) == set(TAG_POLICY_ATTESTATION_FIELDS)
    assert set(unlock_template["teardown_recipe_attestation"]) == set(
        TEARDOWN_RECIPE_ATTESTATION_FIELDS
    )
    assert set(unlock_template["source_policy_attestation"]) == set(
        SOURCE_POLICY_ATTESTATION_FIELDS
    )
    assert set(unlock_template["risk_acceptance"]) == set(RISK_ACCEPTANCE_FIELDS)


def _assert_required_tags(tags: object) -> None:
    assert isinstance(tags, dict)
    assert set(REQUIRED_TAG_KEYS) <= set(tags)
    assert all(tags[key] for key in REQUIRED_TAG_KEYS)


def _complete_unlock_manifest() -> dict[str, object]:
    return {
        "schema_version": "jpcite.aws_operator_unlock_manifest.p0.v1",
        "unlock_id": "future-unlock-2026-05-15",
        "created_at_utc": "2026-05-15T00:00:00Z",
        "expires_at_utc": "2026-05-16T00:00:00Z",
        "operator_name": "Bookyou Operator",
        "operator_email": "operator@example.com",
        "aws_account_id": "123456789012",
        "aws_profile": "bookyou-recovery",
        "aws_region": "us-east-1",
        "billing_region": "us-east-1",
        "target_credit_spend_usd": TARGET_CREDIT_SPEND_USD,
        "approved_stage_ids": list(stage_ids()),
        "approved_template_ids": list(template_ids()),
        "budget_guard_attestation": dict.fromkeys(BUDGET_GUARD_ATTESTATION_FIELDS, True),
        "tag_policy_attestation": dict.fromkeys(TAG_POLICY_ATTESTATION_FIELDS, True),
        "teardown_recipe_attestation": dict.fromkeys(TEARDOWN_RECIPE_ATTESTATION_FIELDS, True),
        "source_policy_attestation": dict.fromkeys(SOURCE_POLICY_ATTESTATION_FIELDS, True),
        "risk_acceptance": {
            "operator_accepts_live_aws_mutation_templates": True,
            "target_19490_acknowledged": True,
            "rollback_owner_named": True,
            "live_run_window_utc": "2026-05-15T01:00:00Z/2026-05-15T06:00:00Z",
        },
        "operator_signature_sha256": f"sha256:{'a' * 64}",
    }
