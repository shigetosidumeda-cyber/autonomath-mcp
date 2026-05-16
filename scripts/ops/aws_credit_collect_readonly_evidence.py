#!/usr/bin/env python3
"""Normalize captured read-only AWS evidence for the credit preflight.

This helper never executes AWS commands. By default it prints the imported
read-only command plan operators can run and capture outside this process.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from jpintel_mcp.agent_runtime.aws_credit_simulation import (
    ALLOWED_DATA_CLASS_VALUES,
    AWS_PROFILE,
    GATE_READY,
    READ_ONLY_COMMAND_PLAN,
    REQUIRED_TAG_KEYS,
    build_preflight_simulation,
    exposure_inputs_from_mapping,
)

MUTATING_AWS_CLI_VERBS = frozenset(
    {
        "accept",
        "add",
        "apply",
        "associate",
        "attach",
        "cancel",
        "copy",
        "create",
        "delete",
        "detach",
        "disable",
        "disassociate",
        "enable",
        "execute",
        "import",
        "invoke",
        "modify",
        "provision",
        "put",
        "reboot",
        "register",
        "remove",
        "restore",
        "run",
        "send",
        "set",
        "start",
        "stop",
        "submit",
        "terminate",
        "update",
    }
)


class EvidenceError(ValueError):
    """Raised when a supplied evidence file is missing required structure."""


def readonly_command_plan() -> list[dict[str, Any]]:
    """Return a JSON-serializable copy of the imported read-only plan."""

    plan: list[dict[str, Any]] = []
    for command in READ_ONLY_COMMAND_PLAN:
        argv = tuple(command.get("argv", ()))
        plan.append(
            {
                "id": str(command.get("id", "")),
                "argv": list(argv),
                "shell": shlex.join(argv),
                "mutates_aws": command.get("mutates_aws"),
            }
        )
    return plan


def assert_readonly_command_plan(plan: Sequence[Mapping[str, Any]] | None = None) -> None:
    """Fail if the imported AWS command plan contains a known mutating action."""

    commands = plan or readonly_command_plan()
    for command in commands:
        if command.get("mutates_aws") is not False:
            raise EvidenceError(f"command is not explicitly marked read-only: {command.get('id')}")

        argv = command.get("argv", ())
        if not isinstance(argv, Sequence) or isinstance(argv, str):
            raise EvidenceError(f"command argv must be a sequence: {command.get('id')}")
        if not argv or argv[0] != "aws":
            raise EvidenceError(f"command must invoke aws CLI: {command.get('id')}")

        mutating_tokens = MUTATING_AWS_CLI_VERBS.intersection(str(part) for part in argv)
        if mutating_tokens:
            joined = ", ".join(sorted(mutating_tokens))
            raise EvidenceError(f"command contains mutating AWS verb(s): {joined}")


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvidenceError(f"{path} must contain a JSON object")
    return payload


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def parse_sts_get_caller_identity(payload: Mapping[str, Any]) -> dict[str, str]:
    """Parse captured `aws sts get-caller-identity` JSON."""

    account = _string(payload.get("Account") or payload.get("account_id"))
    arn = _string(payload.get("Arn") or payload.get("arn"))
    user_id = _string(payload.get("UserId") or payload.get("user_id"))
    if not account:
        raise EvidenceError("STS evidence is missing Account")
    return {"Account": account, "Arn": arn, "UserId": user_id}


def parse_describe_budgets(
    payload: Mapping[str, Any],
    *,
    alerts_confirmed: bool = False,
    actions_reviewed: bool = False,
) -> dict[str, Any]:
    """Parse captured `aws budgets describe-budgets` JSON.

    Alert/action booleans are not derivable from this inventory alone and stay
    false unless an operator assertion file explicitly confirms them.
    """

    budgets = payload.get("Budgets")
    if not isinstance(budgets, list):
        raise EvidenceError("Budgets evidence is missing Budgets[]")

    normalized: list[dict[str, str]] = []
    for budget in budgets:
        if not isinstance(budget, Mapping):
            continue
        name = _string(budget.get("BudgetName") or budget.get("name"))
        if name:
            normalized.append({"name": name})

    return {
        "alerts_confirmed": alerts_confirmed,
        "actions_reviewed": actions_reviewed,
        "budgets": normalized,
    }


def parse_resourcegroupstaggingapi_get_resources(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Parse captured `resourcegroupstaggingapi get-resources` JSON."""

    resource_mappings = payload.get("ResourceTagMappingList")
    if not isinstance(resource_mappings, list):
        raise EvidenceError("Tagging evidence is missing ResourceTagMappingList[]")

    resources: list[dict[str, Any]] = []
    observed_tag_keys: set[str] = set()
    missing_required_by_resource: dict[str, list[str]] = {}
    unexpected_data_class_values: dict[str, str] = {}

    for index, resource in enumerate(resource_mappings):
        if not isinstance(resource, Mapping):
            continue
        arn = _string(resource.get("ResourceARN")) or f"resource[{index}]"
        tag_items = resource.get("Tags", [])
        if not isinstance(tag_items, list):
            tag_items = []

        tags: dict[str, str] = {}
        for tag in tag_items:
            if not isinstance(tag, Mapping):
                continue
            key = _string(tag.get("Key"))
            if not key:
                continue
            value = _string(tag.get("Value"))
            tags[key] = value
            observed_tag_keys.add(key)

        missing_required = [key for key in REQUIRED_TAG_KEYS if key not in tags]
        if missing_required:
            missing_required_by_resource[arn] = missing_required

        data_class = tags.get("DataClass")
        if data_class and data_class not in ALLOWED_DATA_CLASS_VALUES:
            unexpected_data_class_values[arn] = data_class

        resources.append({"arn": arn, "tags": tags})

    return {
        "resources": resources,
        "observed_tag_keys": sorted(observed_tag_keys),
        "missing_required_tag_keys_by_resource": missing_required_by_resource,
        "unexpected_data_class_values": unexpected_data_class_values,
    }


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def build_evidence_payload(
    *,
    sts_json: Path | None = None,
    budgets_json: Path | None = None,
    tagging_json: Path | None = None,
    configured_region_file: Path | None = None,
    operator_evidence_json: Path | None = None,
) -> dict[str, Any]:
    """Build a preflight-compatible evidence object from supplied files."""

    supplied_paths = (
        sts_json,
        budgets_json,
        tagging_json,
        configured_region_file,
        operator_evidence_json,
    )
    evidence: dict[str, Any] = {
        "evidence_complete": False,
        "evidence_files_supplied": any(path is not None for path in supplied_paths),
        "live_aws_commands_executed_by_helper": False,
    }

    if sts_json is not None:
        evidence["caller_identity"] = parse_sts_get_caller_identity(_load_json_object(sts_json))

    if configured_region_file is not None:
        region = configured_region_file.read_text(encoding="utf-8").strip()
        if not region:
            raise EvidenceError("configured region evidence is empty")
        evidence["aws_config"] = {"profile": AWS_PROFILE, "region": region}

    if budgets_json is not None:
        evidence["budget_guard"] = parse_describe_budgets(_load_json_object(budgets_json))

    if tagging_json is not None:
        evidence["tagging_inventory"] = parse_resourcegroupstaggingapi_get_resources(
            _load_json_object(tagging_json)
        )

    if operator_evidence_json is not None:
        operator_evidence = _load_json_object(operator_evidence_json)
        evidence = _deep_merge(evidence, operator_evidence)

    required_top_level_keys = (
        "caller_identity",
        "aws_config",
        "budget_guard",
        "tagging_policy",
        "canary_conditions",
        "exposure_inputs",
    )
    evidence["evidence_complete"] = all(key in evidence for key in required_top_level_keys)
    return evidence


def build_preflight_report_from_files(
    *,
    sts_json: Path | None = None,
    budgets_json: Path | None = None,
    tagging_json: Path | None = None,
    configured_region_file: Path | None = None,
    operator_evidence_json: Path | None = None,
) -> dict[str, Any]:
    evidence = build_evidence_payload(
        sts_json=sts_json,
        budgets_json=budgets_json,
        tagging_json=tagging_json,
        configured_region_file=configured_region_file,
        operator_evidence_json=operator_evidence_json,
    )
    canary_conditions = evidence.get("canary_conditions")
    if not isinstance(canary_conditions, Mapping):
        canary_conditions = {}

    report = build_preflight_simulation(
        canary_conditions=canary_conditions,
        exposure_inputs=exposure_inputs_from_mapping(evidence),
        inspection_evidence=evidence,
    )
    return {
        "evidence": evidence,
        "preflight": report,
        "read_only_command_plan": readonly_command_plan(),
    }


def _print_json(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _print_text_plan() -> None:
    assert_readonly_command_plan()
    print("Read-only AWS evidence command plan:")
    for command in readonly_command_plan():
        print(f"- {command['id']}: {command['shell']}")
    print("This helper does not execute AWS commands; capture outputs and pass files back in.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print or normalize read-only AWS evidence for the credit preflight."
    )
    parser.add_argument(
        "--dry-run-json",
        action="store_true",
        help="Print the imported read-only command plan as JSON and exit.",
    )
    parser.add_argument("--sts-json", type=Path, help="Captured STS get-caller-identity JSON.")
    parser.add_argument("--budgets-json", type=Path, help="Captured Budgets describe-budgets JSON.")
    parser.add_argument(
        "--tagging-json",
        type=Path,
        help="Captured resourcegroupstaggingapi get-resources JSON.",
    )
    parser.add_argument(
        "--configured-region-file",
        type=Path,
        help="Captured output from aws configure get region.",
    )
    parser.add_argument(
        "--operator-evidence-json",
        type=Path,
        help="Operator assertions for non-inferable canary, tagging, and teardown evidence.",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Always exit 0 after printing evidence/preflight JSON.",
    )
    args = parser.parse_args(argv)

    evidence_args = {
        "sts_json": args.sts_json,
        "budgets_json": args.budgets_json,
        "tagging_json": args.tagging_json,
        "configured_region_file": args.configured_region_file,
        "operator_evidence_json": args.operator_evidence_json,
    }
    has_evidence_files = any(value is not None for value in evidence_args.values())

    if args.dry_run_json:
        assert_readonly_command_plan()
        _print_json(
            {
                "live_aws_commands_executed_by_helper": False,
                "read_only_command_plan": readonly_command_plan(),
            }
        )
        return 0

    if not has_evidence_files:
        _print_text_plan()
        return 0

    assert_readonly_command_plan()
    payload = build_preflight_report_from_files(**evidence_args)
    _print_json(payload)
    if args.warn_only:
        return 0
    return 0 if payload["preflight"]["gate_state"] == GATE_READY else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
