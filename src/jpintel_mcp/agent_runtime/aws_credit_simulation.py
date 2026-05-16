"""Deterministic local AWS credit preflight simulation.

This module is intentionally offline-only. It models the credit conversion
gate from local inputs and never imports AWS SDKs, shell helpers, or network
clients.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

TARGET_CREDIT_CONVERSION_USD = 19490
AWS_PROFILE = "bookyou-recovery"
AWS_ACCOUNT_ID = "993693061769"
AWS_REGION = "us-east-1"
BILLING_REGION = "us-east-1"

GATE_BLOCKED = "AWS_BLOCKED_PRE_FLIGHT"
GATE_READY = "AWS_CANARY_READY"

REQUIRED_BUDGET_GUARDS = (
    "jpcite-credit-gross-burn-2026-05",
    "jpcite-credit-paid-exposure-2026-05",
    "jpcite-credit-account-backstop-2026-05",
)

REQUIRED_TAG_KEYS = (
    "Project",
    "SpendProgram",
    "CreditRun",
    "Owner",
    "Environment",
    "Purpose",
    "AutoStop",
    "DataClass",
    "Workload",
)

ALLOWED_DATA_CLASS_VALUES = (
    "public-only",
    "synthetic-only",
    "derived-aggregate-only",
)

READ_ONLY_COMMAND_PLAN = (
    {
        "id": "caller_identity",
        "argv": (
            "aws",
            "sts",
            "get-caller-identity",
            "--profile",
            AWS_PROFILE,
            "--region",
            AWS_REGION,
        ),
        "mutates_aws": False,
    },
    {
        "id": "configured_region",
        "argv": (
            "aws",
            "configure",
            "get",
            "region",
            "--profile",
            AWS_PROFILE,
        ),
        "mutates_aws": False,
    },
    {
        "id": "budget_inventory",
        "argv": (
            "aws",
            "budgets",
            "describe-budgets",
            "--profile",
            AWS_PROFILE,
            "--region",
            BILLING_REGION,
            "--account-id",
            AWS_ACCOUNT_ID,
        ),
        "mutates_aws": False,
    },
    {
        "id": "tagged_resource_inventory",
        "argv": (
            "aws",
            "resourcegroupstaggingapi",
            "get-resources",
            "--profile",
            AWS_PROFILE,
            "--region",
            AWS_REGION,
            "--tag-filters",
            "Key=Project,Values=jpcite",
            "Key=CreditRun,Values=2026-05",
        ),
        "mutates_aws": False,
    },
)

REQUIRED_CANARY_CONDITIONS = (
    "account_identity_confirmed",
    "budget_guard_confirmed",
    "credit_eligibility_confirmed",
    "cash_bill_guard_confirmed",
    "queue_caps_confirmed",
    "teardown_recipes_confirmed",
    "tagging_controls_confirmed",
    "stale_resource_scan_confirmed",
)

DEFAULT_QUEUE_ITEMS = (
    {"name": "source_receipt_capture_queue", "count": 120, "unit_exposure_usd": 7.5},
    {"name": "ocr_embedding_queue", "count": 80, "unit_exposure_usd": 12.0},
    {"name": "packet_render_queue", "count": 50, "unit_exposure_usd": 3.0},
)

DEFAULT_TEARDOWN_ITEMS = (
    {"name": "artifact_lake", "delete_recipe": False, "debt_usd": 420.0},
    {"name": "batch_workers", "delete_recipe": False, "debt_usd": 640.0},
    {"name": "search_index", "delete_recipe": False, "debt_usd": 510.0},
)


@dataclass(frozen=True)
class ExposureInputs:
    """Local-only exposure assumptions used by the preflight model."""

    control_spend_usd: float = 0.0
    queue_items: tuple[Mapping[str, Any], ...] = DEFAULT_QUEUE_ITEMS
    teardown_items: tuple[Mapping[str, Any], ...] = DEFAULT_TEARDOWN_ITEMS
    untagged_resource_count: int = 3
    stale_resource_count: int = 2
    untagged_penalty_usd: float = 275.0
    stale_penalty_usd: float = 350.0
    reserve_ratio: float = 0.12


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    return default


def _int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _string(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _budget_name(budget: Mapping[str, Any]) -> str:
    return _string(budget.get("name") or budget.get("BudgetName"))


def _required_tag_keys(value: Any) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        return tuple(str(key) for key in value if isinstance(key, str))
    if isinstance(value, list | tuple):
        return tuple(str(key) for key in value if isinstance(key, str))
    return ()


def _queue_exposure_usd(queue_items: tuple[Mapping[str, Any], ...]) -> float:
    return sum(
        _number(item.get("count")) * _number(item.get("unit_exposure_usd")) for item in queue_items
    )


def _teardown_debt_usd(teardown_items: tuple[Mapping[str, Any], ...]) -> float:
    return sum(_number(item.get("debt_usd")) for item in teardown_items)


def _all_delete_recipes_present(teardown_items: tuple[Mapping[str, Any], ...]) -> bool:
    return bool(teardown_items) and all(
        item.get("delete_recipe") is True for item in teardown_items
    )


def _recipe_refs_present(teardown_items: tuple[Mapping[str, Any], ...]) -> bool:
    return bool(teardown_items) and all(
        isinstance(item.get("recipe_ref"), str) and bool(item["recipe_ref"].strip())
        for item in teardown_items
    )


def _identity_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    identity = _mapping(payload.get("caller_identity") or payload.get("aws_identity"))
    config = _mapping(payload.get("aws_config"))
    account_id = _string(identity.get("Account") or identity.get("account_id"))
    profile = _string(config.get("profile") or identity.get("profile"))
    region = _string(config.get("region") or identity.get("region"))

    return {
        "expected_account_id": AWS_ACCOUNT_ID,
        "observed_account_id": account_id,
        "account_id_matches": account_id == AWS_ACCOUNT_ID,
        "expected_profile": AWS_PROFILE,
        "observed_profile": profile,
        "profile_matches": profile == AWS_PROFILE,
        "expected_region": AWS_REGION,
        "observed_region": region,
        "region_matches": region == AWS_REGION,
        "principal_arn": _string(identity.get("Arn") or identity.get("arn")),
        "confirmed": account_id == AWS_ACCOUNT_ID
        and profile == AWS_PROFILE
        and region == AWS_REGION,
    }


def _budget_guard_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    budget_guard = _mapping(payload.get("budget_guard"))
    budgets_raw = budget_guard.get("budgets", ())
    if not isinstance(budgets_raw, list | tuple):
        budgets_raw = ()

    observed_names = tuple(
        name
        for budget in budgets_raw
        if isinstance(budget, Mapping)
        for name in (_budget_name(budget),)
        if name
    )
    missing_names = tuple(name for name in REQUIRED_BUDGET_GUARDS if name not in observed_names)
    alerts_confirmed = budget_guard.get("alerts_confirmed") is True
    actions_reviewed = budget_guard.get("actions_reviewed") is True

    return {
        "required_budget_names": REQUIRED_BUDGET_GUARDS,
        "observed_budget_names": observed_names,
        "missing_budget_names": missing_names,
        "alerts_confirmed": alerts_confirmed,
        "actions_reviewed": actions_reviewed,
        "confirmed": not missing_names and alerts_confirmed and actions_reviewed,
    }


def _tagging_policy_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    tagging_policy = _mapping(payload.get("tagging_policy"))
    observed_keys = _required_tag_keys(tagging_policy.get("required_tags"))
    missing_keys = tuple(key for key in REQUIRED_TAG_KEYS if key not in observed_keys)

    data_class_values = tagging_policy.get("allowed_data_class_values", ())
    if not isinstance(data_class_values, list | tuple):
        data_class_values = ()
    missing_data_classes = tuple(
        value for value in ALLOWED_DATA_CLASS_VALUES if value not in data_class_values
    )

    return {
        "required_tag_keys": REQUIRED_TAG_KEYS,
        "observed_tag_keys": observed_keys,
        "missing_tag_keys": missing_keys,
        "required_data_class_values": ALLOWED_DATA_CLASS_VALUES,
        "missing_data_class_values": missing_data_classes,
        "tag_on_create_enforced": tagging_policy.get("tag_on_create_enforced") is True,
        "untagged_exception_manifest_present": (
            tagging_policy.get("untagged_exception_manifest_present") is True
        ),
        "confirmed": not missing_keys
        and not missing_data_classes
        and tagging_policy.get("tag_on_create_enforced") is True
        and tagging_policy.get("untagged_exception_manifest_present") is True,
    }


def normalize_canary_conditions(
    conditions: Mapping[str, Any] | None = None,
) -> dict[str, bool]:
    provided = conditions or {}
    return {condition: provided.get(condition) is True for condition in REQUIRED_CANARY_CONDITIONS}


def build_preflight_simulation(
    *,
    canary_conditions: Mapping[str, Any] | None = None,
    exposure_inputs: ExposureInputs | None = None,
    inspection_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    inputs = exposure_inputs or ExposureInputs()
    evidence = inspection_evidence or {}
    normalized_canaries = normalize_canary_conditions(canary_conditions)
    identity = _identity_report(evidence)
    budget_guard = _budget_guard_report(evidence)
    tagging_policy = _tagging_policy_report(evidence)

    queue_exposure_usd = _queue_exposure_usd(inputs.queue_items)
    teardown_debt_usd = _teardown_debt_usd(inputs.teardown_items)
    untagged_penalty_total_usd = inputs.untagged_resource_count * inputs.untagged_penalty_usd
    stale_penalty_total_usd = inputs.stale_resource_count * inputs.stale_penalty_usd
    reserve_usd = round(
        TARGET_CREDIT_CONVERSION_USD * inputs.reserve_ratio
        + untagged_penalty_total_usd
        + stale_penalty_total_usd,
        2,
    )
    projected_exposure_usd = round(
        inputs.control_spend_usd + queue_exposure_usd + teardown_debt_usd + reserve_usd,
        2,
    )

    all_canaries_present = all(normalized_canaries.values())
    all_delete_recipes_present = _all_delete_recipes_present(inputs.teardown_items)
    all_recipe_refs_present = _recipe_refs_present(inputs.teardown_items)
    gate_state = (
        GATE_READY
        if all_canaries_present
        and all_delete_recipes_present
        and all_recipe_refs_present
        and identity["confirmed"]
        and budget_guard["confirmed"]
        and tagging_policy["confirmed"]
        else GATE_BLOCKED
    )

    missing_canary_conditions = tuple(
        condition for condition, present in normalized_canaries.items() if not present
    )
    missing_teardown_recipes = tuple(
        str(item.get("name", "unknown"))
        for item in inputs.teardown_items
        if item.get("delete_recipe") is not True
    )
    missing_teardown_recipe_refs = tuple(
        str(item.get("name", "unknown"))
        for item in inputs.teardown_items
        if not (isinstance(item.get("recipe_ref"), str) and item["recipe_ref"].strip())
    )

    return {
        "simulation_id": "aws-credit-local-preflight-2026-05-15",
        "profile": AWS_PROFILE,
        "account_id": AWS_ACCOUNT_ID,
        "region": AWS_REGION,
        "billing_region": BILLING_REGION,
        "target_credit_conversion_usd": TARGET_CREDIT_CONVERSION_USD,
        "gate_state": gate_state,
        "live_aws_commands_allowed": False,
        "read_only_command_plan": READ_ONLY_COMMAND_PLAN,
        "account_identity": identity,
        "budget_guard": budget_guard,
        "tagging_policy": tagging_policy,
        "canary_conditions": normalized_canaries,
        "missing_canary_conditions": missing_canary_conditions,
        "cash_bill_guard_enabled": True,
        "exposure": {
            "control_spend_usd": round(inputs.control_spend_usd, 2),
            "queued_exposure_usd": round(queue_exposure_usd, 2),
            "teardown_debt_usd": round(teardown_debt_usd, 2),
            "untagged_penalty_usd": round(untagged_penalty_total_usd, 2),
            "stale_penalty_usd": round(stale_penalty_total_usd, 2),
            "ineligible_charge_uncertainty_reserve_usd": reserve_usd,
            "projected_exposure_usd": projected_exposure_usd,
            "remaining_target_after_projected_exposure_usd": round(
                TARGET_CREDIT_CONVERSION_USD - projected_exposure_usd,
                2,
            ),
        },
        "teardown": {
            "all_resources_have_delete_recipe": (
                all_delete_recipes_present and all_recipe_refs_present
            ),
            "missing_delete_recipes": missing_teardown_recipes,
            "missing_recipe_refs": missing_teardown_recipe_refs,
            "post_teardown_attestation_non_aws_triggered": True,
        },
        "penalties": {
            "untagged_resource_count": inputs.untagged_resource_count,
            "stale_resource_count": inputs.stale_resource_count,
        },
    }


def exposure_inputs_from_mapping(payload: Mapping[str, Any]) -> ExposureInputs:
    exposure = payload.get("exposure_inputs")
    if not isinstance(exposure, Mapping):
        return ExposureInputs()

    queue_items = exposure.get("queue_items", DEFAULT_QUEUE_ITEMS)
    if not isinstance(queue_items, list | tuple):
        queue_items = DEFAULT_QUEUE_ITEMS

    teardown_items = exposure.get("teardown_items", DEFAULT_TEARDOWN_ITEMS)
    if not isinstance(teardown_items, list | tuple):
        teardown_items = DEFAULT_TEARDOWN_ITEMS

    return ExposureInputs(
        control_spend_usd=_number(exposure.get("control_spend_usd")),
        queue_items=tuple(item for item in queue_items if isinstance(item, Mapping)),
        teardown_items=tuple(item for item in teardown_items if isinstance(item, Mapping)),
        untagged_resource_count=_int(exposure.get("untagged_resource_count"), 3),
        stale_resource_count=_int(exposure.get("stale_resource_count"), 2),
        untagged_penalty_usd=_number(exposure.get("untagged_penalty_usd"), 275.0),
        stale_penalty_usd=_number(exposure.get("stale_penalty_usd"), 350.0),
        reserve_ratio=_number(exposure.get("reserve_ratio"), 0.12),
    )
