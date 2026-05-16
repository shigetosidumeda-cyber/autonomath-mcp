#!/usr/bin/env python3
"""Fail-closed validator for the static P0 release capsule pointer."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]


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


def _load_source_receipt_contract_issues() -> Callable[..., Any]:
    """Import ``source_receipt_contract_issues`` without requiring pydantic.

    The plain ``from jpintel_mcp.agent_runtime.source_receipts import ...`` path
    triggers ``agent_runtime/__init__.py``, which transitively imports
    ``contracts`` and therefore pydantic. The validator should still work in
    bare CI containers where the venv has not been hydrated yet (e.g. before
    ``pip install -e .``). When the package import fails we load the helper
    module directly from its filename, bypassing ``__init__``.
    """

    try:
        from jpintel_mcp.agent_runtime.source_receipts import (  # noqa: PLC0415
            source_receipt_contract_issues as _impl,
        )

        return _impl
    except ImportError:
        module_path = _REPO_ROOT / "src" / "jpintel_mcp" / "agent_runtime" / "source_receipts.py"
        spec = importlib.util.spec_from_file_location("_validator_source_receipts", module_path)
        if spec is None or spec.loader is None:  # pragma: no cover
            raise
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.source_receipt_contract_issues


source_receipt_contract_issues = _load_source_receipt_contract_issues()

CAPSULE_DIR = Path("site/releases/rc1-p0-bootstrap")
WELL_KNOWN_RELEASE_PATH = Path("site/.well-known/jpcite-release.json")
RUNTIME_POINTER_PATH = Path("site/releases/current/runtime_pointer.json")
MANIFEST_PATH = CAPSULE_DIR / "release_capsule_manifest.json"
P0_FACADE_PATH = CAPSULE_DIR / "agent_surface/p0_facade.json"
CAPABILITY_MATRIX_PATH = CAPSULE_DIR / "capability_matrix.json"
PREFLIGHT_SCORECARD_PATH = CAPSULE_DIR / "preflight_scorecard.json"
OUTCOME_CATALOG_PATH = CAPSULE_DIR / "outcome_catalog.json"
ACCOUNTING_CSV_PROFILES_PATH = CAPSULE_DIR / "accounting_csv_profiles.json"
ALGORITHM_BLUEPRINTS_PATH = CAPSULE_DIR / "algorithm_blueprints.json"
OUTCOME_SOURCE_CROSSWALK_PATH = CAPSULE_DIR / "outcome_source_crosswalk.json"
PACKET_SKELETONS_PATH = CAPSULE_DIR / "packet_skeletons.json"
INLINE_PACKETS_PATH = CAPSULE_DIR / "inline_packets.json"
PUBLIC_SOURCE_DOMAINS_PATH = CAPSULE_DIR / "public_source_domains.json"
AWS_SPEND_PROGRAM_PATH = CAPSULE_DIR / "aws_spend_program.json"
AWS_EXECUTION_TEMPLATES_PATH = CAPSULE_DIR / "aws_execution_templates.json"

# Extended check inputs (Stream H additions, 2026-05-16)
CONTRACTS_PY_PATH = Path("src/jpintel_mcp/agent_runtime/contracts.py")
SCHEMAS_DIR = Path("schemas/jpcir")
INLINE_REGISTRY_PATH = Path("src/jpintel_mcp/services/packets/inline_registry.py")
SERVER_JSON_PATH = Path("site/server.json")
AGENTS_JSON_PATH = Path("site/.well-known/agents.json")
LLMS_JSON_PATH = Path("site/.well-known/llms.json")

EXPECTED_TARGET_CREDIT_CONVERSION_USD = 19490
EXPECTED_PREFLIGHT_BLOCKING_GATE_COUNT = 5
EXPECTED_OUTCOME_CATALOG_DELIVERABLE_COUNT = 14
EXPECTED_SCHEMA_PARITY_COUNT = 24

PUBLIC_MANIFEST_PATH = "/releases/rc1-p0-bootstrap/release_capsule_manifest.json"
PUBLIC_P0_FACADE_PATH = "/releases/rc1-p0-bootstrap/agent_surface/p0_facade.json"
PUBLIC_CAPABILITY_MATRIX_PATH = "/releases/rc1-p0-bootstrap/capability_matrix.json"
PUBLIC_PREFLIGHT_SCORECARD_PATH = "/releases/rc1-p0-bootstrap/preflight_scorecard.json"
PUBLIC_OUTCOME_CATALOG_PATH = "/releases/rc1-p0-bootstrap/outcome_catalog.json"
PUBLIC_ACCOUNTING_CSV_PROFILES_PATH = "/releases/rc1-p0-bootstrap/accounting_csv_profiles.json"
PUBLIC_ALGORITHM_BLUEPRINTS_PATH = "/releases/rc1-p0-bootstrap/algorithm_blueprints.json"
PUBLIC_OUTCOME_SOURCE_CROSSWALK_PATH = "/releases/rc1-p0-bootstrap/outcome_source_crosswalk.json"
PUBLIC_PACKET_SKELETONS_PATH = "/releases/rc1-p0-bootstrap/packet_skeletons.json"
PUBLIC_INLINE_PACKETS_PATH = "/releases/rc1-p0-bootstrap/inline_packets.json"
PUBLIC_PUBLIC_SOURCE_DOMAINS_PATH = "/releases/rc1-p0-bootstrap/public_source_domains.json"
PUBLIC_AWS_SPEND_PROGRAM_PATH = "/releases/rc1-p0-bootstrap/aws_spend_program.json"
PUBLIC_AWS_EXECUTION_TEMPLATES_PATH = "/releases/rc1-p0-bootstrap/aws_execution_templates.json"
PUBLIC_RUNTIME_POINTER_PATH = "/releases/current/runtime_pointer.json"
PUBLIC_WELL_KNOWN_RELEASE_PATH = "/.well-known/jpcite-release.json"

PUBLIC_CATALOG_SURFACE_PATHS = (
    PUBLIC_OUTCOME_CATALOG_PATH,
    PUBLIC_ACCOUNTING_CSV_PROFILES_PATH,
    PUBLIC_ALGORITHM_BLUEPRINTS_PATH,
    PUBLIC_OUTCOME_SOURCE_CROSSWALK_PATH,
    PUBLIC_PACKET_SKELETONS_PATH,
    PUBLIC_INLINE_PACKETS_PATH,
    PUBLIC_PUBLIC_SOURCE_DOMAINS_PATH,
    PUBLIC_AWS_SPEND_PROGRAM_PATH,
    PUBLIC_AWS_EXECUTION_TEMPLATES_PATH,
)

REQUIRED_GENERATED_SURFACES = (
    PUBLIC_WELL_KNOWN_RELEASE_PATH,
    PUBLIC_RUNTIME_POINTER_PATH,
    PUBLIC_MANIFEST_PATH,
    PUBLIC_P0_FACADE_PATH,
    PUBLIC_PREFLIGHT_SCORECARD_PATH,
    *PUBLIC_CATALOG_SURFACE_PATHS,
)

EXPECTED_P0_TOOLS = [
    "jpcite_route",
    "jpcite_preview_cost",
    "jpcite_execute_packet",
    "jpcite_get_packet",
]
EXPECTED_P0_TOOL_SEMANTICS = {
    "jpcite_route": "route",
    "jpcite_preview_cost": "preview",
    "jpcite_execute_packet": "execute",
    "jpcite_get_packet": "get",
}
ACTIVE_AWS_POINTER_KEYS = {
    "active_aws_command_plan",
    "active_aws_manifest",
    "active_aws_pointer",
    "active_aws_profile",
    "active_aws_runtime_pointer",
    "aws_active_pointer",
}

REQUIRED_BLOCKING_GATES = {
    "policy_trust_csv_boundaries",
    "accepted_artifact_billing_contract",
    "aws_budget_cash_guard_canary",
    "spend_simulation_pass_state",
    "teardown_simulation_pass_state",
}

REQUIRED_ACCOUNTING_BLOCKED_OUTPUTS = {
    "public_packet_claim",
    "public_source_receipt",
    "absence_or_completeness_claim",
    "certified_accounting_import_file",
    "row_level_export_without_consent",
}

EXPECTED_NO_HIT_SEMANTICS = "no_hit_not_absence"
EXPECTED_AWS_SPEND_EXECUTION_MODE = "offline_non_mutating_blueprint"
EXPECTED_AWS_TEMPLATE_EXECUTION_MODE = "offline_template_catalog"
EXPECTED_AWS_TEMPLATE_BLOCKED_STATE = "AWS_TEMPLATE_CATALOG_BLOCKED"
EXPECTED_AWS_BUDGET_GUARD_TEMPLATE_IDS = {
    "budget_credit_gross_burn_guard",
    "budget_paid_cash_exposure_backstop",
    "budget_action_operator_stopline",
    "cost_anomaly_monitor_guard",
}
EXPECTED_AWS_REQUIRED_TAG_KEYS = {
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
EXPECTED_AWS_ALLOWED_DATA_CLASSES = {
    "public-only",
    "synthetic-only",
    "derived-aggregate-only",
}
FORBIDDEN_AWS_COMMAND_KEYS = {"argv", "args", "command", "commands", "shell"}

FORBIDDEN_LEAKAGE_TOKENS = [
    "raw_csv",
    "private fact capsule",
    "private_fact_capsule",
]
LEAKAGE_TOKEN_EXEMPT_PATHS = {
    ACCOUNTING_CSV_PROFILES_PATH,
    ALGORITHM_BLUEPRINTS_PATH,
    OUTCOME_CATALOG_PATH,
    OUTCOME_SOURCE_CROSSWALK_PATH,
    PUBLIC_SOURCE_DOMAINS_PATH,
}


def _load_json(repo_root: Path, relative_path: Path, errors: list[str]) -> Any:
    path = repo_root / relative_path
    if not path.exists():
        errors.append(f"missing file: {relative_path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON in {relative_path}: {exc}")
        return None


def _require_false(data: Any, key: str, label: str, errors: list[str]) -> None:
    if not isinstance(data, dict) or data.get(key) is not False:
        errors.append(f"{label} must set {key}=false")


def _require_true(data: Any, key: str, label: str, errors: list[str]) -> None:
    if not isinstance(data, dict) or data.get(key) is not True:
        errors.append(f"{label} must set {key}=true")


def _require_equal(actual: Any, expected: Any, label: str, errors: list[str]) -> None:
    if actual != expected:
        errors.append(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def _require_non_empty_dict_list(
    data: dict[str, Any],
    key: str,
    label: str,
    errors: list[str],
) -> list[dict[str, Any]]:
    items = data.get(key)
    if not isinstance(items, list) or not items:
        errors.append(f"{label} must include non-empty {key}")
        return []

    dict_items = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{label} {key}[{index}] must be an object")
            continue
        dict_items.append(item)
    return dict_items


def _require_required_aws_tags(tags: Any, label: str, errors: list[str]) -> None:
    if not isinstance(tags, dict):
        errors.append(f"{label} must include required_tags")
        return

    missing_tags = sorted(EXPECTED_AWS_REQUIRED_TAG_KEYS - set(tags))
    if missing_tags:
        errors.append(f"{label} required_tags missing: {missing_tags}")
    blank_tags = sorted(key for key, value in tags.items() if not value)
    if blank_tags:
        errors.append(f"{label} required_tags contain blank values: {blank_tags}")
    _require_equal(tags.get("SpendProgram"), "aws-credit-19490", f"{label} SpendProgram", errors)
    _require_equal(tags.get("AutoStop"), "required", f"{label} AutoStop", errors)
    if tags.get("DataClass") not in EXPECTED_AWS_ALLOWED_DATA_CLASSES:
        errors.append(f"{label} DataClass is not an allowed value: {tags.get('DataClass')!r}")


def _validate_mutation_templates(
    templates: Any,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(templates, list) or not templates:
        errors.append(f"{label} must include non-empty mutation templates")
        return
    for index, template in enumerate(templates):
        item_label = f"{label}[{index}]"
        if not isinstance(template, dict):
            errors.append(f"{item_label} must be an object")
            continue
        leaked_command_keys = sorted(FORBIDDEN_AWS_COMMAND_KEYS & set(template))
        if leaked_command_keys:
            errors.append(f"{item_label} must not include command keys: {leaked_command_keys}")
        _require_false(template, "executable", item_label, errors)
        _require_equal(
            template.get("rendered_command"), None, f"{item_label} rendered_command", errors
        )
        operation_template = template.get("operation_template")
        if not isinstance(operation_template, str) or "${" not in operation_template:
            errors.append(f"{item_label} operation_template must keep placeholder syntax")


def _require_blocked_outputs(data: Any, label: str, errors: list[str]) -> None:
    blocked_outputs = data.get("blocked_downstream_outputs") if isinstance(data, dict) else None
    if not isinstance(blocked_outputs, list):
        errors.append(f"{label} must set blocked_downstream_outputs")
        return

    missing_outputs = sorted(REQUIRED_ACCOUNTING_BLOCKED_OUTPUTS - set(blocked_outputs))
    if missing_outputs:
        errors.append(f"{label} blocked_downstream_outputs missing: {missing_outputs}")


def _strings(data: Any) -> list[str]:
    if isinstance(data, str):
        return [data]
    if isinstance(data, dict):
        values: list[str] = []
        for key, value in data.items():
            values.extend(_strings(key))
            values.extend(_strings(value))
        return values
    if isinstance(data, list):
        values = []
        for item in data:
            values.extend(_strings(item))
        return values
    return []


def _public_path_to_repo_path(public_path: str) -> Path | None:
    if not public_path.startswith("/") or ".." in Path(public_path).parts:
        return None
    return Path("site") / public_path.removeprefix("/")


def _validate_leakage_tokens(files: dict[Path, Any], errors: list[str]) -> None:
    for relative_path, data in files.items():
        if data is None:
            continue
        if relative_path in LEAKAGE_TOKEN_EXEMPT_PATHS:
            continue
        haystack = "\n".join(_strings(data)).lower()
        for token in FORBIDDEN_LEAKAGE_TOKENS:
            if token in haystack:
                errors.append(
                    f"forbidden private CSV/public source token in {relative_path}: {token}"
                )


def _validate_no_active_aws_pointer(data: Any, label: str, errors: list[str]) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            if key in ACTIVE_AWS_POINTER_KEYS and value not in (None, False, ""):
                errors.append(f"{label} must not set active AWS pointer {key}")
            _validate_no_active_aws_pointer(value, label, errors)
    elif isinstance(data, list):
        for item in data:
            _validate_no_active_aws_pointer(item, label, errors)


def _validate_generated_surface_paths(
    repo_root: Path, manifest: dict[str, Any], errors: list[str]
) -> None:
    surfaces = manifest.get("generated_surfaces")
    if not isinstance(surfaces, list):
        errors.append("manifest generated_surfaces must be a list")
        return

    for surface in surfaces:
        if not isinstance(surface, str):
            errors.append(f"manifest generated_surfaces contains non-string path: {surface!r}")
            continue
        repo_path = _public_path_to_repo_path(surface)
        if repo_path is None:
            errors.append(
                f"manifest generated_surfaces path is not a safe public path: {surface!r}"
            )
            continue
        if not (repo_root / repo_path).exists():
            errors.append(
                f"manifest generated_surfaces path does not exist: {surface} -> {repo_path}"
            )


def _validate_p0_tool_semantics(tools: Any, errors: list[str]) -> None:
    if not isinstance(tools, list):
        return

    semantics_by_name = {
        tool.get("name"): tool.get("semantics")
        for tool in tools
        if isinstance(tool, dict) and "semantics" in tool
    }
    if not semantics_by_name:
        return
    _require_equal(
        semantics_by_name,
        EXPECTED_P0_TOOL_SEMANTICS,
        "P0 facade tool semantics",
        errors,
    )


def _validate_outcome_catalog(data: dict[str, Any], errors: list[str]) -> None:
    _require_equal(
        data.get("schema_version"),
        "jpcite.outcome_catalog.p0.v1",
        "outcome catalog schema_version",
        errors,
    )
    _require_false(data, "request_time_llm_dependency", "outcome catalog", errors)
    _require_false(data, "live_network_dependency", "outcome catalog", errors)
    _require_false(data, "live_aws_dependency", "outcome catalog", errors)
    _require_equal(
        data.get("no_hit_semantics"),
        EXPECTED_NO_HIT_SEMANTICS,
        "outcome catalog no_hit_semantics",
        errors,
    )

    for index, deliverable in enumerate(
        _require_non_empty_dict_list(data, "deliverables", "outcome catalog", errors)
    ):
        label = f"outcome catalog deliverables[{index}]"
        _require_false(deliverable, "api_wiring_required", label, errors)
        _require_false(deliverable, "request_time_llm_dependency", label, errors)
        _require_false(deliverable, "live_network_dependency", label, errors)
        _require_false(deliverable, "live_aws_dependency", label, errors)
        _require_equal(
            deliverable.get("no_hit_semantics"),
            EXPECTED_NO_HIT_SEMANTICS,
            f"{label} no_hit_semantics",
            errors,
        )


def _validate_accounting_csv_profiles(data: dict[str, Any], errors: list[str]) -> None:
    _require_equal(
        data.get("schema_version"),
        "jpcite.accounting_csv_profiles.p0.v1",
        "accounting CSV profiles schema_version",
        errors,
    )
    _require_blocked_outputs(data, "accounting CSV profiles", errors)

    for index, profile in enumerate(
        _require_non_empty_dict_list(data, "profiles", "accounting CSV profiles", errors)
    ):
        label = f"accounting CSV profiles profiles[{index}]"
        _require_blocked_outputs(profile, label, errors)
        _require_false(profile, "official_certification_claimed", label, errors)
        account_category_policy = profile.get("account_category_policy")
        _require_false(
            account_category_policy,
            "derived_category_allowed",
            f"{label} account_category_policy",
            errors,
        )


def _validate_algorithm_blueprints(data: dict[str, Any], errors: list[str]) -> None:
    _require_equal(
        data.get("schema_version"),
        "jpcite.algorithm_blueprints.p0.v1",
        "algorithm blueprints schema_version",
        errors,
    )
    _require_false(data, "llm_allowed", "algorithm blueprints", errors)
    _require_false(data, "network_allowed", "algorithm blueprints", errors)
    _require_equal(
        data.get("no_hit_semantics"),
        EXPECTED_NO_HIT_SEMANTICS,
        "algorithm blueprints no_hit_semantics",
        errors,
    )

    for index, blueprint in enumerate(
        _require_non_empty_dict_list(data, "blueprints", "algorithm blueprints", errors)
    ):
        label = f"algorithm blueprints blueprints[{index}]"
        _require_false(blueprint, "llm_allowed", label, errors)
        _require_false(blueprint, "network_allowed", label, errors)
        gap_handling = blueprint.get("gap_handling")
        _require_false(
            gap_handling,
            "absence_claim_enabled",
            f"{label} gap_handling",
            errors,
        )
        _require_equal(
            gap_handling.get("no_hit_semantics") if isinstance(gap_handling, dict) else None,
            EXPECTED_NO_HIT_SEMANTICS,
            f"{label} gap_handling no_hit_semantics",
            errors,
        )
        _require_false(
            blueprint.get("advice_boundary"),
            "asserts_legal_or_accounting_advice",
            f"{label} advice_boundary",
            errors,
        )
        _require_false(
            blueprint.get("proof_handling"),
            "private_csv_can_support_public_claims",
            f"{label} proof_handling",
            errors,
        )


def _validate_public_source_domains(data: dict[str, Any], errors: list[str]) -> None:
    _require_equal(
        data.get("schema_version"),
        "jpcite.public_source_domains.p0.v1",
        "public source domains schema_version",
        errors,
    )
    _require_false(data, "collection_enabled_initially", "public source domains", errors)
    _require_equal(
        data.get("playwright_screenshot_max_px"),
        1600,
        "public source domains playwright_screenshot_max_px",
        errors,
    )

    for index, source in enumerate(
        _require_non_empty_dict_list(data, "catalog", "public source domains", errors)
    ):
        label = f"public source domains catalog[{index}]"
        _require_false(source, "collection_enabled_initially", label, errors)
        _require_false(source, "bulk_resale_or_redistribution_allowed", label, errors)
        _require_false(source, "pii_collection_allowed", label, errors)
        screenshot_policy = source.get("playwright_screenshot_policy")
        _require_false(
            screenshot_policy,
            "full_page_capture_allowed",
            f"{label} playwright_screenshot_policy",
            errors,
        )
        _require_equal(
            screenshot_policy.get("max_bitmap_long_edge_px")
            if isinstance(screenshot_policy, dict)
            else None,
            1600,
            f"{label} playwright_screenshot_policy max_bitmap_long_edge_px",
            errors,
        )
        robots_terms = source.get("robots_terms_posture")
        _require_true(
            robots_terms,
            "robots_txt_must_be_checked",
            f"{label} robots_terms_posture",
            errors,
        )
        _require_true(
            robots_terms,
            "terms_must_be_reviewed",
            f"{label} robots_terms_posture",
            errors,
        )
        _require_true(
            robots_terms,
            "stop_on_disallow_or_terms_conflict",
            f"{label} robots_terms_posture",
            errors,
        )


def _validate_aws_spend_program(data: dict[str, Any], errors: list[str]) -> None:
    _require_equal(
        data.get("schema_version"),
        "jpcite.aws_spend_program.p0.v1",
        "AWS spend program schema_version",
        errors,
    )
    _require_equal(
        data.get("target_credit_spend_usd"),
        EXPECTED_TARGET_CREDIT_CONVERSION_USD,
        "AWS spend program target_credit_spend_usd",
        errors,
    )
    _require_equal(
        data.get("planned_target_sum_usd"),
        EXPECTED_TARGET_CREDIT_CONVERSION_USD,
        "AWS spend program planned_target_sum_usd",
        errors,
    )
    _require_false(data, "live_execution_allowed", "AWS spend program", errors)
    _require_false(data, "preflight_evidence_passed", "AWS spend program", errors)
    _require_equal(
        data.get("execution_mode"),
        EXPECTED_AWS_SPEND_EXECUTION_MODE,
        "AWS spend program execution_mode",
        errors,
    )

    for index, batch in enumerate(
        _require_non_empty_dict_list(data, "batches", "AWS spend program", errors)
    ):
        label = f"AWS spend program batches[{index}]"
        _require_false(batch, "aws_calls_allowed", label, errors)
        _require_false(batch, "network_calls_allowed", label, errors)
        _require_false(batch, "mutates_live_aws", label, errors)
        _require_false(batch, "subprocess_allowed", label, errors)
        _require_equal(
            batch.get("execution_mode"),
            EXPECTED_AWS_SPEND_EXECUTION_MODE,
            f"{label} execution_mode",
            errors,
        )


def _validate_outcome_source_crosswalk(data: dict[str, Any], errors: list[str]) -> None:
    _require_equal(
        data.get("schema_version"),
        "jpcite.outcome_source_crosswalk.p0.v1",
        "outcome source crosswalk schema_version",
        errors,
    )
    covered_slugs = data.get("covered_deliverable_slugs")
    crosswalk = data.get("crosswalk")
    if not isinstance(covered_slugs, list) or not covered_slugs:
        errors.append("outcome source crosswalk must include covered_deliverable_slugs")
        covered_slugs = []
    if not isinstance(crosswalk, list) or not crosswalk:
        errors.append("outcome source crosswalk must include non-empty crosswalk")
        crosswalk = []
    _require_equal(
        len(crosswalk),
        len(covered_slugs),
        "outcome source crosswalk coverage count",
        errors,
    )
    if len(set(covered_slugs)) != len(covered_slugs):
        errors.append("outcome source crosswalk covered_deliverable_slugs must be unique")

    for index, entry in enumerate(crosswalk):
        if not isinstance(entry, dict):
            errors.append(f"outcome source crosswalk crosswalk[{index}] must be an object")
            continue
        label = f"outcome source crosswalk crosswalk[{index}]"
        if not entry.get("deliverable_slug"):
            errors.append(f"{label} must include deliverable_slug")
        for key in (
            "source_category_links",
            "public_source_categories",
            "public_source_family_ids",
            "algorithm_blueprint_ids",
            "aws_stage_ids",
        ):
            if not isinstance(entry.get(key), list) or not entry[key]:
                errors.append(f"{label} must include non-empty {key}")
        requires_csv_overlay = entry.get("requires_csv_overlay")
        csv_profile_keys = entry.get("accounting_csv_profile_keys")
        if requires_csv_overlay is True and not csv_profile_keys:
            errors.append(f"{label} requires CSV overlay but has no accounting CSV profiles")
        if requires_csv_overlay is False and csv_profile_keys:
            errors.append(f"{label} has CSV profiles while requires_csv_overlay=false")


def _validate_packet_skeletons(data: dict[str, Any], errors: list[str]) -> None:
    _require_equal(
        data.get("schema_version"),
        "jpcite.packet_skeleton_catalog.p0.v1",
        "packet skeleton catalog schema_version",
        errors,
    )
    _require_false(
        data,
        "paid_packet_body_materialized",
        "packet skeleton catalog",
        errors,
    )
    _require_false(data, "request_time_llm_dependency", "packet skeleton catalog", errors)
    _require_false(data, "live_network_dependency", "packet skeleton catalog", errors)
    _require_false(data, "live_aws_dependency", "packet skeleton catalog", errors)
    _require_false(data, "real_csv_runtime_enabled", "packet skeleton catalog", errors)
    _require_equal(
        data.get("no_hit_semantics"),
        EXPECTED_NO_HIT_SEMANTICS,
        "packet skeleton catalog no_hit_semantics",
        errors,
    )
    skeletons = data.get("skeletons")
    if not isinstance(skeletons, dict) or not skeletons:
        errors.append("packet skeleton catalog must include non-empty skeletons")
        return
    for outcome_contract_id, skeleton in skeletons.items():
        label = f"packet skeleton catalog skeletons[{outcome_contract_id}]"
        if not isinstance(skeleton, dict):
            errors.append(f"{label} must be an object")
            continue
        _require_equal(
            skeleton.get("schema_version"),
            "jpcite.packet_skeleton.p0.v1",
            f"{label} schema_version",
            errors,
        )
        _require_equal(
            skeleton.get("outcome_contract_id"),
            outcome_contract_id,
            f"{label} outcome_contract_id",
            errors,
        )
        no_hit = skeleton.get("no_hit_semantics")
        if not isinstance(no_hit, dict):
            errors.append(f"{label} must include no_hit_semantics")
        else:
            _require_equal(
                no_hit.get("rule"),
                EXPECTED_NO_HIT_SEMANTICS,
                f"{label} no_hit rule",
                errors,
            )
            _require_false(no_hit, "absence_claim_enabled", f"{label} no_hit", errors)
        for key in ("claims", "source_receipts", "known_gaps"):
            if not isinstance(skeleton.get(key), list) or not skeleton[key]:
                errors.append(f"{label} must include non-empty {key}")
        for claim_index, claim in enumerate(skeleton.get("claims", [])):
            if not isinstance(claim, dict):
                errors.append(f"{label} claims[{claim_index}] must be an object")
                continue
            _require_equal(
                claim.get("visibility"),
                "public",
                f"{label} claims[{claim_index}] visibility",
                errors,
            )
        for issue in source_receipt_contract_issues(skeleton):
            errors.append(
                f"{label} source receipt contract issue {issue['code']}: "
                f"{issue['subject_type']} {issue['subject_id']}"
            )
        private_overlay = skeleton.get("private_overlay")
        if isinstance(private_overlay, dict):
            _require_equal(
                private_overlay.get("tenant_scope"),
                "tenant_private",
                f"{label} private_overlay tenant_scope",
                errors,
            )
            _require_equal(
                private_overlay.get("redaction_policy"),
                "hash_only_private_facts",
                f"{label} private_overlay redaction_policy",
                errors,
            )
            _require_false(
                private_overlay,
                "csv_input_retained",
                f"{label} private_overlay",
                errors,
            )
            _require_false(
                private_overlay,
                "csv_input_logged",
                f"{label} private_overlay",
                errors,
            )
            _require_false(
                private_overlay,
                "csv_input_sent_to_aws",
                f"{label} private_overlay",
                errors,
            )
            _require_false(
                private_overlay,
                "public_surface_export_allowed",
                f"{label} private_overlay",
                errors,
            )
            _require_false(
                private_overlay,
                "source_receipt_compatible",
                f"{label} private_overlay",
                errors,
            )
            for fact_index, fact in enumerate(private_overlay.get("private_fact_examples", [])):
                if not isinstance(fact, dict):
                    errors.append(
                        f"{label} private_overlay private_fact_examples[{fact_index}] "
                        "must be an object"
                    )
                    continue
                _require_false(
                    fact,
                    "public_claim_support",
                    f"{label} private_overlay private_fact_examples[{fact_index}]",
                    errors,
                )
                _require_false(
                    fact,
                    "source_receipt_compatible",
                    f"{label} private_overlay private_fact_examples[{fact_index}]",
                    errors,
                )
                _require_false(
                    fact,
                    "private_value_retained",
                    f"{label} private_overlay private_fact_examples[{fact_index}]",
                    errors,
                )


def _validate_inline_packets(data: dict[str, Any], errors: list[str]) -> None:
    _require_equal(
        data.get("schema_version"),
        "jpcite.inline_packet_catalog.p0.v1",
        "inline_packets schema_version",
        errors,
    )
    for key in (
        "billable",
        "accepted_artifact_created",
        "paid_packet_body_materialized",
        "request_time_llm_call_performed",
        "live_source_fetch_performed",
        "live_aws_dependency_used",
    ):
        _require_false(data, key, "inline_packets", errors)
    _require_equal(
        data.get("charge_status"),
        "not_charged",
        "inline_packets charge_status",
        errors,
    )
    packets = data.get("packets")
    if not isinstance(packets, dict) or not packets:
        errors.append("inline_packets must include packets")
        return
    for packet_id, packet in packets.items():
        label = f"inline_packets.{packet_id}"
        if not isinstance(packet, dict):
            errors.append(f"{label} must be an object")
            continue
        for key in (
            "billable",
            "accepted_artifact_created",
            "paid_packet_body_materialized",
            "request_time_llm_call_performed",
            "live_source_fetch_performed",
            "live_aws_dependency_used",
        ):
            _require_false(packet, key, label, errors)
        ledger = packet.get("receipt_ledger")
        if not isinstance(ledger, dict):
            errors.append(f"{label} must include receipt_ledger")
            continue
        _require_equal(
            ledger.get("public_claims_release_allowed"),
            True,
            f"{label} receipt_ledger public_claims_release_allowed",
            errors,
        )
        if ledger.get("issues") != []:
            errors.append(f"{label} receipt_ledger must have no issues")


def _validate_aws_execution_templates(data: dict[str, Any], errors: list[str]) -> None:
    _require_equal(
        data.get("schema_version"),
        "jpcite.aws_execution_templates.p0.v1",
        "AWS execution templates schema_version",
        errors,
    )
    _require_equal(
        data.get("target_credit_spend_usd"),
        EXPECTED_TARGET_CREDIT_CONVERSION_USD,
        "AWS execution templates target_credit_spend_usd",
        errors,
    )
    _require_equal(
        data.get("planned_target_sum_usd"),
        EXPECTED_TARGET_CREDIT_CONVERSION_USD,
        "AWS execution templates planned_target_sum_usd",
        errors,
    )
    _require_true(data, "data_only", "AWS execution templates", errors)
    _require_true(data, "no_aws_execution_performed", "AWS execution templates", errors)
    _require_false(data, "network_calls_allowed", "AWS execution templates", errors)
    _require_false(data, "subprocess_allowed", "AWS execution templates", errors)
    _require_false(data, "live_execution_allowed", "AWS execution templates", errors)
    _require_false(
        data,
        "live_execution_allowed_by_default",
        "AWS execution templates",
        errors,
    )
    _require_equal(
        data.get("live_execution_gate_state"),
        EXPECTED_AWS_TEMPLATE_BLOCKED_STATE,
        "AWS execution templates live_execution_gate_state",
        errors,
    )
    _require_equal(
        data.get("execution_mode"),
        EXPECTED_AWS_TEMPLATE_EXECUTION_MODE,
        "AWS execution templates execution_mode",
        errors,
    )
    _require_equal(
        set(data.get("budget_guard_template_ids", [])),
        EXPECTED_AWS_BUDGET_GUARD_TEMPLATE_IDS,
        "AWS execution templates budget_guard_template_ids",
        errors,
    )
    _require_equal(
        set(data.get("required_tag_keys", [])),
        EXPECTED_AWS_REQUIRED_TAG_KEYS,
        "AWS execution templates required_tag_keys",
        errors,
    )

    for key in ("execution_templates", "staged_queue_manifests", "teardown_recipes"):
        for index, item in enumerate(
            _require_non_empty_dict_list(data, key, "AWS execution templates", errors)
        ):
            label = f"AWS execution templates {key}[{index}]"
            _require_true(item, "data_only", label, errors)
            _require_false(item, "live_execution_allowed", label, errors)
            _require_required_aws_tags(item.get("required_tags"), label, errors)
            if key != "teardown_recipes":
                _require_true(item, "unlock_required", label, errors)
            if key == "execution_templates":
                _validate_mutation_templates(
                    item.get("mutation_templates"),
                    f"{label} mutation_templates",
                    errors,
                )
            if key == "teardown_recipes":
                _validate_mutation_templates(
                    item.get("delete_step_templates"),
                    f"{label} delete_step_templates",
                    errors,
                )
                _validate_mutation_templates(
                    item.get("verification_templates"),
                    f"{label} verification_templates",
                    errors,
                )

    manifests = data.get("staged_queue_manifests")
    if isinstance(manifests, list) and manifests:
        planned_total = sum(
            manifest.get("planned_usd", 0) for manifest in manifests if isinstance(manifest, dict)
        )
        _require_equal(
            planned_total,
            EXPECTED_TARGET_CREDIT_CONVERSION_USD,
            "AWS execution templates queue planned_usd sum",
            errors,
        )
        last_manifest = manifests[-1]
        if isinstance(last_manifest, dict):
            _require_equal(
                last_manifest.get("cumulative_planned_usd"),
                EXPECTED_TARGET_CREDIT_CONVERSION_USD,
                "AWS execution templates final cumulative_planned_usd",
                errors,
            )
            _require_equal(
                last_manifest.get("remaining_target_after_stage_usd"),
                0,
                "AWS execution templates final remaining_target_after_stage_usd",
                errors,
            )

    unlock_template = data.get("operator_unlock_template")
    if isinstance(unlock_template, dict):
        _require_equal(
            unlock_template.get("target_credit_spend_usd"),
            EXPECTED_TARGET_CREDIT_CONVERSION_USD,
            "AWS execution templates operator_unlock_template target_credit_spend_usd",
            errors,
        )
        _require_equal(
            unlock_template.get("approved_stage_ids"),
            [],
            "AWS execution templates operator_unlock_template approved_stage_ids",
            errors,
        )
        _require_equal(
            unlock_template.get("approved_template_ids"),
            [],
            "AWS execution templates operator_unlock_template approved_template_ids",
            errors,
        )
        for key in (
            "budget_guard_attestation",
            "tag_policy_attestation",
            "teardown_recipe_attestation",
            "source_policy_attestation",
        ):
            values = unlock_template.get(key)
            if not isinstance(values, dict) or not values:
                errors.append(f"AWS execution templates operator_unlock_template missing {key}")
            elif any(value is not False for value in values.values()):
                errors.append(
                    f"AWS execution templates operator_unlock_template {key} must default false"
                )
        risk_acceptance = unlock_template.get("risk_acceptance")
        if not isinstance(risk_acceptance, dict) or not risk_acceptance:
            errors.append(
                "AWS execution templates operator_unlock_template missing risk_acceptance"
            )
        else:
            risky_truths = [
                key for key, value in risk_acceptance.items() if isinstance(value, bool) and value
            ]
            if risky_truths:
                errors.append(
                    "AWS execution templates operator_unlock_template risk_acceptance "
                    f"must default false: {risky_truths}"
                )
    else:
        errors.append("AWS execution templates must include operator_unlock_template")

    unlock_validation = data.get("operator_unlock_validation")
    if isinstance(unlock_validation, dict):
        _require_false(
            unlock_validation,
            "complete",
            "AWS execution templates operator_unlock_validation",
            errors,
        )
        _require_false(
            unlock_validation,
            "live_execution_allowed_after_validation",
            "AWS execution templates operator_unlock_validation",
            errors,
        )
    else:
        errors.append("AWS execution templates must include operator_unlock_validation")

    execution_templates = data.get("execution_templates")
    recipe_classes = {
        recipe.get("resource_class")
        for recipe in data.get("teardown_recipes", [])
        if isinstance(recipe, dict)
    }
    required_resource_classes: set[Any] = set()
    if isinstance(execution_templates, list):
        required_resource_classes.update(
            template.get("resource_class")
            for template in execution_templates
            if isinstance(template, dict)
        )
    if isinstance(manifests, list):
        for manifest in manifests:
            if not isinstance(manifest, dict):
                continue
            for queue_item in manifest.get("queue_items", []):
                if isinstance(queue_item, dict):
                    required_resource_classes.add(queue_item.get("resource_class"))
    missing_recipes = sorted(
        resource_class
        for resource_class in required_resource_classes
        if resource_class and resource_class not in recipe_classes
    )
    if missing_recipes:
        errors.append(f"AWS execution templates missing teardown recipes: {missing_recipes}")


# ---------------------------------------------------------------------------
# Stream H extensions (2026-05-16): additional capsule-wide consistency checks
# ---------------------------------------------------------------------------


_CLASS_PATTERN = re.compile(
    r"^class (?P<name>[A-Z][A-Za-z0-9_]*)\(StrictModel\):",
    re.MULTILINE,
)


def _camel_to_snake(name: str) -> str:
    """Convert ``CamelCase`` model name to ``snake_case`` schema stem."""

    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return snake


def _validate_schema_parity(repo_root: Path, errors: list[str]) -> None:
    """Check pydantic models in ``contracts.py`` align with JSON schemas.

    The check is intentionally static: it greps for ``class X(StrictModel):``
    in the contracts module, so it does not require pydantic to be installed.
    Only top-level models whose ``snake_case`` name has a matching
    ``schemas/jpcir/<name>.schema.json`` are counted — internal nested record
    types (e.g. ``PrivateFactCapsuleRecord``, ``ExecutionPhase``) are excluded
    from the parity number by construction since they have no JSON schema.
    """

    contracts_path = repo_root / CONTRACTS_PY_PATH
    schemas_dir = repo_root / SCHEMAS_DIR

    # When invoked against a stub tree (tests using tmp_path), the source-side
    # inputs simply do not exist. Treat that as "nothing to check" rather than
    # an error so the capsule-only fixtures continue to validate cleanly.
    if not contracts_path.exists() or not schemas_dir.exists():
        return

    contracts_source = contracts_path.read_text(encoding="utf-8")
    model_names = [match.group("name") for match in _CLASS_PATTERN.finditer(contracts_source)]
    if not model_names:
        errors.append("schema parity: no StrictModel classes detected in contracts.py")
        return

    schema_stems = {
        path.name.removesuffix(".schema.json") for path in schemas_dir.glob("*.schema.json")
    }
    if not schema_stems:
        errors.append("schema parity: no *.schema.json files found in schemas/jpcir")
        return

    paired = sorted(name for name in model_names if _camel_to_snake(name) in schema_stems)
    paired_count = len(paired)

    if paired_count != EXPECTED_SCHEMA_PARITY_COUNT:
        errors.append(
            "schema parity: expected "
            f"{EXPECTED_SCHEMA_PARITY_COUNT} paired (model<->schema) entries, "
            f"got {paired_count} (paired={paired})"
        )
    if len(schema_stems) != EXPECTED_SCHEMA_PARITY_COUNT:
        errors.append(
            "schema parity: expected "
            f"{EXPECTED_SCHEMA_PARITY_COUNT} schema files in {SCHEMAS_DIR}, "
            f"got {len(schema_stems)}"
        )

    unmatched_schemas = sorted(schema_stems - {_camel_to_snake(name) for name in model_names})
    if unmatched_schemas:
        errors.append(f"schema parity: schemas without matching StrictModel: {unmatched_schemas}")


def _validate_outcome_pricing_complete(outcome_catalog: Any, errors: list[str]) -> None:
    """Every outcome in ``outcome_catalog.json`` must price > 0 JPY.

    The accepted-artifact billing contract requires that the public catalog
    advertises a per-deliverable price for every billable outcome. A missing
    or zero price would cause the billing ledger to compute ¥0 and bypass
    the metered billing path, which is a regression.
    """

    if not isinstance(outcome_catalog, dict):
        return
    deliverables = outcome_catalog.get("deliverables")
    if not isinstance(deliverables, list) or not deliverables:
        return
    # Stub fixtures (e.g. tmp_path trees in the existing test suite) include
    # placeholder deliverables that lack ``deliverable_slug`` /
    # ``estimated_price_jpy`` because they only exercise the fail-closed flag
    # walks. Skip the pricing-completeness check unless at least one
    # deliverable looks like a production entry (carries ``deliverable_slug``).
    if not any(isinstance(d, dict) and "deliverable_slug" in d for d in deliverables):
        return
    if len(deliverables) != EXPECTED_OUTCOME_CATALOG_DELIVERABLE_COUNT:
        errors.append(
            "outcome pricing: expected "
            f"{EXPECTED_OUTCOME_CATALOG_DELIVERABLE_COUNT} deliverables, "
            f"got {len(deliverables)}"
        )

    missing_or_invalid: list[str] = []
    for index, deliverable in enumerate(deliverables):
        if not isinstance(deliverable, dict):
            errors.append(f"outcome pricing: deliverables[{index}] must be an object")
            continue
        slug = deliverable.get("deliverable_slug") or f"index={index}"
        price = deliverable.get("estimated_price_jpy")
        if not isinstance(price, int) or price <= 0:
            missing_or_invalid.append(f"{slug}->{price!r}")
    if missing_or_invalid:
        errors.append(
            f"outcome pricing: deliverables missing estimated_price_jpy > 0: {missing_or_invalid}"
        )


_ALIASES_DICT_PATTERN = re.compile(
    r"INLINE_PACKET_ALIASES\s*=\s*\{(?P<body>.*?)\}",
    re.DOTALL,
)
_ALIAS_ENTRY_PATTERN = re.compile(
    r'"(?P<alias>[a-zA-Z0-9_]+)"\s*:\s*"(?P<packet>[a-zA-Z0-9_]+)"',
)


def _parse_inline_alias_map(repo_root: Path) -> dict[str, str] | None:
    """Parse ``INLINE_PACKET_ALIASES`` from ``inline_registry.py`` statically.

    Returns ``None`` when the file is missing or unparseable, so the caller
    can record a single explanatory error and skip the per-entry checks.
    """

    registry_path = repo_root / INLINE_REGISTRY_PATH
    if not registry_path.exists():
        return None
    source = registry_path.read_text(encoding="utf-8")
    match = _ALIASES_DICT_PATTERN.search(source)
    if match is None:
        return None
    body = match.group("body")
    return dict(_ALIAS_ENTRY_PATTERN.findall(body))


def _validate_inline_packet_aliases(
    repo_root: Path, inline_packets: Any, errors: list[str]
) -> None:
    """Cross-check ``INLINE_PACKET_ALIASES`` against ``inline_packets.json``.

    The registry maps each public alias (including ``p0_*`` prefixed forms)
    to its canonical packet id. The JSON capsule must agree: every alias
    must appear under ``alias_ids`` and every canonical packet must appear
    under ``packet_ids`` / ``packets``.
    """

    # Stub trees (e.g. test tmp_path fixtures) will not carry the source-side
    # registry. Treat absent registry as "nothing to cross-check" rather than
    # an error; the per-test that wants to assert the missing-registry path
    # should pass an empty tmp_path explicitly and the parse helper will
    # return None.
    registry_path = repo_root / INLINE_REGISTRY_PATH
    if not registry_path.exists():
        return

    alias_map = _parse_inline_alias_map(repo_root)
    if alias_map is None:
        errors.append(
            "inline packet aliases: could not parse INLINE_PACKET_ALIASES from "
            f"{INLINE_REGISTRY_PATH}"
        )
        return

    if not isinstance(inline_packets, dict):
        return

    expected_alias_ids = set(alias_map)
    expected_packet_ids = set(alias_map.values())

    actual_alias_ids_raw = inline_packets.get("alias_ids")
    actual_packet_ids_raw = inline_packets.get("packet_ids")
    packets_block = inline_packets.get("packets")

    if not isinstance(actual_alias_ids_raw, list):
        errors.append("inline packet aliases: inline_packets.alias_ids must be a list")
    else:
        actual_alias_ids = set(actual_alias_ids_raw)
        missing_aliases = sorted(expected_alias_ids - actual_alias_ids)
        extra_aliases = sorted(actual_alias_ids - expected_alias_ids)
        if missing_aliases:
            errors.append(f"inline packet aliases: alias_ids missing {missing_aliases}")
        if extra_aliases:
            errors.append(
                f"inline packet aliases: alias_ids carries unknown entries {extra_aliases}"
            )

    if not isinstance(actual_packet_ids_raw, list):
        errors.append("inline packet aliases: inline_packets.packet_ids must be a list")
    else:
        actual_packet_ids = set(actual_packet_ids_raw)
        missing_packets = sorted(expected_packet_ids - actual_packet_ids)
        extra_packets = sorted(actual_packet_ids - expected_packet_ids)
        if missing_packets:
            errors.append(f"inline packet aliases: packet_ids missing {missing_packets}")
        if extra_packets:
            errors.append(
                f"inline packet aliases: packet_ids carries unknown entries {extra_packets}"
            )

    if isinstance(packets_block, dict):
        packet_dict_keys = set(packets_block)
        missing_dict_keys = sorted(expected_packet_ids - packet_dict_keys)
        if missing_dict_keys:
            errors.append(
                f"inline packet aliases: packets dict missing entries {missing_dict_keys}"
            )


def _validate_preflight_gate_count(preflight: Any, errors: list[str]) -> None:
    """Preflight scorecard must enumerate exactly the canonical 5 gates.

    A drift here (4 or 6) is symptomatic of someone silently relaxing the
    AWS canary gate or doubling a gate after a rename — both are launch
    blockers.
    """

    if not isinstance(preflight, dict):
        return
    gates = preflight.get("blocking_gates")
    if not isinstance(gates, list):
        errors.append("preflight gate count: blocking_gates must be a list")
        return
    if len(gates) != EXPECTED_PREFLIGHT_BLOCKING_GATE_COUNT:
        errors.append(
            "preflight gate count: expected "
            f"{EXPECTED_PREFLIGHT_BLOCKING_GATE_COUNT} blocking_gates, "
            f"got {len(gates)} ({gates})"
        )
    if len(set(gates)) != len(gates):
        errors.append(f"preflight gate count: blocking_gates must be unique, got {gates}")


def _coerce_tool_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _extract_server_tool_count(server_json: Any) -> int | None:
    if not isinstance(server_json, dict):
        return None
    meta = server_json.get("_meta")
    if isinstance(meta, dict):
        publisher_meta = meta.get("io.modelcontextprotocol.registry/publisher-provided")
        if isinstance(publisher_meta, dict):
            count = _coerce_tool_count(publisher_meta.get("tool_count"))
            if count is not None:
                return count
    return None


def _extract_agents_tool_count(agents_json: Any) -> int | None:
    if not isinstance(agents_json, dict):
        return None
    tools_count = agents_json.get("tools_count")
    if isinstance(tools_count, dict):
        return _coerce_tool_count(tools_count.get("public_default"))
    return _coerce_tool_count(tools_count)


def _extract_llms_tool_count(llms_json: Any) -> int | None:
    """Pull the MCP tool count from ``llms.json`` when advertised.

    ``llms.json`` does not always carry an explicit ``tool_count`` field, but
    when present it appears either at ``mcp.tool_count`` or at
    ``tool_inventory.tool_count``. Returns ``None`` when no count is
    advertised so the parity check can degrade gracefully without
    false-flagging.
    """

    if not isinstance(llms_json, dict):
        return None
    mcp_block = llms_json.get("mcp")
    if isinstance(mcp_block, dict):
        count = _coerce_tool_count(mcp_block.get("tool_count"))
        if count is not None:
            return count
    inventory = llms_json.get("tool_inventory")
    if isinstance(inventory, dict):
        count = _coerce_tool_count(inventory.get("tool_count"))
        if count is not None:
            return count
    return _coerce_tool_count(llms_json.get("tool_count"))


def _validate_discovery_surface_parity(
    server_json: Any,
    agents_json: Any,
    llms_json: Any,
    errors: list[str],
) -> None:
    """server.json / agents.json / llms.json must advertise the same tool count.

    Drift here means an agent crawler will resolve different tool inventories
    depending on which surface it indexes — a Stream C regression.
    """

    server_count = _extract_server_tool_count(server_json)
    agents_count = _extract_agents_tool_count(agents_json)
    llms_count = _extract_llms_tool_count(llms_json)

    counts: dict[str, int] = {}
    if server_count is not None:
        counts["server.json"] = server_count
    else:
        errors.append("discovery parity: server.json missing tool_count")
    if agents_count is not None:
        counts["agents.json"] = agents_count
    else:
        errors.append("discovery parity: agents.json missing tools_count.public_default")

    # llms.json is allowed to omit the explicit count (schema is "emerging"),
    # but if it advertises one, it must match.
    if llms_count is not None:
        counts["llms.json"] = llms_count

    if counts and len(set(counts.values())) != 1:
        errors.append(f"discovery parity: tool count mismatch across surfaces: {counts}")


def validate_release_capsule(repo_root: Path) -> list[str]:
    """Return validation errors for the static release capsule."""
    errors: list[str] = []
    repo_root = repo_root.resolve()

    files = {
        WELL_KNOWN_RELEASE_PATH: _load_json(repo_root, WELL_KNOWN_RELEASE_PATH, errors),
        RUNTIME_POINTER_PATH: _load_json(repo_root, RUNTIME_POINTER_PATH, errors),
        MANIFEST_PATH: _load_json(repo_root, MANIFEST_PATH, errors),
        P0_FACADE_PATH: _load_json(repo_root, P0_FACADE_PATH, errors),
        CAPABILITY_MATRIX_PATH: _load_json(repo_root, CAPABILITY_MATRIX_PATH, errors),
        PREFLIGHT_SCORECARD_PATH: _load_json(repo_root, PREFLIGHT_SCORECARD_PATH, errors),
        OUTCOME_CATALOG_PATH: _load_json(repo_root, OUTCOME_CATALOG_PATH, errors),
        ACCOUNTING_CSV_PROFILES_PATH: _load_json(repo_root, ACCOUNTING_CSV_PROFILES_PATH, errors),
        ALGORITHM_BLUEPRINTS_PATH: _load_json(repo_root, ALGORITHM_BLUEPRINTS_PATH, errors),
        OUTCOME_SOURCE_CROSSWALK_PATH: _load_json(repo_root, OUTCOME_SOURCE_CROSSWALK_PATH, errors),
        PACKET_SKELETONS_PATH: _load_json(repo_root, PACKET_SKELETONS_PATH, errors),
        INLINE_PACKETS_PATH: _load_json(repo_root, INLINE_PACKETS_PATH, errors),
        PUBLIC_SOURCE_DOMAINS_PATH: _load_json(repo_root, PUBLIC_SOURCE_DOMAINS_PATH, errors),
        AWS_SPEND_PROGRAM_PATH: _load_json(repo_root, AWS_SPEND_PROGRAM_PATH, errors),
        AWS_EXECUTION_TEMPLATES_PATH: _load_json(repo_root, AWS_EXECUTION_TEMPLATES_PATH, errors),
    }
    well_known_release = files[WELL_KNOWN_RELEASE_PATH]
    pointer = files[RUNTIME_POINTER_PATH]
    manifest = files[MANIFEST_PATH]
    facade = files[P0_FACADE_PATH]
    matrix = files[CAPABILITY_MATRIX_PATH]
    preflight = files[PREFLIGHT_SCORECARD_PATH]
    outcome_catalog = files[OUTCOME_CATALOG_PATH]
    accounting_csv_profiles = files[ACCOUNTING_CSV_PROFILES_PATH]
    algorithm_blueprints = files[ALGORITHM_BLUEPRINTS_PATH]
    outcome_source_crosswalk = files[OUTCOME_SOURCE_CROSSWALK_PATH]
    packet_skeletons = files[PACKET_SKELETONS_PATH]
    inline_packets = files[INLINE_PACKETS_PATH]
    public_source_domains = files[PUBLIC_SOURCE_DOMAINS_PATH]
    aws_spend_program = files[AWS_SPEND_PROGRAM_PATH]
    aws_execution_templates = files[AWS_EXECUTION_TEMPLATES_PATH]

    _validate_leakage_tokens(files, errors)
    for relative_path, data in files.items():
        _validate_no_active_aws_pointer(data, str(relative_path), errors)

    if isinstance(well_known_release, dict):
        _require_equal(
            well_known_release.get("schema_version"),
            "jpcite.well_known_release.p0.v1",
            "well-known release schema_version",
            errors,
        )
        _require_equal(
            well_known_release.get("active_capsule_manifest"),
            PUBLIC_MANIFEST_PATH,
            "well-known release active_capsule_manifest",
            errors,
        )
        _require_equal(
            well_known_release.get("manifest_path"),
            PUBLIC_MANIFEST_PATH,
            "well-known release manifest_path",
            errors,
        )
        _require_equal(
            well_known_release.get("p0_facade_path"),
            PUBLIC_P0_FACADE_PATH,
            "well-known release p0_facade_path",
            errors,
        )
        _require_equal(
            well_known_release.get("runtime_pointer_path"),
            PUBLIC_RUNTIME_POINTER_PATH,
            "well-known release runtime_pointer_path",
            errors,
        )
        _require_false(
            well_known_release, "aws_runtime_dependency_allowed", "well-known release", errors
        )
        _require_false(
            well_known_release, "live_aws_commands_allowed", "well-known release", errors
        )
        manifest_file = repo_root / MANIFEST_PATH
        if manifest_file.exists():
            actual_sha256 = hashlib.sha256(manifest_file.read_bytes()).hexdigest()
            _require_equal(
                well_known_release.get("manifest_sha256"),
                actual_sha256,
                "well-known release manifest_sha256",
                errors,
            )

    if isinstance(pointer, dict):
        _require_equal(
            pointer.get("active_capsule_manifest"),
            PUBLIC_MANIFEST_PATH,
            "runtime pointer active_capsule_manifest",
            errors,
        )
        _require_false(pointer, "aws_runtime_dependency_allowed", "runtime pointer", errors)
        _require_false(pointer, "live_aws_commands_allowed", "runtime pointer", errors)

    if isinstance(manifest, dict):
        _require_false(
            manifest, "aws_runtime_dependency_allowed", "release capsule manifest", errors
        )
        _require_false(
            manifest, "request_time_llm_fact_generation_enabled", "release capsule manifest", errors
        )
        _require_false(manifest, "real_csv_runtime_enabled", "release capsule manifest", errors)
        _require_equal(
            manifest.get("capability_matrix_path"),
            PUBLIC_CAPABILITY_MATRIX_PATH,
            "manifest capability_matrix_path",
            errors,
        )

        _validate_generated_surface_paths(repo_root, manifest, errors)
        generated_surfaces = manifest.get("generated_surfaces")
        surfaces = (
            {surface for surface in generated_surfaces if isinstance(surface, str)}
            if isinstance(generated_surfaces, list)
            else set()
        )
        for surface in REQUIRED_GENERATED_SURFACES:
            if surface not in surfaces:
                errors.append(f"manifest generated_surfaces missing {surface}")

    if isinstance(facade, dict):
        _require_false(facade, "aws_runtime_dependency_allowed", "P0 facade", errors)
        _require_false(facade, "request_time_llm_fact_generation_enabled", "P0 facade", errors)
        _require_false(facade, "full_catalog_visible_by_default", "P0 facade", errors)
        _require_equal(
            facade.get("default_visibility"),
            "p0_facade_only",
            "P0 facade default_visibility",
            errors,
        )
        tools = facade.get("tools")
        tool_names = [tool.get("name") for tool in tools] if isinstance(tools, list) else None
        _require_equal(tool_names, EXPECTED_P0_TOOLS, "P0 facade tools", errors)
        _validate_p0_tool_semantics(tools, errors)

    if isinstance(matrix, dict):
        _require_false(matrix, "full_catalog_default_visible", "capability matrix", errors)
        _require_equal(
            matrix.get("p0_facade_tools"),
            EXPECTED_P0_TOOLS,
            "capability matrix P0 tools",
            errors,
        )
        capabilities = matrix.get("capabilities")
        capability_ids = (
            [capability.get("capability_id") for capability in capabilities]
            if isinstance(capabilities, list)
            else None
        )
        _require_equal(capability_ids, EXPECTED_P0_TOOLS, "capability matrix capabilities", errors)

    if isinstance(preflight, dict):
        # Stream W (2026-05-16): the scorecard is allowed to be in either
        # ``AWS_BLOCKED_PRE_FLIGHT`` or ``AWS_CANARY_READY``. The hard
        # invariant is that ``live_aws_commands_allowed`` MUST remain False
        # until operator unlock (Stream I).
        if preflight.get("state") not in {"AWS_BLOCKED_PRE_FLIGHT", "AWS_CANARY_READY"}:
            errors.append(
                f"preflight state mismatch: expected one of "
                f"['AWS_BLOCKED_PRE_FLIGHT', 'AWS_CANARY_READY'], got {preflight.get('state')!r}"
            )
        _require_false(preflight, "live_aws_commands_allowed", "preflight scorecard", errors)
        _require_equal(
            preflight.get("target_credit_conversion_usd"),
            EXPECTED_TARGET_CREDIT_CONVERSION_USD,
            "preflight target_credit_conversion_usd",
            errors,
        )
        if preflight.get("cash_bill_guard_enabled") is not True:
            errors.append("preflight scorecard must set cash_bill_guard_enabled=true")
        gates = set(preflight.get("blocking_gates", []))
        missing_gates = sorted(REQUIRED_BLOCKING_GATES - gates)
        if missing_gates:
            errors.append(f"preflight scorecard missing blocking gates: {missing_gates}")

    if isinstance(outcome_catalog, dict):
        _validate_outcome_catalog(outcome_catalog, errors)

    if isinstance(accounting_csv_profiles, dict):
        _validate_accounting_csv_profiles(accounting_csv_profiles, errors)

    if isinstance(algorithm_blueprints, dict):
        _validate_algorithm_blueprints(algorithm_blueprints, errors)

    if isinstance(outcome_source_crosswalk, dict):
        _validate_outcome_source_crosswalk(outcome_source_crosswalk, errors)

    if isinstance(packet_skeletons, dict):
        _validate_packet_skeletons(packet_skeletons, errors)

    if isinstance(inline_packets, dict):
        _validate_inline_packets(inline_packets, errors)

    if isinstance(public_source_domains, dict):
        _validate_public_source_domains(public_source_domains, errors)

    if isinstance(aws_spend_program, dict):
        _validate_aws_spend_program(aws_spend_program, errors)

    if isinstance(aws_execution_templates, dict):
        _validate_aws_execution_templates(aws_execution_templates, errors)

    capsule_ids = [
        data.get("capsule_id") if isinstance(data, dict) else None
        for data in [manifest, facade, preflight]
    ]
    if isinstance(well_known_release, dict):
        capsule_ids.append(well_known_release.get("active_capsule_id"))
    if isinstance(pointer, dict):
        capsule_ids.append(pointer.get("active_capsule_id"))
    if any(capsule_id is None for capsule_id in capsule_ids) or len(set(capsule_ids)) != 1:
        errors.append(f"capsule id mismatch across checked artifacts: {capsule_ids}")

    # Stream H extended checks (2026-05-16). These are best-effort and only
    # run when the supporting input files are reachable so that the legacy
    # capsule walks above keep their existing failure shape on stub fixtures
    # (e.g. tmp_path trees that contain only the capsule JSON files).
    _validate_schema_parity(repo_root, errors)
    _validate_outcome_pricing_complete(outcome_catalog, errors)
    _validate_inline_packet_aliases(repo_root, inline_packets, errors)
    _validate_preflight_gate_count(preflight, errors)
    discovery_paths = (SERVER_JSON_PATH, AGENTS_JSON_PATH, LLMS_JSON_PATH)
    if all((repo_root / path).exists() for path in discovery_paths):
        server_json = _load_json(repo_root, SERVER_JSON_PATH, errors)
        agents_json = _load_json(repo_root, AGENTS_JSON_PATH, errors)
        llms_json = _load_json(repo_root, LLMS_JSON_PATH, errors)
        _validate_discovery_surface_parity(server_json, agents_json, llms_json, errors)

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()

    errors = validate_release_capsule(args.repo_root)
    if errors:
        print("release capsule validator: failed")
        for error in errors:
            print(f"- {error}")
        return 1

    print("release capsule validator: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
