#!/usr/bin/env python3
"""Validate generated P0 agent-runtime bootstrap artifacts."""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _maybe_reexec_venv() -> None:
    """Use the repo virtualenv when invoked by a bare system python.

    uv-managed venvs symlink to a shared interpreter, so ``Path.resolve()``
    collapses ``.venv/bin/python`` and the global ``python3.12`` to the same
    file. Detect "already in venv" via ``sys.prefix`` instead.
    """

    venv_dir = _REPO_ROOT / ".venv"
    venv_python = venv_dir / "bin" / "python"
    if (
        venv_python.exists()
        and Path(sys.prefix).resolve() != venv_dir.resolve()
        and os.environ.get("JPCITE_NO_VENV_REEXEC") != "1"
    ):
        os.environ["JPCITE_NO_VENV_REEXEC"] = "1"
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


_maybe_reexec_venv()

for _path in (_REPO_ROOT, _REPO_ROOT / "src"):
    _path_text = str(_path)
    if _path_text not in sys.path:
        sys.path.insert(0, _path_text)

from jpintel_mcp.agent_runtime.contracts import (
    AwsNoopCommandPlan,
    CapabilityMatrix,
    ExecutionGraph,
    PrivateFactCapsule,
    ReleaseCapsuleManifest,
    SpendSimulation,
    TeardownSimulation,
)
from jpintel_mcp.agent_runtime.defaults import CAPSULE_ID, P0_FACADE_TOOLS
from jpintel_mcp.agent_runtime.source_receipts import source_receipt_contract_issues

FORBIDDEN_AGENT_RUNTIME_IMPORTS = {
    "boto3",
    "botocore",
    "subprocess",
    "requests",
    "urllib.request",
    "csv",
}
EXPECTED_AWS_TEMPLATE_BUDGET_GUARDS = {
    "budget_credit_gross_burn_guard",
    "budget_paid_cash_exposure_backstop",
    "budget_action_operator_stopline",
    "cost_anomaly_monitor_guard",
}
EXPECTED_AWS_TEMPLATE_REQUIRED_TAGS = {
    "Project",
    "SpendProgram",
    "CreditRun",
    "Owner",
    "Environment",
    "Purpose",
    "AutoStop",
    "DataClass",
    "Workload",
}
FORBIDDEN_AWS_COMMAND_KEYS = {"argv", "args", "command", "commands", "shell"}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_required_aws_tags(tags: Any, label: str) -> None:
    _assert(isinstance(tags, dict), f"{label} missing required_tags")
    _assert(
        set(tags) >= EXPECTED_AWS_TEMPLATE_REQUIRED_TAGS,
        f"{label} required_tags incomplete",
    )
    _assert(tags["SpendProgram"] == "aws-credit-19490", f"{label} SpendProgram drift")
    _assert(tags["AutoStop"] == "required", f"{label} AutoStop drift")
    _assert(
        tags["DataClass"] in {"public-only", "synthetic-only", "derived-aggregate-only"},
        f"{label} DataClass drift",
    )
    _assert(
        all(tags[key] for key in EXPECTED_AWS_TEMPLATE_REQUIRED_TAGS),
        f"{label} blank required tag",
    )


def _assert_mutation_templates_are_offline(templates: Any, label: str) -> None:
    _assert(isinstance(templates, list) and templates, f"{label} missing mutation templates")
    for index, template in enumerate(templates):
        item_label = f"{label}[{index}]"
        _assert(isinstance(template, dict), f"{item_label} is not an object")
        _assert(
            FORBIDDEN_AWS_COMMAND_KEYS.isdisjoint(template),
            f"{item_label} contains executable command keys",
        )
        _assert(template.get("executable") is False, f"{item_label} executable")
        _assert(template.get("rendered_command") is None, f"{item_label} rendered command")
        _assert(
            "${" in template.get("operation_template", ""),
            f"{item_label} lost placeholders",
        )


def _validate_outcome_source_crosswalk_contract(
    outcome_catalog: dict[str, Any],
    accounting_csv_profiles: dict[str, Any],
    outcome_source_crosswalk: dict[str, Any],
) -> None:
    outcome_slugs = [
        deliverable["deliverable_slug"] for deliverable in outcome_catalog["deliverables"]
    ]
    _assert(
        outcome_source_crosswalk["schema_version"] == "jpcite.outcome_source_crosswalk.p0.v1",
        "outcome source crosswalk schema mismatch",
    )
    _assert(
        outcome_source_crosswalk["covered_deliverable_slugs"] == outcome_slugs,
        "outcome source crosswalk coverage/order mismatch",
    )
    _assert(
        len(outcome_source_crosswalk["crosswalk"]) == len(outcome_slugs),
        "outcome source crosswalk count mismatch",
    )

    csv_profile_keys = {profile["profile_key"] for profile in accounting_csv_profiles["profiles"]}
    outcomes_by_slug = {
        deliverable["deliverable_slug"]: deliverable
        for deliverable in outcome_catalog["deliverables"]
    }
    for entry in outcome_source_crosswalk["crosswalk"]:
        slug = entry["deliverable_slug"]
        outcome = outcomes_by_slug[slug]
        _assert(entry["algorithm_blueprint_ids"], f"{slug} missing algorithms")
        _assert(
            "evidence_join" in entry["algorithm_blueprint_ids"],
            f"{slug} missing evidence_join",
        )
        _assert(
            "no_hit_semantics" in entry["algorithm_blueprint_ids"],
            f"{slug} missing no_hit_semantics",
        )
        _assert(entry["aws_stage_ids"], f"{slug} missing AWS stages")
        _assert(entry["source_category_links"], f"{slug} missing source links")
        if outcome["requires_user_csv"]:
            _assert(entry["requires_csv_overlay"] is True, f"{slug} CSV overlay disabled")
            _assert(
                set(entry["accounting_csv_profile_keys"]) == csv_profile_keys,
                f"{slug} CSV profile mismatch",
            )
        else:
            _assert(entry["requires_csv_overlay"] is False, f"{slug} unexpected CSV overlay")
            _assert(entry["accounting_csv_profile_keys"] == [], f"{slug} unexpected CSV keys")


def _validate_packet_skeleton_catalog(data: dict[str, Any]) -> None:
    _assert(
        data["schema_version"] == "jpcite.packet_skeleton_catalog.p0.v1",
        "packet skeleton catalog schema mismatch",
    )
    _assert(data["paid_packet_body_materialized"] is False, "paid packet body materialized")
    _assert(data["request_time_llm_dependency"] is False, "packet skeletons enable LLM")
    _assert(data["live_network_dependency"] is False, "packet skeletons enable network")
    _assert(data["live_aws_dependency"] is False, "packet skeletons enable AWS")
    _assert(data["real_csv_runtime_enabled"] is False, "packet skeletons enable real CSV")
    _assert(data["no_hit_semantics"] == "no_hit_not_absence", "packet no-hit drift")
    _assert(isinstance(data["skeletons"], dict) and data["skeletons"], "missing skeletons")
    for outcome_contract_id, skeleton in data["skeletons"].items():
        _assert(
            skeleton["schema_version"] == "jpcite.packet_skeleton.p0.v1",
            f"{outcome_contract_id} skeleton schema mismatch",
        )
        _assert(
            skeleton["outcome_contract_id"] == outcome_contract_id,
            f"{outcome_contract_id} skeleton id mismatch",
        )
        _assert(skeleton["claims"], f"{outcome_contract_id} missing claims")
        _assert(
            skeleton["source_receipts"],
            f"{outcome_contract_id} missing source receipts",
        )
        _assert(skeleton["known_gaps"], f"{outcome_contract_id} missing gaps")
        _assert(
            skeleton["no_hit_semantics"]["rule"] == "no_hit_not_absence",
            f"{outcome_contract_id} no-hit rule drift",
        )
        _assert(
            skeleton["no_hit_semantics"]["absence_claim_enabled"] is False,
            f"{outcome_contract_id} absence claim enabled",
        )
        _assert(
            all(claim["visibility"] == "public" for claim in skeleton["claims"]),
            f"{outcome_contract_id} contains non-public claim",
        )
        receipt_issues = source_receipt_contract_issues(skeleton)
        _assert(
            not receipt_issues,
            f"{outcome_contract_id} source receipt issues: {receipt_issues}",
        )
        private_overlay = skeleton.get("private_overlay")
        if private_overlay:
            _assert(
                private_overlay["tenant_scope"] == "tenant_private",
                f"{outcome_contract_id} private overlay scope drift",
            )
            _assert(
                private_overlay["redaction_policy"] == "hash_only_private_facts",
                f"{outcome_contract_id} private overlay redaction drift",
            )
            _assert(
                private_overlay["csv_input_retained"] is False,
                f"{outcome_contract_id} retains CSV input",
            )
            _assert(
                private_overlay["csv_input_logged"] is False,
                f"{outcome_contract_id} logs CSV input",
            )
            _assert(
                private_overlay["csv_input_sent_to_aws"] is False,
                f"{outcome_contract_id} sends CSV input to AWS",
            )
            _assert(
                private_overlay["public_surface_export_allowed"] is False,
                f"{outcome_contract_id} exports private overlay",
            )
            _assert(
                private_overlay["source_receipt_compatible"] is False,
                f"{outcome_contract_id} treats private overlay as source receipt",
            )


def _validate_inline_packet_catalog(data: dict[str, Any]) -> None:
    _assert(
        data["schema_version"] == "jpcite.inline_packet_catalog.p0.v1",
        "inline packet catalog schema mismatch",
    )
    for key in (
        "billable",
        "accepted_artifact_created",
        "paid_packet_body_materialized",
        "request_time_llm_call_performed",
        "live_source_fetch_performed",
        "live_aws_dependency_used",
    ):
        _assert(data[key] is False, f"inline packet catalog {key} drift")
    _assert(data["charge_status"] == "not_charged", "inline packet catalog charged")
    _assert(
        data["packet_ids"]
        == ["outcome_catalog_summary", "source_receipt_ledger", "evidence_answer"],
        "inline packet ids drift",
    )
    for packet_id, packet in data["packets"].items():
        for key in (
            "billable",
            "accepted_artifact_created",
            "paid_packet_body_materialized",
            "request_time_llm_call_performed",
            "live_source_fetch_performed",
            "live_aws_dependency_used",
        ):
            _assert(packet[key] is False, f"{packet_id} inline packet {key} drift")
        ledger = packet["receipt_ledger"]
        _assert(
            ledger["public_claims_release_allowed"] is True,
            f"{packet_id} receipt ledger blocks release",
        )
        _assert(ledger["issues"] == [], f"{packet_id} receipt ledger issues")


def _validate_aws_execution_template_contract(data: dict[str, Any]) -> None:
    _assert(
        data["schema_version"] == "jpcite.aws_execution_templates.p0.v1",
        "AWS execution template schema mismatch",
    )
    _assert(data["execution_mode"] == "offline_template_catalog", "AWS template mode drift")
    _assert(data["target_credit_spend_usd"] == 19490, "AWS execution template target mismatch")
    _assert(data["planned_target_sum_usd"] == 19490, "AWS execution template sum mismatch")
    _assert(data["data_only"] is True, "AWS execution templates are not data-only")
    _assert(data["no_aws_execution_performed"] is True, "AWS execution was performed")
    _assert(data["network_calls_allowed"] is False, "AWS execution templates allow network")
    _assert(data["subprocess_allowed"] is False, "AWS execution templates allow subprocess")
    _assert(
        data["live_execution_allowed"] is False, "AWS execution templates enable live execution"
    )
    _assert(
        data["live_execution_allowed_by_default"] is False,
        "AWS execution templates enable live execution by default",
    )
    _assert(
        data["live_execution_gate_state"] == "AWS_TEMPLATE_CATALOG_BLOCKED",
        "AWS execution templates gate is not blocked",
    )
    _assert(
        set(data["budget_guard_template_ids"]) == EXPECTED_AWS_TEMPLATE_BUDGET_GUARDS,
        "AWS execution template budget guard mismatch",
    )
    _assert(
        set(data["required_tag_keys"]) == EXPECTED_AWS_TEMPLATE_REQUIRED_TAGS,
        "AWS execution template required tags mismatch",
    )

    planned_sum = sum(manifest["planned_usd"] for manifest in data["staged_queue_manifests"])
    _assert(planned_sum == 19490, "AWS execution staged queue sum mismatch")
    _assert(
        data["staged_queue_manifests"][-1]["cumulative_planned_usd"] == 19490,
        "AWS execution final cumulative target mismatch",
    )
    _assert(
        data["staged_queue_manifests"][-1]["remaining_target_after_stage_usd"] == 0,
        "AWS execution final remaining target mismatch",
    )

    recipe_classes = {recipe["resource_class"] for recipe in data["teardown_recipes"]}
    required_resource_classes = set()
    for index, template in enumerate(data["execution_templates"]):
        label = f"AWS execution templates execution_templates[{index}]"
        _assert(template["data_only"] is True, f"{label} not data-only")
        _assert(template["live_execution_allowed"] is False, f"{label} live enabled")
        _assert(template["unlock_required"] is True, f"{label} unlock not required")
        _assert_required_aws_tags(template["required_tags"], label)
        _assert_mutation_templates_are_offline(template["mutation_templates"], label)
        required_resource_classes.add(template["resource_class"])

    for index, manifest in enumerate(data["staged_queue_manifests"]):
        label = f"AWS execution templates staged_queue_manifests[{index}]"
        _assert(manifest["data_only"] is True, f"{label} not data-only")
        _assert(manifest["live_execution_allowed"] is False, f"{label} live enabled")
        _assert(manifest["unlock_required"] is True, f"{label} unlock not required")
        _assert_required_aws_tags(manifest["required_tags"], label)
        required_resource_classes.update(item["resource_class"] for item in manifest["queue_items"])

    for index, recipe in enumerate(data["teardown_recipes"]):
        label = f"AWS execution templates teardown_recipes[{index}]"
        _assert(recipe["data_only"] is True, f"{label} not data-only")
        _assert(recipe["live_execution_allowed"] is False, f"{label} live enabled")
        _assert_required_aws_tags(recipe["required_tags"], label)
        _assert_mutation_templates_are_offline(recipe["delete_step_templates"], label)
        _assert_mutation_templates_are_offline(recipe["verification_templates"], label)

    _assert(
        required_resource_classes <= recipe_classes,
        "AWS execution templates missing teardown recipes",
    )
    unlock_template = data["operator_unlock_template"]
    _assert(unlock_template["approved_stage_ids"] == [], "AWS unlock stages pre-approved")
    _assert(unlock_template["approved_template_ids"] == [], "AWS unlock templates pre-approved")
    _assert(unlock_template["target_credit_spend_usd"] == 19490, "AWS unlock target mismatch")
    unlock_validation = data["operator_unlock_validation"]
    _assert(unlock_validation["complete"] is False, "AWS unlock defaults complete")
    _assert(
        unlock_validation["live_execution_allowed_after_validation"] is False,
        "AWS unlock defaults live",
    )


def _validate_static_artifacts(repo_root: Path) -> None:
    capsule_dir = repo_root / "site" / "releases" / "rc1-p0-bootstrap"
    manifest = ReleaseCapsuleManifest.model_validate(
        _load(capsule_dir / "release_capsule_manifest.json")
    )
    capability_matrix = CapabilityMatrix.model_validate(
        _load(capsule_dir / "capability_matrix.json")
    )
    execution_graph = ExecutionGraph.model_validate(_load(capsule_dir / "execution_graph.json"))
    aws_plan = AwsNoopCommandPlan.model_validate(_load(capsule_dir / "noop_aws_command_plan.json"))
    spend = SpendSimulation.model_validate(_load(capsule_dir / "spend_simulation.json"))
    teardown = TeardownSimulation.model_validate(_load(capsule_dir / "teardown_simulation.json"))
    facade = _load(capsule_dir / "agent_surface" / "p0_facade.json")
    preflight = _load(capsule_dir / "preflight_scorecard.json")
    execution_state = _load(capsule_dir / "execution_state.json")
    outcome_catalog = _load(capsule_dir / "outcome_catalog.json")
    accounting_csv_profiles = _load(capsule_dir / "accounting_csv_profiles.json")
    algorithm_blueprints = _load(capsule_dir / "algorithm_blueprints.json")
    outcome_source_crosswalk = _load(capsule_dir / "outcome_source_crosswalk.json")
    packet_skeletons = _load(capsule_dir / "packet_skeletons.json")
    inline_packets = _load(capsule_dir / "inline_packets.json")
    public_source_domains = _load(capsule_dir / "public_source_domains.json")
    aws_spend_program = _load(capsule_dir / "aws_spend_program.json")
    aws_execution_templates = _load(capsule_dir / "aws_execution_templates.json")
    pointer = _load(repo_root / "site" / "releases" / "current" / "runtime_pointer.json")

    _assert(manifest.capsule_id == CAPSULE_ID, "capsule id mismatch")
    _assert(not manifest.aws_runtime_dependency_allowed, "capsule depends on AWS")
    _assert(not manifest.real_csv_runtime_enabled, "real CSV runtime is enabled")
    _assert(
        not manifest.request_time_llm_fact_generation_enabled,
        "request-time LLM fact generation is enabled",
    )
    _assert(capability_matrix.p0_facade_tools == P0_FACADE_TOOLS, "P0 tool mismatch")
    _assert(
        [tool["name"] for tool in facade["tools"]] == list(P0_FACADE_TOOLS),
        "P0 facade tool order mismatch",
    )
    _assert(
        facade["full_catalog_visible_by_default"] is False,
        "full catalog is visible by default",
    )
    _assert(aws_plan.target_credit_conversion_usd == 19490, "AWS target mismatch")
    _assert(
        aws_spend_program["target_credit_spend_usd"] == 19490,
        "AWS spend program target mismatch",
    )
    _assert(
        aws_spend_program["planned_target_sum_usd"] == 19490,
        "AWS spend program sum mismatch",
    )
    _assert(
        aws_spend_program["live_execution_allowed"] is False,
        "AWS spend program enables live execution",
    )
    _validate_aws_execution_template_contract(aws_execution_templates)
    _assert(aws_plan.cash_bill_guard_enabled, "cash bill guard disabled")
    _assert(not aws_plan.live_aws_commands_allowed, "live AWS commands enabled")
    _assert(
        all(not command.live_allowed for command in aws_plan.commands), "live AWS command leaked"
    )
    _assert(
        spend.pass_state is False or spend.pass_state_flip_authority == "preflight_runner",
        "spend simulation passed before canary without preflight_runner authority",
    )
    _assert(
        teardown.pass_state is False or teardown.pass_state_flip_authority == "preflight_runner",
        "teardown simulation passed before canary without preflight_runner authority",
    )
    # Stream W (2026-05-16): accept either AWS_BLOCKED_PRE_FLIGHT or
    # AWS_CANARY_READY. The hard invariant is that
    # ``live_aws_commands_allowed`` MUST remain False until operator unlock
    # (Stream I) — that flip is what truly gates live AWS.
    _assert(
        preflight["state"] in {"AWS_BLOCKED_PRE_FLIGHT", "AWS_CANARY_READY"},
        "preflight state mismatch",
    )
    _assert(
        execution_state["loop_mode"] == "continuous_until_plan_complete",
        "execution state loop mode mismatch",
    )
    _assert(
        execution_state["state"] in {"AWS_BLOCKED_PRE_FLIGHT", "AWS_CANARY_READY"},
        "execution state mismatch",
    )
    _assert(
        execution_state["live_aws_commands_allowed"] is False,
        "execution state enables AWS",
    )
    _assert(
        "preflight_scorecard.state != AWS_CANARY_READY" in execution_state["hard_stop_conditions"],
        "execution state is missing AWS hard stop",
    )
    _assert(
        outcome_catalog["request_time_llm_dependency"] is False,
        "outcome catalog enables request-time LLM",
    )
    _assert(
        accounting_csv_profiles["schema_version"] == "jpcite.accounting_csv_profiles.p0.v1",
        "accounting CSV profile catalog schema mismatch",
    )
    _assert(
        algorithm_blueprints["llm_allowed"] is False
        and algorithm_blueprints["network_allowed"] is False,
        "algorithm blueprints enable LLM or network",
    )
    _validate_outcome_source_crosswalk_contract(
        outcome_catalog,
        accounting_csv_profiles,
        outcome_source_crosswalk,
    )
    _validate_packet_skeleton_catalog(packet_skeletons)
    _validate_inline_packet_catalog(inline_packets)
    _assert(
        public_source_domains["collection_enabled_initially"] is False,
        "public source domain collection enabled initially",
    )
    _assert(
        public_source_domains["playwright_screenshot_max_px"] == 1600,
        "public source screenshot cap mismatch",
    )
    _assert(pointer["live_aws_commands_allowed"] is False, "runtime pointer enables AWS")
    _assert(execution_graph.aws_commands_allowed_initially is False, "graph enables AWS initially")


def _validate_private_fact_capsule_schema(repo_root: Path) -> None:
    schema_path = repo_root / "schemas" / "jpcir" / "private_fact_capsule.schema.json"
    _assert(schema_path.exists(), "private fact capsule schema missing")
    PrivateFactCapsule.model_validate(
        {
            "capsule_id": "pfc_example",
            "provider_family": "money_forward",
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "row_count_bucket": "100-999",
            "column_fingerprint_hash": "sha256:columns",
            "records": [
                {
                    "record_id": "pfc_record_1",
                    "derived_fact_type": "monthly_expense_bucket",
                    "value_fingerprint_hash": "sha256:value",
                    "confidence_bucket": "medium",
                }
            ],
        }
    )


def _validate_agent_runtime_imports(repo_root: Path) -> None:
    runtime_dir = repo_root / "src" / "jpintel_mcp" / "agent_runtime"
    for path in runtime_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            for module in imported:
                root = module.split(".")[0]
                full = module
                _assert(
                    root not in FORBIDDEN_AGENT_RUNTIME_IMPORTS
                    and full not in FORBIDDEN_AGENT_RUNTIME_IMPORTS,
                    f"forbidden import in {path}: {module}",
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()

    _validate_static_artifacts(repo_root)
    _validate_private_fact_capsule_schema(repo_root)
    _validate_agent_runtime_imports(repo_root)
    print("agent runtime contracts: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
