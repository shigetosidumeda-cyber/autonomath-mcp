"""Offline AWS execution template catalog for a future operator-run window.

This module is data-only. It does not import AWS SDKs, shell helpers, or
network clients, and it never renders or executes the mutating templates below.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

TARGET_CREDIT_SPEND_USD = 19490
CATALOG_VERSION = "jpcite.aws_execution_templates.p0.v1"
CATALOG_ID = "jpcite-aws-execution-template-catalog-2026-05-15"
EXECUTION_MODE = "offline_template_catalog"
LIVE_EXECUTION_BLOCKED_STATE = "AWS_TEMPLATE_CATALOG_BLOCKED"
LIVE_EXECUTION_UNLOCKED_STATE = "AWS_TEMPLATE_CATALOG_UNLOCK_OBJECT_COMPLETE"

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

BASE_REQUIRED_TAGS = {
    "Project": "jpcite",
    "SpendProgram": "aws-credit-19490",
    "CreditRun": "2026-05",
    "Owner": "bookyou-operator",
    "Environment": "future-live-run",
    "Purpose": "official-public-data-artifact-build",
    "AutoStop": "required",
    "DataClass": "public-only",
}

ALLOWED_DATA_CLASS_VALUES = (
    "public-only",
    "synthetic-only",
    "derived-aggregate-only",
)

TAG_POLICY_REQUIREMENTS = (
    {
        "tag_key": "Project",
        "required": True,
        "allowed_values": ("jpcite",),
        "enforcement": "tag_on_create_and_periodic_inventory",
    },
    {
        "tag_key": "SpendProgram",
        "required": True,
        "allowed_values": ("aws-credit-19490",),
        "enforcement": "tag_on_create_and_periodic_inventory",
    },
    {
        "tag_key": "CreditRun",
        "required": True,
        "allowed_values": ("2026-05",),
        "enforcement": "tag_on_create_and_periodic_inventory",
    },
    {
        "tag_key": "Owner",
        "required": True,
        "allowed_values": ("bookyou-operator",),
        "enforcement": "tag_on_create_and_periodic_inventory",
    },
    {
        "tag_key": "Environment",
        "required": True,
        "allowed_values": ("future-live-run",),
        "enforcement": "tag_on_create_and_periodic_inventory",
    },
    {
        "tag_key": "Purpose",
        "required": True,
        "allowed_values": ("official-public-data-artifact-build",),
        "enforcement": "tag_on_create_and_periodic_inventory",
    },
    {
        "tag_key": "AutoStop",
        "required": True,
        "allowed_values": ("required",),
        "enforcement": "tag_on_create_and_periodic_inventory",
    },
    {
        "tag_key": "DataClass",
        "required": True,
        "allowed_values": ALLOWED_DATA_CLASS_VALUES,
        "enforcement": "tag_on_create_and_periodic_inventory",
    },
    {
        "tag_key": "Workload",
        "required": True,
        "allowed_values": ("stage-specific-nonempty",),
        "enforcement": "tag_on_create_and_periodic_inventory",
    },
)

BUDGET_GUARD_TEMPLATE_IDS = (
    "budget_credit_gross_burn_guard",
    "budget_paid_cash_exposure_backstop",
    "budget_action_operator_stopline",
    "cost_anomaly_monitor_guard",
)

REQUIRED_OPERATOR_UNLOCK_FIELDS = (
    "schema_version",
    "unlock_id",
    "created_at_utc",
    "expires_at_utc",
    "operator_name",
    "operator_email",
    "aws_account_id",
    "aws_profile",
    "aws_region",
    "billing_region",
    "target_credit_spend_usd",
    "approved_stage_ids",
    "approved_template_ids",
    "budget_guard_attestation",
    "tag_policy_attestation",
    "teardown_recipe_attestation",
    "source_policy_attestation",
    "risk_acceptance",
    "operator_signature_sha256",
)

BUDGET_GUARD_ATTESTATION_FIELDS = (
    "gross_burn_budget_created",
    "paid_exposure_backstop_created",
    "budget_action_stopline_created",
    "cost_anomaly_monitor_created",
    "alerts_subscribed",
    "aws_credits_verified",
    "cash_bill_alarm_enabled",
)

TAG_POLICY_ATTESTATION_FIELDS = (
    "required_tags_enforced",
    "tag_on_create_controls_enabled",
    "untagged_exception_manifest_empty",
    "data_class_values_restricted",
)

TEARDOWN_RECIPE_ATTESTATION_FIELDS = (
    "every_resource_class_has_delete_recipe",
    "delete_recipe_dry_run_reviewed",
    "post_teardown_inventory_required",
)

SOURCE_POLICY_ATTESTATION_FIELDS = (
    "official_public_sources_only",
    "terms_receipts_required",
    "private_data_blocked",
)

RISK_ACCEPTANCE_FIELDS = (
    "operator_accepts_live_aws_mutation_templates",
    "target_19490_acknowledged",
    "rollback_owner_named",
    "live_run_window_utc",
)

MUTATING_AWS_CLI_VERBS = (
    "create",
    "delete",
    "deregister",
    "detach",
    "disable",
    "empty",
    "put",
    "register",
    "remove",
    "submit",
    "tag",
    "terminate",
    "update",
)


@dataclass(frozen=True)
class MutationTemplate:
    """Template for a future mutating AWS operation, never a runnable command."""

    template_id: str
    operation_name: str
    operation_template: str
    placeholders: tuple[str, ...]
    would_mutate_live_aws: bool = True
    executable: bool = False
    rendered_command: str | None = None

    def __post_init__(self) -> None:
        if not self.template_id.strip():
            raise ValueError("template_id is required")
        if not self.operation_name.strip():
            raise ValueError("operation_name is required")
        if "${" not in self.operation_template:
            raise ValueError("operation_template must keep placeholder tokens")
        if self.executable:
            raise ValueError("mutation templates are never executable")
        if self.rendered_command is not None:
            raise ValueError("mutation templates must not include rendered commands")

    def to_dict(self) -> dict[str, object]:
        return {
            "template_id": self.template_id,
            "operation_name": self.operation_name,
            "operation_template": self.operation_template,
            "placeholders": list(self.placeholders),
            "would_mutate_live_aws": self.would_mutate_live_aws,
            "executable": self.executable,
            "rendered_command": self.rendered_command,
        }


@dataclass(frozen=True)
class ExecutionTemplate:
    """Resource template retained offline until a separate unlock is complete."""

    template_id: str
    display_name: str
    category: str
    resource_class: str
    service_family: str
    required_tags: Mapping[str, str]
    guard_refs: tuple[str, ...]
    mutation_templates: tuple[MutationTemplate, ...]
    data_only: bool = True
    live_execution_allowed: bool = False
    unlock_required: bool = True

    def __post_init__(self) -> None:
        if not self.template_id.strip():
            raise ValueError("template_id is required")
        if not self.resource_class.strip():
            raise ValueError("resource_class is required")
        _validate_required_tags(self.required_tags)
        if not self.guard_refs:
            raise ValueError("guard_refs are required")
        if not self.mutation_templates:
            raise ValueError("mutation_templates are required")
        if not self.data_only:
            raise ValueError("execution templates must remain data-only")
        if self.live_execution_allowed:
            raise ValueError("execution templates are disabled by default")

    def to_dict(self) -> dict[str, object]:
        return {
            "template_id": self.template_id,
            "display_name": self.display_name,
            "category": self.category,
            "resource_class": self.resource_class,
            "service_family": self.service_family,
            "required_tags": dict(self.required_tags),
            "guard_refs": list(self.guard_refs),
            "mutation_templates": [template.to_dict() for template in self.mutation_templates],
            "data_only": self.data_only,
            "live_execution_allowed": self.live_execution_allowed,
            "unlock_required": self.unlock_required,
        }


@dataclass(frozen=True)
class QueueItemTemplate:
    """Queue entry for staged future work, expressed as a manifest row."""

    item_id: str
    resource_class: str
    template_ref: str
    max_items: int
    max_parallel: int
    unit_budget_ceiling_usd: int

    def __post_init__(self) -> None:
        if self.max_items < 0:
            raise ValueError("max_items must be non-negative")
        if self.max_parallel < 0:
            raise ValueError("max_parallel must be non-negative")
        if self.unit_budget_ceiling_usd < 0:
            raise ValueError("unit_budget_ceiling_usd must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "resource_class": self.resource_class,
            "template_ref": self.template_ref,
            "max_items": self.max_items,
            "max_parallel": self.max_parallel,
            "unit_budget_ceiling_usd": self.unit_budget_ceiling_usd,
        }


@dataclass(frozen=True)
class QueueManifest:
    """Staged queue manifest with hard-stop budget ceilings."""

    stage_id: str
    stage_name: str
    planned_usd: int
    soft_stop_usd: int
    hard_stop_usd: int
    required_tags: Mapping[str, str]
    queue_items: tuple[QueueItemTemplate, ...]
    guard_refs: tuple[str, ...]
    manifest_path: str
    data_only: bool = True
    live_execution_allowed: bool = False
    unlock_required: bool = True

    def __post_init__(self) -> None:
        if self.planned_usd < 0:
            raise ValueError("planned_usd must be non-negative")
        if not 0 <= self.soft_stop_usd <= self.hard_stop_usd:
            raise ValueError("soft_stop_usd must be between 0 and hard_stop_usd")
        if self.hard_stop_usd != self.planned_usd:
            raise ValueError("hard_stop_usd must equal planned_usd")
        _validate_required_tags(self.required_tags)
        if not self.queue_items:
            raise ValueError("queue_items are required")
        if not self.guard_refs:
            raise ValueError("guard_refs are required")
        if not self.data_only or self.live_execution_allowed:
            raise ValueError("queue manifests are offline-only by default")

    def to_dict(self, cumulative_planned_usd: int) -> dict[str, object]:
        return {
            "stage_id": self.stage_id,
            "stage_name": self.stage_name,
            "planned_usd": self.planned_usd,
            "soft_stop_usd": self.soft_stop_usd,
            "hard_stop_usd": self.hard_stop_usd,
            "cumulative_planned_usd": cumulative_planned_usd,
            "remaining_target_after_stage_usd": (TARGET_CREDIT_SPEND_USD - cumulative_planned_usd),
            "required_tags": dict(self.required_tags),
            "queue_items": [item.to_dict() for item in self.queue_items],
            "guard_refs": list(self.guard_refs),
            "manifest_path": self.manifest_path,
            "data_only": self.data_only,
            "live_execution_allowed": self.live_execution_allowed,
            "unlock_required": self.unlock_required,
        }


@dataclass(frozen=True)
class TeardownRecipe:
    """Delete recipe template required for each future resource class."""

    resource_class: str
    recipe_id: str
    deletion_order: int
    required_tags: Mapping[str, str]
    preconditions: tuple[str, ...]
    delete_step_templates: tuple[MutationTemplate, ...]
    verification_templates: tuple[MutationTemplate, ...]
    evidence_artifacts: tuple[str, ...]
    data_only: bool = True
    live_execution_allowed: bool = False

    def __post_init__(self) -> None:
        if self.deletion_order <= 0:
            raise ValueError("deletion_order must be positive")
        _validate_required_tags(self.required_tags)
        if not self.preconditions:
            raise ValueError("preconditions are required")
        if not self.delete_step_templates:
            raise ValueError("delete_step_templates are required")
        if not self.verification_templates:
            raise ValueError("verification_templates are required")
        if not self.evidence_artifacts:
            raise ValueError("evidence_artifacts are required")
        if not self.data_only or self.live_execution_allowed:
            raise ValueError("teardown recipes are offline-only by default")

    def to_dict(self) -> dict[str, object]:
        return {
            "resource_class": self.resource_class,
            "recipe_id": self.recipe_id,
            "deletion_order": self.deletion_order,
            "required_tags": dict(self.required_tags),
            "preconditions": list(self.preconditions),
            "delete_step_templates": [
                template.to_dict() for template in self.delete_step_templates
            ],
            "verification_templates": [
                template.to_dict() for template in self.verification_templates
            ],
            "evidence_artifacts": list(self.evidence_artifacts),
            "data_only": self.data_only,
            "live_execution_allowed": self.live_execution_allowed,
        }


def _tags(workload: str, *, data_class: str = "public-only") -> dict[str, str]:
    return {
        **BASE_REQUIRED_TAGS,
        "DataClass": data_class,
        "Workload": workload,
    }


def _validate_required_tags(tags: Mapping[str, str]) -> None:
    missing = tuple(key for key in REQUIRED_TAG_KEYS if not tags.get(key))
    if missing:
        raise ValueError(f"missing required tags: {missing!r}")


def _mutation(
    template_id: str,
    operation_name: str,
    operation_template: str,
    placeholders: tuple[str, ...],
    *,
    would_mutate_live_aws: bool = True,
) -> MutationTemplate:
    return MutationTemplate(
        template_id=template_id,
        operation_name=operation_name,
        operation_template=operation_template,
        placeholders=placeholders,
        would_mutate_live_aws=would_mutate_live_aws,
    )


def _template(
    template_id: str,
    display_name: str,
    category: str,
    resource_class: str,
    service_family: str,
    workload: str,
    operation_name: str,
    operation_template: str,
    placeholders: tuple[str, ...],
    *,
    guard_refs: tuple[str, ...] = (
        "budget_credit_gross_burn_guard",
        "budget_paid_cash_exposure_backstop",
        "required_tag_policy_template",
        "operator_unlock_manifest",
    ),
    data_class: str = "public-only",
) -> ExecutionTemplate:
    return ExecutionTemplate(
        template_id=template_id,
        display_name=display_name,
        category=category,
        resource_class=resource_class,
        service_family=service_family,
        required_tags=_tags(workload, data_class=data_class),
        guard_refs=guard_refs,
        mutation_templates=(
            _mutation(
                f"{template_id}_mutation_template",
                operation_name,
                operation_template,
                placeholders,
            ),
        ),
    )


EXECUTION_TEMPLATES = (
    _template(
        "budget_credit_gross_burn_guard",
        "Gross credit burn budget guard",
        "budget_guard",
        "aws_budget",
        "aws-budgets",
        "budget-gross-burn",
        "create_budget_template",
        (
            "aws budgets create-budget --account-id ${aws_account_id} "
            "--budget file://${gross_burn_budget_spec_path} "
            "--notifications-with-subscribers file://${budget_alerts_path} "
            "--region ${billing_region} --profile ${aws_profile}"
        ),
        (
            "aws_account_id",
            "gross_burn_budget_spec_path",
            "budget_alerts_path",
            "billing_region",
            "aws_profile",
        ),
        guard_refs=("operator_unlock_manifest", "required_tag_policy_template"),
    ),
    _template(
        "budget_paid_cash_exposure_backstop",
        "Paid cash exposure backstop budget",
        "budget_guard",
        "aws_budget",
        "aws-budgets",
        "budget-paid-cash-backstop",
        "create_budget_template",
        (
            "aws budgets create-budget --account-id ${aws_account_id} "
            "--budget file://${paid_exposure_budget_spec_path} "
            "--notifications-with-subscribers file://${paid_exposure_alerts_path} "
            "--region ${billing_region} --profile ${aws_profile}"
        ),
        (
            "aws_account_id",
            "paid_exposure_budget_spec_path",
            "paid_exposure_alerts_path",
            "billing_region",
            "aws_profile",
        ),
        guard_refs=("operator_unlock_manifest", "required_tag_policy_template"),
    ),
    _template(
        "budget_action_operator_stopline",
        "Budget action operator stopline",
        "budget_guard",
        "budget_action",
        "aws-budgets",
        "budget-action-stopline",
        "create_budget_action_template",
        (
            "aws budgets create-budget-action --account-id ${aws_account_id} "
            "--budget-name ${gross_burn_budget_name} "
            "--notification-type ACTUAL --action-threshold file://${action_threshold_path} "
            "--definition file://${budget_action_definition_path} "
            "--approval-model MANUAL --region ${billing_region} --profile ${aws_profile}"
        ),
        (
            "aws_account_id",
            "gross_burn_budget_name",
            "action_threshold_path",
            "budget_action_definition_path",
            "billing_region",
            "aws_profile",
        ),
        guard_refs=("operator_unlock_manifest", "required_tag_policy_template"),
    ),
    _template(
        "cost_anomaly_monitor_guard",
        "Cost anomaly monitor guard",
        "budget_guard",
        "cost_anomaly_monitor",
        "aws-ce",
        "cost-anomaly-monitor",
        "create_anomaly_monitor_template",
        (
            "aws ce create-anomaly-monitor "
            "--anomaly-monitor file://${cost_anomaly_monitor_spec_path} "
            "--region ${billing_region} --profile ${aws_profile}"
        ),
        ("cost_anomaly_monitor_spec_path", "billing_region", "aws_profile"),
        guard_refs=("operator_unlock_manifest", "required_tag_policy_template"),
    ),
    _template(
        "required_tag_policy_template",
        "Required tag policy enforcement",
        "tag_policy",
        "tag_policy",
        "aws-organizations",
        "required-tag-policy",
        "create_tag_policy_template",
        (
            "aws organizations create-policy --name ${tag_policy_name} "
            "--type TAG_POLICY --content file://${tag_policy_document_path} "
            "--profile ${aws_profile}"
        ),
        ("tag_policy_name", "tag_policy_document_path", "aws_profile"),
        guard_refs=("operator_unlock_manifest", "budget_credit_gross_burn_guard"),
    ),
    _template(
        "iam_execution_role_template",
        "Execution role for batch workers",
        "runtime_resource",
        "iam_role",
        "aws-iam",
        "batch-execution-role",
        "create_role_template",
        (
            "aws iam create-role --role-name ${execution_role_name} "
            "--assume-role-policy-document file://${assume_role_policy_path} "
            "--tags file://${required_tags_path} --profile ${aws_profile}"
        ),
        (
            "execution_role_name",
            "assume_role_policy_path",
            "required_tags_path",
            "aws_profile",
        ),
    ),
    _template(
        "iam_least_privilege_policy_template",
        "Least privilege policy for public-source pipeline",
        "runtime_resource",
        "iam_policy",
        "aws-iam",
        "least-privilege-policy",
        "create_policy_template",
        (
            "aws iam create-policy --policy-name ${policy_name} "
            "--policy-document file://${policy_document_path} "
            "--tags file://${required_tags_path} --profile ${aws_profile}"
        ),
        (
            "policy_name",
            "policy_document_path",
            "required_tags_path",
            "aws_profile",
        ),
    ),
    _template(
        "artifact_lake_bucket_template",
        "Artifact lake bucket",
        "runtime_resource",
        "s3_bucket",
        "aws-s3",
        "artifact-lake",
        "create_bucket_template",
        (
            "aws s3api create-bucket --bucket ${artifact_bucket_name} "
            "--create-bucket-configuration LocationConstraint=${aws_region} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        ("artifact_bucket_name", "aws_region", "aws_profile"),
    ),
    _template(
        "source_capture_queue_template",
        "Source capture SQS queue",
        "runtime_resource",
        "sqs_queue",
        "aws-sqs",
        "source-capture-queue",
        "create_queue_template",
        (
            "aws sqs create-queue --queue-name ${source_capture_queue_name} "
            "--attributes file://${source_capture_queue_attributes_path} "
            "--tags file://${required_tags_path} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        (
            "source_capture_queue_name",
            "source_capture_queue_attributes_path",
            "required_tags_path",
            "aws_region",
            "aws_profile",
        ),
    ),
    _template(
        "batch_compute_environment_template",
        "Batch compute environment",
        "runtime_resource",
        "batch_compute_environment",
        "aws-batch",
        "batch-compute-environment",
        "create_compute_environment_template",
        (
            "aws batch create-compute-environment "
            "--compute-environment-name ${compute_environment_name} "
            "--type MANAGED --compute-resources file://${compute_resources_path} "
            "--service-role ${batch_service_role_arn} --tags file://${required_tags_path} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        (
            "compute_environment_name",
            "compute_resources_path",
            "batch_service_role_arn",
            "required_tags_path",
            "aws_region",
            "aws_profile",
        ),
    ),
    _template(
        "batch_job_queue_template",
        "Batch job queue",
        "runtime_resource",
        "batch_job_queue",
        "aws-batch",
        "batch-job-queue",
        "create_job_queue_template",
        (
            "aws batch create-job-queue --job-queue-name ${job_queue_name} "
            "--priority ${job_queue_priority} "
            "--compute-environment-order file://${compute_environment_order_path} "
            "--tags file://${required_tags_path} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        (
            "job_queue_name",
            "job_queue_priority",
            "compute_environment_order_path",
            "required_tags_path",
            "aws_region",
            "aws_profile",
        ),
    ),
    _template(
        "batch_job_definition_template",
        "Batch job definition",
        "runtime_resource",
        "batch_job_definition",
        "aws-batch",
        "batch-job-definition",
        "register_job_definition_template",
        (
            "aws batch register-job-definition --job-definition-name ${job_definition_name} "
            "--type container --container-properties file://${container_properties_path} "
            "--tags file://${required_tags_path} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        (
            "job_definition_name",
            "container_properties_path",
            "required_tags_path",
            "aws_region",
            "aws_profile",
        ),
    ),
    _template(
        "step_function_orchestrator_template",
        "Step Functions orchestrator",
        "runtime_resource",
        "stepfunctions_state_machine",
        "aws-stepfunctions",
        "pipeline-orchestrator",
        "create_state_machine_template",
        (
            "aws stepfunctions create-state-machine --name ${state_machine_name} "
            "--definition file://${state_machine_definition_path} "
            "--role-arn ${state_machine_role_arn} --tags file://${required_tags_path} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        (
            "state_machine_name",
            "state_machine_definition_path",
            "state_machine_role_arn",
            "required_tags_path",
            "aws_region",
            "aws_profile",
        ),
    ),
    _template(
        "public_manifest_table_template",
        "Public manifest DynamoDB table",
        "runtime_resource",
        "dynamodb_table",
        "aws-dynamodb",
        "public-manifest-table",
        "create_table_template",
        (
            "aws dynamodb create-table --table-name ${manifest_table_name} "
            "--cli-input-json file://${manifest_table_spec_path} "
            "--tags file://${required_tags_path} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        (
            "manifest_table_name",
            "manifest_table_spec_path",
            "required_tags_path",
            "aws_region",
            "aws_profile",
        ),
    ),
    _template(
        "public_search_domain_template",
        "Public search OpenSearch domain",
        "runtime_resource",
        "opensearch_domain",
        "aws-opensearch",
        "public-search-domain",
        "create_domain_template",
        (
            "aws opensearch create-domain --domain-name ${search_domain_name} "
            "--cli-input-json file://${search_domain_spec_path} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        ("search_domain_name", "search_domain_spec_path", "aws_region", "aws_profile"),
    ),
    _template(
        "worker_image_repository_template",
        "Worker image ECR repository",
        "runtime_resource",
        "ecr_repository",
        "aws-ecr",
        "worker-image-repository",
        "create_repository_template",
        (
            "aws ecr create-repository --repository-name ${repository_name} "
            "--tags file://${required_tags_path} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        ("repository_name", "required_tags_path", "aws_region", "aws_profile"),
    ),
    _template(
        "stage_scheduler_rule_template",
        "Stage scheduler EventBridge rule",
        "runtime_resource",
        "eventbridge_rule",
        "aws-events",
        "stage-scheduler-rule",
        "put_rule_template",
        (
            "aws events put-rule --name ${scheduler_rule_name} "
            "--schedule-expression ${schedule_expression} "
            "--tags file://${required_tags_path} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        (
            "scheduler_rule_name",
            "schedule_expression",
            "required_tags_path",
            "aws_region",
            "aws_profile",
        ),
    ),
    _template(
        "pipeline_log_group_template",
        "Pipeline CloudWatch log group",
        "runtime_resource",
        "cloudwatch_log_group",
        "aws-logs",
        "pipeline-log-group",
        "create_log_group_template",
        (
            "aws logs create-log-group --log-group-name ${log_group_name} "
            "--tags file://${required_tags_path} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        ("log_group_name", "required_tags_path", "aws_region", "aws_profile"),
    ),
)


def _queue_item(
    item_id: str,
    resource_class: str,
    template_ref: str,
    max_items: int,
    max_parallel: int,
    unit_budget_ceiling_usd: int,
) -> QueueItemTemplate:
    return QueueItemTemplate(
        item_id=item_id,
        resource_class=resource_class,
        template_ref=template_ref,
        max_items=max_items,
        max_parallel=max_parallel,
        unit_budget_ceiling_usd=unit_budget_ceiling_usd,
    )


def _queue_manifest(
    stage_id: str,
    stage_name: str,
    planned_usd: int,
    soft_stop_usd: int,
    hard_stop_usd: int,
    workload: str,
    queue_items: tuple[QueueItemTemplate, ...],
) -> QueueManifest:
    return QueueManifest(
        stage_id=stage_id,
        stage_name=stage_name,
        planned_usd=planned_usd,
        soft_stop_usd=soft_stop_usd,
        hard_stop_usd=hard_stop_usd,
        required_tags=_tags(workload),
        queue_items=queue_items,
        guard_refs=(
            "budget_credit_gross_burn_guard",
            "budget_paid_cash_exposure_backstop",
            "cost_anomaly_monitor_guard",
            "required_tag_policy_template",
            "operator_unlock_manifest",
        ),
        manifest_path=f"aws_execution_templates/queues/{stage_id}.manifest.json",
    )


STAGED_QUEUE_MANIFESTS = (
    _queue_manifest(
        "stage_00_preflight_evidence_lock",
        "Preflight evidence lock",
        0,
        0,
        0,
        "preflight-evidence-lock",
        (
            _queue_item(
                "budget_guard_review",
                "aws_budget",
                "budget_credit_gross_burn_guard",
                1,
                1,
                0,
            ),
            _queue_item(
                "tag_policy_review",
                "tag_policy",
                "required_tag_policy_template",
                1,
                1,
                0,
            ),
        ),
    ),
    _queue_manifest(
        "stage_01_official_source_inventory",
        "Official source inventory",
        2140,
        1925,
        2140,
        "official-source-inventory",
        (
            _queue_item(
                "source_registry_manifest",
                "s3_bucket",
                "artifact_lake_bucket_template",
                180,
                12,
                12,
            ),
            _queue_item(
                "terms_receipt_manifest",
                "dynamodb_table",
                "public_manifest_table_template",
                180,
                8,
                12,
            ),
        ),
    ),
    _queue_manifest(
        "stage_02_public_collection_capture",
        "Public collection capture",
        4360,
        3920,
        4360,
        "public-collection-capture",
        (
            _queue_item(
                "public_capture_jobs",
                "batch_job_queue",
                "batch_job_queue_template",
                240,
                24,
                18,
            ),
            _queue_item(
                "source_capture_messages",
                "sqs_queue",
                "source_capture_queue_template",
                240,
                24,
                18,
            ),
        ),
    ),
    _queue_manifest(
        "stage_03_ocr_normalization_search_build",
        "OCR normalization and search build",
        5180,
        4660,
        5180,
        "ocr-normalization-search",
        (
            _queue_item(
                "ocr_normalization_jobs",
                "batch_job_definition",
                "batch_job_definition_template",
                260,
                20,
                20,
            ),
            _queue_item(
                "public_search_index_build",
                "opensearch_domain",
                "public_search_domain_template",
                1,
                1,
                5180,
            ),
        ),
    ),
    _queue_manifest(
        "stage_04_claim_graph_packet_factory",
        "Claim graph and packet factory",
        3720,
        3345,
        3720,
        "claim-graph-packet-factory",
        (
            _queue_item(
                "packet_orchestration_runs",
                "stepfunctions_state_machine",
                "step_function_orchestrator_template",
                120,
                10,
                31,
            ),
            _queue_item(
                "packet_manifest_writes",
                "dynamodb_table",
                "public_manifest_table_template",
                120,
                10,
                31,
            ),
        ),
    ),
    _queue_manifest(
        "stage_05_quality_eval_gap_review",
        "Quality evaluation and gap review",
        2190,
        1970,
        2190,
        "quality-eval-gap-review",
        (
            _queue_item(
                "quality_eval_jobs",
                "batch_compute_environment",
                "batch_compute_environment_template",
                90,
                8,
                24,
            ),
            _queue_item(
                "quality_log_streams",
                "cloudwatch_log_group",
                "pipeline_log_group_template",
                90,
                8,
                24,
            ),
        ),
    ),
    _queue_manifest(
        "stage_06_release_artifact_packaging",
        "Release artifact packaging",
        1400,
        1260,
        1400,
        "release-artifact-packaging",
        (
            _queue_item(
                "release_image_publish",
                "ecr_repository",
                "worker_image_repository_template",
                8,
                2,
                175,
            ),
            _queue_item(
                "release_scheduler_rule",
                "eventbridge_rule",
                "stage_scheduler_rule_template",
                1,
                1,
                1400,
            ),
        ),
    ),
    _queue_manifest(
        "stage_07_teardown_attestation",
        "Teardown attestation",
        500,
        450,
        500,
        "teardown-attestation",
        (
            _queue_item(
                "teardown_role_review",
                "iam_role",
                "iam_execution_role_template",
                4,
                1,
                125,
            ),
            _queue_item(
                "teardown_policy_review",
                "iam_policy",
                "iam_least_privilege_policy_template",
                4,
                1,
                125,
            ),
        ),
    ),
)


def _delete_recipe(
    resource_class: str,
    deletion_order: int,
    workload: str,
    delete_template: str,
    delete_placeholders: tuple[str, ...],
    verify_template: str,
    verify_placeholders: tuple[str, ...],
) -> TeardownRecipe:
    return TeardownRecipe(
        resource_class=resource_class,
        recipe_id=f"delete_{resource_class}_recipe",
        deletion_order=deletion_order,
        required_tags=_tags(workload),
        preconditions=(
            "operator_unlock_manifest_complete",
            "resource_inventory_scoped_to_required_tags",
            "artifact_export_and_checksums_confirmed",
        ),
        delete_step_templates=(
            _mutation(
                f"delete_{resource_class}_template",
                f"delete_{resource_class}",
                delete_template,
                delete_placeholders,
            ),
        ),
        verification_templates=(
            _mutation(
                f"verify_{resource_class}_deleted_template",
                f"verify_{resource_class}_deleted",
                verify_template,
                verify_placeholders,
                would_mutate_live_aws=False,
            ),
        ),
        evidence_artifacts=(
            f"teardown/{resource_class}/pre_delete_inventory.json",
            f"teardown/{resource_class}/delete_recipe_review.json",
            f"teardown/{resource_class}/post_delete_inventory.json",
        ),
    )


TEARDOWN_RECIPES = (
    _delete_recipe(
        "eventbridge_rule",
        10,
        "teardown-eventbridge-rule",
        (
            "aws events remove-targets --rule ${rule_name} --ids ${target_ids} "
            "--region ${aws_region} --profile ${aws_profile} && "
            "aws events delete-rule --name ${rule_name} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        ("rule_name", "target_ids", "aws_region", "aws_profile"),
        (
            "aws events list-rules --name-prefix ${rule_name} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        ("rule_name", "aws_region", "aws_profile"),
    ),
    _delete_recipe(
        "stepfunctions_state_machine",
        20,
        "teardown-stepfunctions",
        (
            "aws stepfunctions delete-state-machine "
            "--state-machine-arn ${state_machine_arn} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        ("state_machine_arn", "aws_region", "aws_profile"),
        (
            "aws stepfunctions describe-state-machine "
            "--state-machine-arn ${state_machine_arn} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        ("state_machine_arn", "aws_region", "aws_profile"),
    ),
    _delete_recipe(
        "batch_job_queue",
        30,
        "teardown-batch-job-queue",
        (
            "aws batch update-job-queue --job-queue ${job_queue_name} --state DISABLED "
            "--region ${aws_region} --profile ${aws_profile} && "
            "aws batch delete-job-queue --job-queue ${job_queue_name} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        ("job_queue_name", "aws_region", "aws_profile"),
        (
            "aws batch describe-job-queues --job-queues ${job_queue_name} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        ("job_queue_name", "aws_region", "aws_profile"),
    ),
    _delete_recipe(
        "batch_compute_environment",
        40,
        "teardown-batch-compute-environment",
        (
            "aws batch update-compute-environment "
            "--compute-environment ${compute_environment_name} --state DISABLED "
            "--region ${aws_region} --profile ${aws_profile} && "
            "aws batch delete-compute-environment "
            "--compute-environment ${compute_environment_name} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        ("compute_environment_name", "aws_region", "aws_profile"),
        (
            "aws batch describe-compute-environments "
            "--compute-environments ${compute_environment_name} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        ("compute_environment_name", "aws_region", "aws_profile"),
    ),
    _delete_recipe(
        "batch_job_definition",
        50,
        "teardown-batch-job-definition",
        (
            "aws batch deregister-job-definition "
            "--job-definition ${job_definition_arn} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        ("job_definition_arn", "aws_region", "aws_profile"),
        (
            "aws batch describe-job-definitions "
            "--job-definitions ${job_definition_arn} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        ("job_definition_arn", "aws_region", "aws_profile"),
    ),
    _delete_recipe(
        "sqs_queue",
        60,
        "teardown-sqs-queue",
        (
            "aws sqs delete-queue --queue-url ${queue_url} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        ("queue_url", "aws_region", "aws_profile"),
        (
            "aws sqs get-queue-url --queue-name ${queue_name} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        ("queue_name", "aws_region", "aws_profile"),
    ),
    _delete_recipe(
        "opensearch_domain",
        70,
        "teardown-opensearch-domain",
        (
            "aws opensearch delete-domain --domain-name ${domain_name} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        ("domain_name", "aws_region", "aws_profile"),
        (
            "aws opensearch describe-domain --domain-name ${domain_name} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        ("domain_name", "aws_region", "aws_profile"),
    ),
    _delete_recipe(
        "dynamodb_table",
        80,
        "teardown-dynamodb-table",
        (
            "aws dynamodb delete-table --table-name ${table_name} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        ("table_name", "aws_region", "aws_profile"),
        (
            "aws dynamodb describe-table --table-name ${table_name} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        ("table_name", "aws_region", "aws_profile"),
    ),
    _delete_recipe(
        "cloudwatch_log_group",
        90,
        "teardown-cloudwatch-log-group",
        (
            "aws logs delete-log-group --log-group-name ${log_group_name} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        ("log_group_name", "aws_region", "aws_profile"),
        (
            "aws logs describe-log-groups --log-group-name-prefix ${log_group_name} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        ("log_group_name", "aws_region", "aws_profile"),
    ),
    _delete_recipe(
        "ecr_repository",
        100,
        "teardown-ecr-repository",
        (
            "aws ecr delete-repository --repository-name ${repository_name} --force "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        ("repository_name", "aws_region", "aws_profile"),
        (
            "aws ecr describe-repositories --repository-names ${repository_name} "
            "--region ${aws_region} --profile ${aws_profile}"
        ),
        ("repository_name", "aws_region", "aws_profile"),
    ),
    _delete_recipe(
        "s3_bucket",
        110,
        "teardown-s3-bucket",
        (
            "aws s3api delete-objects --bucket ${bucket_name} "
            "--delete file://${delete_manifest_path} --region ${aws_region} "
            "--profile ${aws_profile} && aws s3api delete-bucket "
            "--bucket ${bucket_name} --region ${aws_region} --profile ${aws_profile}"
        ),
        ("bucket_name", "delete_manifest_path", "aws_region", "aws_profile"),
        (
            "aws s3api head-bucket --bucket ${bucket_name} --region ${aws_region} "
            "--profile ${aws_profile}"
        ),
        ("bucket_name", "aws_region", "aws_profile"),
    ),
    _delete_recipe(
        "tag_policy",
        120,
        "teardown-tag-policy",
        (
            "aws organizations detach-policy --policy-id ${tag_policy_id} "
            "--target-id ${target_id} --profile ${aws_profile} && "
            "aws organizations delete-policy --policy-id ${tag_policy_id} "
            "--profile ${aws_profile}"
        ),
        ("tag_policy_id", "target_id", "aws_profile"),
        ("aws organizations describe-policy --policy-id ${tag_policy_id} --profile ${aws_profile}"),
        ("tag_policy_id", "aws_profile"),
    ),
    _delete_recipe(
        "budget_action",
        130,
        "teardown-budget-action",
        (
            "aws budgets delete-budget-action --account-id ${aws_account_id} "
            "--budget-name ${budget_name} --action-id ${action_id} "
            "--region ${billing_region} --profile ${aws_profile}"
        ),
        ("aws_account_id", "budget_name", "action_id", "billing_region", "aws_profile"),
        (
            "aws budgets describe-budget-actions-for-budget "
            "--account-id ${aws_account_id} --budget-name ${budget_name} "
            "--region ${billing_region} --profile ${aws_profile}"
        ),
        ("aws_account_id", "budget_name", "billing_region", "aws_profile"),
    ),
    _delete_recipe(
        "cost_anomaly_monitor",
        140,
        "teardown-cost-anomaly-monitor",
        (
            "aws ce delete-anomaly-monitor --monitor-arn ${monitor_arn} "
            "--region ${billing_region} --profile ${aws_profile}"
        ),
        ("monitor_arn", "billing_region", "aws_profile"),
        (
            "aws ce get-anomaly-monitors --monitor-arn-list ${monitor_arn} "
            "--region ${billing_region} --profile ${aws_profile}"
        ),
        ("monitor_arn", "billing_region", "aws_profile"),
    ),
    _delete_recipe(
        "aws_budget",
        150,
        "teardown-aws-budget",
        (
            "aws budgets delete-budget --account-id ${aws_account_id} "
            "--budget-name ${budget_name} --region ${billing_region} "
            "--profile ${aws_profile}"
        ),
        ("aws_account_id", "budget_name", "billing_region", "aws_profile"),
        (
            "aws budgets describe-budget --account-id ${aws_account_id} "
            "--budget-name ${budget_name} --region ${billing_region} "
            "--profile ${aws_profile}"
        ),
        ("aws_account_id", "budget_name", "billing_region", "aws_profile"),
    ),
    _delete_recipe(
        "iam_policy",
        160,
        "teardown-iam-policy",
        (
            "aws iam delete-policy-version --policy-arn ${policy_arn} "
            "--version-id ${non_default_version_id} --profile ${aws_profile} && "
            "aws iam delete-policy --policy-arn ${policy_arn} --profile ${aws_profile}"
        ),
        ("policy_arn", "non_default_version_id", "aws_profile"),
        ("aws iam get-policy --policy-arn ${policy_arn} --profile ${aws_profile}"),
        ("policy_arn", "aws_profile"),
    ),
    _delete_recipe(
        "iam_role",
        170,
        "teardown-iam-role",
        (
            "aws iam detach-role-policy --role-name ${role_name} "
            "--policy-arn ${policy_arn} --profile ${aws_profile} && "
            "aws iam delete-role --role-name ${role_name} --profile ${aws_profile}"
        ),
        ("role_name", "policy_arn", "aws_profile"),
        ("aws iam get-role --role-name ${role_name} --profile ${aws_profile}"),
        ("role_name", "aws_profile"),
    ),
)


OPERATOR_UNLOCK_MANIFEST_SCHEMA = {
    "schema_version": "jpcite.aws_operator_unlock_manifest.p0.v1",
    "type": "object",
    "additionalProperties": False,
    "required": REQUIRED_OPERATOR_UNLOCK_FIELDS,
    "properties": {
        "schema_version": {"const": "jpcite.aws_operator_unlock_manifest.p0.v1"},
        "unlock_id": {"type": "string", "minLength": 8},
        "created_at_utc": {"type": "string", "format": "date-time"},
        "expires_at_utc": {"type": "string", "format": "date-time"},
        "operator_name": {"type": "string", "minLength": 1},
        "operator_email": {"type": "string", "minLength": 3},
        "aws_account_id": {"type": "string", "minLength": 12, "maxLength": 12},
        "aws_profile": {"type": "string", "minLength": 1},
        "aws_region": {"type": "string", "minLength": 1},
        "billing_region": {"type": "string", "minLength": 1},
        "target_credit_spend_usd": {"const": TARGET_CREDIT_SPEND_USD},
        "approved_stage_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": len(STAGED_QUEUE_MANIFESTS),
        },
        "approved_template_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": len(EXECUTION_TEMPLATES),
        },
        "budget_guard_attestation": {
            "type": "object",
            "required": BUDGET_GUARD_ATTESTATION_FIELDS,
        },
        "tag_policy_attestation": {
            "type": "object",
            "required": TAG_POLICY_ATTESTATION_FIELDS,
        },
        "teardown_recipe_attestation": {
            "type": "object",
            "required": TEARDOWN_RECIPE_ATTESTATION_FIELDS,
        },
        "source_policy_attestation": {
            "type": "object",
            "required": SOURCE_POLICY_ATTESTATION_FIELDS,
        },
        "risk_acceptance": {
            "type": "object",
            "required": RISK_ACCEPTANCE_FIELDS,
        },
        "operator_signature_sha256": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    },
}


def planned_queue_target_usd(
    queue_manifests: tuple[QueueManifest, ...] = STAGED_QUEUE_MANIFESTS,
) -> int:
    return sum(manifest.planned_usd for manifest in queue_manifests)


def template_ids(
    templates: tuple[ExecutionTemplate, ...] = EXECUTION_TEMPLATES,
) -> tuple[str, ...]:
    return tuple(template.template_id for template in templates)


def stage_ids(
    queue_manifests: tuple[QueueManifest, ...] = STAGED_QUEUE_MANIFESTS,
) -> tuple[str, ...]:
    return tuple(manifest.stage_id for manifest in queue_manifests)


def resource_classes_requiring_delete_recipe() -> tuple[str, ...]:
    classes = {template.resource_class for template in EXECUTION_TEMPLATES} | {
        item.resource_class for manifest in STAGED_QUEUE_MANIFESTS for item in manifest.queue_items
    }
    return tuple(sorted(classes))


def resource_classes_with_delete_recipe(
    recipes: tuple[TeardownRecipe, ...] = TEARDOWN_RECIPES,
) -> tuple[str, ...]:
    return tuple(sorted(recipe.resource_class for recipe in recipes))


def missing_teardown_recipe_resource_classes() -> tuple[str, ...]:
    required = set(resource_classes_requiring_delete_recipe())
    observed = set(resource_classes_with_delete_recipe())
    return tuple(sorted(required - observed))


def _queue_manifest_dicts() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    cumulative = 0
    for manifest in STAGED_QUEUE_MANIFESTS:
        cumulative += manifest.planned_usd
        result.append(manifest.to_dict(cumulative))
    return result


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _true_fields(payload: Mapping[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(field for field in fields if payload.get(field) is not True)


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list | tuple):
        return set()
    return {item for item in value if isinstance(item, str) and item.strip()}


def _valid_sha256_shape(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if not value.startswith("sha256:") or len(value) != 71:
        return False
    digest = value.removeprefix("sha256:")
    return all(char in "0123456789abcdef" for char in digest)


def validate_operator_unlock(
    unlock: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Validate the future unlock object without enabling or executing AWS calls."""

    manifest = _mapping(unlock)
    required_stage_ids = set(stage_ids())
    required_template_ids = set(template_ids())
    approved_stage_ids = _string_set(manifest.get("approved_stage_ids"))
    approved_template_ids = _string_set(manifest.get("approved_template_ids"))

    missing_top_level_fields = tuple(
        field
        for field in REQUIRED_OPERATOR_UNLOCK_FIELDS
        if field not in manifest or manifest.get(field) in (None, "", ())
    )
    missing_string_fields = tuple(
        field
        for field in (
            "schema_version",
            "unlock_id",
            "created_at_utc",
            "expires_at_utc",
            "operator_name",
            "operator_email",
            "aws_account_id",
            "aws_profile",
            "aws_region",
            "billing_region",
        )
        if not _nonempty_string(manifest.get(field))
    )

    attestation_failures = {
        "budget_guard_attestation": _true_fields(
            _mapping(manifest.get("budget_guard_attestation")),
            BUDGET_GUARD_ATTESTATION_FIELDS,
        ),
        "tag_policy_attestation": _true_fields(
            _mapping(manifest.get("tag_policy_attestation")),
            TAG_POLICY_ATTESTATION_FIELDS,
        ),
        "teardown_recipe_attestation": _true_fields(
            _mapping(manifest.get("teardown_recipe_attestation")),
            TEARDOWN_RECIPE_ATTESTATION_FIELDS,
        ),
        "source_policy_attestation": _true_fields(
            _mapping(manifest.get("source_policy_attestation")),
            SOURCE_POLICY_ATTESTATION_FIELDS,
        ),
    }

    risk_acceptance = _mapping(manifest.get("risk_acceptance"))
    risk_acceptance_failures = _true_fields(
        risk_acceptance,
        (
            "operator_accepts_live_aws_mutation_templates",
            "target_19490_acknowledged",
            "rollback_owner_named",
        ),
    )
    if not _nonempty_string(risk_acceptance.get("live_run_window_utc")):
        risk_acceptance_failures = (*risk_acceptance_failures, "live_run_window_utc")

    incorrect_values: list[str] = []
    if manifest.get("schema_version") != "jpcite.aws_operator_unlock_manifest.p0.v1":
        incorrect_values.append("schema_version")
    if manifest.get("target_credit_spend_usd") != TARGET_CREDIT_SPEND_USD:
        incorrect_values.append("target_credit_spend_usd")
    if not _valid_sha256_shape(manifest.get("operator_signature_sha256")):
        incorrect_values.append("operator_signature_sha256")

    missing_stage_ids = tuple(sorted(required_stage_ids - approved_stage_ids))
    extra_stage_ids = tuple(sorted(approved_stage_ids - required_stage_ids))
    missing_template_ids = tuple(sorted(required_template_ids - approved_template_ids))
    extra_template_ids = tuple(sorted(approved_template_ids - required_template_ids))
    missing_recipe_classes = missing_teardown_recipe_resource_classes()

    complete = not (
        missing_top_level_fields
        or missing_string_fields
        or any(attestation_failures.values())
        or risk_acceptance_failures
        or incorrect_values
        or missing_stage_ids
        or extra_stage_ids
        or missing_template_ids
        or extra_template_ids
        or missing_recipe_classes
    )

    return {
        "complete": complete,
        "missing_top_level_fields": list(missing_top_level_fields),
        "missing_string_fields": list(missing_string_fields),
        "attestation_failures": {
            name: list(fields) for name, fields in attestation_failures.items()
        },
        "risk_acceptance_failures": list(risk_acceptance_failures),
        "incorrect_values": incorrect_values,
        "missing_stage_ids": list(missing_stage_ids),
        "extra_stage_ids": list(extra_stage_ids),
        "missing_template_ids": list(missing_template_ids),
        "extra_template_ids": list(extra_template_ids),
        "missing_teardown_recipe_resource_classes": list(missing_recipe_classes),
        "live_execution_allowed_after_validation": complete,
    }


def operator_unlock_complete(unlock: Mapping[str, Any] | None = None) -> bool:
    return bool(validate_operator_unlock(unlock)["complete"])


def build_operator_unlock_manifest_template() -> dict[str, object]:
    """Return an intentionally incomplete operator unlock template."""

    return {
        "schema_version": "jpcite.aws_operator_unlock_manifest.p0.v1",
        "unlock_id": "",
        "created_at_utc": "",
        "expires_at_utc": "",
        "operator_name": "",
        "operator_email": "",
        "aws_account_id": "",
        "aws_profile": "",
        "aws_region": "",
        "billing_region": "",
        "target_credit_spend_usd": TARGET_CREDIT_SPEND_USD,
        "approved_stage_ids": [],
        "approved_template_ids": [],
        "budget_guard_attestation": dict.fromkeys(BUDGET_GUARD_ATTESTATION_FIELDS, False),
        "tag_policy_attestation": dict.fromkeys(TAG_POLICY_ATTESTATION_FIELDS, False),
        "teardown_recipe_attestation": dict.fromkeys(TEARDOWN_RECIPE_ATTESTATION_FIELDS, False),
        "source_policy_attestation": dict.fromkeys(SOURCE_POLICY_ATTESTATION_FIELDS, False),
        "risk_acceptance": {
            "operator_accepts_live_aws_mutation_templates": False,
            "target_19490_acknowledged": False,
            "rollback_owner_named": False,
            "live_run_window_utc": "",
        },
        "operator_signature_sha256": "",
    }


def build_aws_execution_template_catalog(
    *,
    operator_unlock: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Return the offline AWS execution template catalog as JSON-ready data."""

    if planned_queue_target_usd() != TARGET_CREDIT_SPEND_USD:
        raise ValueError("planned staged queue target must remain 19490")
    missing_recipe_classes = missing_teardown_recipe_resource_classes()
    if missing_recipe_classes:
        raise ValueError(f"missing delete recipes for resource classes: {missing_recipe_classes!r}")

    unlock_validation = validate_operator_unlock(operator_unlock)
    live_execution_allowed = bool(unlock_validation["complete"])

    return {
        "schema_version": CATALOG_VERSION,
        "catalog_id": CATALOG_ID,
        "execution_mode": EXECUTION_MODE,
        "data_only": True,
        "no_aws_execution_performed": True,
        "network_calls_allowed": False,
        "subprocess_allowed": False,
        "live_execution_allowed_by_default": False,
        "live_execution_allowed": live_execution_allowed,
        "live_execution_gate_state": (
            LIVE_EXECUTION_UNLOCKED_STATE
            if live_execution_allowed
            else LIVE_EXECUTION_BLOCKED_STATE
        ),
        "target_credit_spend_usd": TARGET_CREDIT_SPEND_USD,
        "planned_target_sum_usd": planned_queue_target_usd(),
        "required_tag_keys": list(REQUIRED_TAG_KEYS),
        "tag_policy_requirements": [dict(item) for item in TAG_POLICY_REQUIREMENTS],
        "budget_guard_template_ids": list(BUDGET_GUARD_TEMPLATE_IDS),
        "budget_guard_templates": [
            template.to_dict()
            for template in EXECUTION_TEMPLATES
            if template.template_id in BUDGET_GUARD_TEMPLATE_IDS
        ],
        "execution_templates": [template.to_dict() for template in EXECUTION_TEMPLATES],
        "staged_queue_manifests": _queue_manifest_dicts(),
        "teardown_recipes": [recipe.to_dict() for recipe in TEARDOWN_RECIPES],
        "operator_unlock_manifest_schema": OPERATOR_UNLOCK_MANIFEST_SCHEMA,
        "operator_unlock_template": build_operator_unlock_manifest_template(),
        "operator_unlock_validation": unlock_validation,
        "safety_rules": [
            "catalog_is_data_only",
            "live_execution_disabled_by_default",
            "mutating_aws_operations_are_templates_not_commands",
            "operator_unlock_manifest_must_be_complete",
            "every_template_requires_required_tags",
            "every_resource_class_requires_delete_recipe",
            "staged_queue_target_sum_must_equal_19490",
        ],
    }
