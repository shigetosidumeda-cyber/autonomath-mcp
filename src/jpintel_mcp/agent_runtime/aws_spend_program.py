"""Offline AWS credit spend program blueprint.

This module is a static planning contract only. It does not import AWS SDKs,
network clients, subprocess helpers, or any code path that can mutate live
infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

TARGET_CREDIT_SPEND_USD = 19490
TARGET_CREDIT_CONVERSION_USD = TARGET_CREDIT_SPEND_USD

PROGRAM_ID = "jpcite-aws-credit-spend-program-2026-05-15"
EXECUTION_MODE = "offline_non_mutating_blueprint"
LIVE_EXECUTION_BLOCKED_STATE = "AWS_BLOCKED_PRE_FLIGHT"
PREFLIGHT_EVIDENCE_READY_STATE = "AWS_PREFLIGHT_EVIDENCE_READY"

OFFICIAL_PUBLIC_DATA_COLLECTION = "official_public_data_collection"
ARTIFACT_GENERATION = "artifact_generation"
QUALITY_RELEASE_EVIDENCE = "quality_release_evidence"
TEARDOWN_ATTESTATION = "teardown_attestation"

REQUIRED_OUTPUT_CONNECTIONS = (
    OFFICIAL_PUBLIC_DATA_COLLECTION,
    ARTIFACT_GENERATION,
)

OFFICIAL_PUBLIC_SOURCE_FAMILIES = (
    "gBizINFO",
    "NTA invoice publication site",
    "e-Gov laws and public notices",
    "jGrants",
    "e-Stat",
    "EDINET",
    "courts.go.jp",
    "prefecture and municipality public pages",
)

REQUIRED_PREFLIGHT_EVIDENCE = (
    "aws_account_identity_read_only_report",
    "credit_balance_and_expiration_report",
    "budget_cash_bill_guard_report",
    "service_quota_and_credit_eligibility_report",
    "tagging_policy_and_resource_inventory_report",
    "source_terms_public_access_report",
    "teardown_recipe_review_report",
    "artifact_manifest_schema_report",
)

REQUIRED_HARD_STOPS = (
    "preflight_evidence_missing",
    "live_execution_unlock_missing",
    "budget_cash_guard_missing",
    "credit_eligibility_or_service_sku_uncertain",
    "stage_hard_stop_would_exceed_target",
    "planned_target_sum_not_19490",
    "source_terms_or_robots_unknown",
    "private_or_nonpublic_data_detected",
    "public_source_receipts_missing",
    "claim_without_source_receipt",
    "artifact_manifest_missing_or_unverifiable",
    "missing_teardown_recipe_or_attestation",
)

TEARDOWN_ATTESTATIONS = (
    {
        "attestation_id": "delete_recipe_present_for_every_resource_class",
        "required_artifact": "teardown/delete_recipe_matrix.json",
        "required_before_stage": "stage_01_official_source_inventory",
    },
    {
        "attestation_id": "tagged_resource_inventory_empty_or_explained",
        "required_artifact": "teardown/tagged_resource_inventory_after_run.json",
        "required_before_stage": "stage_07_teardown_attestation",
    },
    {
        "attestation_id": "post_teardown_cost_meter_reviewed",
        "required_artifact": "teardown/post_teardown_cost_meter_review.json",
        "required_before_stage": "program_closeout",
    },
)


@dataclass(frozen=True)
class SpendEnvelope:
    """One batch spend envelope, expressed in integer USD."""

    planned_usd: int
    soft_stop_usd: int
    hard_stop_usd: int
    max_single_work_item_usd: int

    def __post_init__(self) -> None:
        if self.planned_usd < 0:
            raise ValueError("planned_usd must be non-negative")
        if not 0 <= self.soft_stop_usd <= self.hard_stop_usd:
            raise ValueError("soft_stop_usd must be between 0 and hard_stop_usd")
        if self.hard_stop_usd != self.planned_usd:
            raise ValueError("hard_stop_usd must equal planned_usd for no-overrun")
        if not 0 <= self.max_single_work_item_usd <= self.hard_stop_usd:
            raise ValueError("max_single_work_item_usd must fit inside hard_stop_usd")

    def to_dict(self) -> dict[str, int]:
        return {
            "planned_usd": self.planned_usd,
            "soft_stop_usd": self.soft_stop_usd,
            "hard_stop_usd": self.hard_stop_usd,
            "max_single_work_item_usd": self.max_single_work_item_usd,
        }


@dataclass(frozen=True)
class DataAssetOutput:
    """Planned data artifact emitted by a non-mutating batch."""

    asset_id: str
    path: str
    connection: str
    source_scope: str
    artifact_kind: str
    collection_mode: str = "offline_manifest_only"

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise ValueError("asset_id is required")
        if self.connection not in {
            OFFICIAL_PUBLIC_DATA_COLLECTION,
            ARTIFACT_GENERATION,
            QUALITY_RELEASE_EVIDENCE,
            TEARDOWN_ATTESTATION,
        }:
            raise ValueError(f"unknown output connection: {self.connection}")
        if "public" not in self.source_scope:
            raise ValueError("source_scope must be public-source compatible")

    def to_dict(self) -> dict[str, str]:
        return {
            "asset_id": self.asset_id,
            "path": self.path,
            "connection": self.connection,
            "source_scope": self.source_scope,
            "artifact_kind": self.artifact_kind,
            "collection_mode": self.collection_mode,
        }


@dataclass(frozen=True)
class SpendBatch:
    """A non-mutating staged execution batch."""

    stage_id: str
    stage_name: str
    spend_envelope: SpendEnvelope
    data_asset_outputs: tuple[DataAssetOutput, ...]
    stop_conditions: tuple[str, ...]
    teardown_attestations: tuple[str, ...] = ()
    mutates_live_aws: bool = False
    aws_calls_allowed: bool = False
    subprocess_allowed: bool = False
    network_calls_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.stage_id.strip() or not self.stage_name.strip():
            raise ValueError("stage_id and stage_name are required")
        if not self.data_asset_outputs:
            raise ValueError("each stage must define data asset outputs")
        if not self.stop_conditions:
            raise ValueError("each stage must define stop conditions")
        if self.mutates_live_aws:
            raise ValueError("spend batches must be non-mutating")
        if self.aws_calls_allowed or self.subprocess_allowed or self.network_calls_allowed:
            raise ValueError("spend batches must remain offline-only")

    def to_dict(self, cumulative_planned_usd: int) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "stage_name": self.stage_name,
            "execution_mode": EXECUTION_MODE,
            "mutates_live_aws": self.mutates_live_aws,
            "aws_calls_allowed": self.aws_calls_allowed,
            "subprocess_allowed": self.subprocess_allowed,
            "network_calls_allowed": self.network_calls_allowed,
            "spend_envelope": self.spend_envelope.to_dict(),
            "cumulative_planned_usd": cumulative_planned_usd,
            "remaining_target_after_stage_usd": (TARGET_CREDIT_SPEND_USD - cumulative_planned_usd),
            "data_asset_outputs": [output.to_dict() for output in self.data_asset_outputs],
            "stop_conditions": list(self.stop_conditions),
            "teardown_attestations": list(self.teardown_attestations),
        }


def _output(
    asset_id: str,
    path: str,
    connection: str,
    artifact_kind: str,
    *,
    source_scope: str = "official_public_sources_only",
    collection_mode: str = "offline_manifest_only",
) -> DataAssetOutput:
    return DataAssetOutput(
        asset_id=asset_id,
        path=path,
        connection=connection,
        source_scope=source_scope,
        artifact_kind=artifact_kind,
        collection_mode=collection_mode,
    )


STAGED_NON_MUTATING_BATCHES = (
    SpendBatch(
        stage_id="stage_00_preflight_evidence_lock",
        stage_name="Preflight evidence lock",
        spend_envelope=SpendEnvelope(0, 0, 0, 0),
        data_asset_outputs=(
            _output(
                "preflight_evidence_scorecard",
                "aws_spend_program/preflight/evidence_scorecard.json",
                QUALITY_RELEASE_EVIDENCE,
                "gate_scorecard",
            ),
        ),
        stop_conditions=(
            "preflight_evidence_missing",
            "live_execution_unlock_missing",
            "budget_cash_guard_missing",
            "credit_eligibility_or_service_sku_uncertain",
        ),
        teardown_attestations=("delete_recipe_present_for_every_resource_class",),
    ),
    SpendBatch(
        stage_id="stage_01_official_source_inventory",
        stage_name="Official source inventory",
        spend_envelope=SpendEnvelope(2140, 1925, 2140, 120),
        data_asset_outputs=(
            _output(
                "official_source_registry",
                "data/public_sources/official_source_registry.json",
                OFFICIAL_PUBLIC_DATA_COLLECTION,
                "source_registry",
            ),
            _output(
                "source_terms_receipt_register",
                "data/public_sources/source_terms_receipts.jsonl",
                OFFICIAL_PUBLIC_DATA_COLLECTION,
                "policy_receipt_ledger",
            ),
        ),
        stop_conditions=(
            "source_terms_or_robots_unknown",
            "private_or_nonpublic_data_detected",
            "stage_hard_stop_would_exceed_target",
        ),
        teardown_attestations=("delete_recipe_present_for_every_resource_class",),
    ),
    SpendBatch(
        stage_id="stage_02_public_collection_capture",
        stage_name="Public collection capture",
        spend_envelope=SpendEnvelope(4360, 3920, 4360, 160),
        data_asset_outputs=(
            _output(
                "public_collection_queue",
                "data/public_sources/public_collection_queue.jsonl",
                OFFICIAL_PUBLIC_DATA_COLLECTION,
                "collection_queue",
                collection_mode="offline_plan_for_public_capture",
            ),
            _output(
                "source_receipt_ledger",
                "artifacts/source_receipts/source_receipt_ledger.jsonl",
                ARTIFACT_GENERATION,
                "source_receipt_ledger",
            ),
        ),
        stop_conditions=(
            "public_source_receipts_missing",
            "private_or_nonpublic_data_detected",
            "stage_hard_stop_would_exceed_target",
        ),
        teardown_attestations=("delete_recipe_present_for_every_resource_class",),
    ),
    SpendBatch(
        stage_id="stage_03_ocr_normalization_search_build",
        stage_name="OCR normalization and search build",
        spend_envelope=SpendEnvelope(5180, 4660, 5180, 220),
        data_asset_outputs=(
            _output(
                "normalized_public_text_shards",
                "artifacts/normalized_public_text/shards.manifest.json",
                ARTIFACT_GENERATION,
                "normalized_text_manifest",
            ),
            _output(
                "public_search_index_manifest",
                "artifacts/search/public_search_index_manifest.json",
                ARTIFACT_GENERATION,
                "index_manifest",
            ),
        ),
        stop_conditions=(
            "credit_eligibility_or_service_sku_uncertain",
            "private_or_nonpublic_data_detected",
            "stage_hard_stop_would_exceed_target",
        ),
        teardown_attestations=("delete_recipe_present_for_every_resource_class",),
    ),
    SpendBatch(
        stage_id="stage_04_claim_graph_packet_factory",
        stage_name="Claim graph and packet factory",
        spend_envelope=SpendEnvelope(3720, 3345, 3720, 180),
        data_asset_outputs=(
            _output(
                "claim_graph",
                "artifacts/claim_graph/claim_graph.jsonl",
                ARTIFACT_GENERATION,
                "claim_graph",
            ),
            _output(
                "evidence_packet_manifest",
                "artifacts/evidence_packets/packet_manifest.json",
                ARTIFACT_GENERATION,
                "accepted_artifact_manifest",
            ),
        ),
        stop_conditions=(
            "claim_without_source_receipt",
            "artifact_manifest_missing_or_unverifiable",
            "stage_hard_stop_would_exceed_target",
        ),
        teardown_attestations=("delete_recipe_present_for_every_resource_class",),
    ),
    SpendBatch(
        stage_id="stage_05_quality_eval_gap_review",
        stage_name="Quality evaluation and gap review",
        spend_envelope=SpendEnvelope(2190, 1970, 2190, 90),
        data_asset_outputs=(
            _output(
                "geo_eval_report",
                "artifacts/eval/geo_eval_report.json",
                QUALITY_RELEASE_EVIDENCE,
                "quality_report",
            ),
            _output(
                "known_gap_register",
                "artifacts/evidence_packets/known_gap_register.json",
                ARTIFACT_GENERATION,
                "known_gap_register",
            ),
        ),
        stop_conditions=(
            "planned_target_sum_not_19490",
            "artifact_manifest_missing_or_unverifiable",
            "claim_without_source_receipt",
            "stage_hard_stop_would_exceed_target",
        ),
        teardown_attestations=("delete_recipe_present_for_every_resource_class",),
    ),
    SpendBatch(
        stage_id="stage_06_release_artifact_packaging",
        stage_name="Release artifact packaging",
        spend_envelope=SpendEnvelope(1400, 1260, 1400, 70),
        data_asset_outputs=(
            _output(
                "public_packet_pages",
                "site/releases/aws_spend_program/public_packets_manifest.json",
                ARTIFACT_GENERATION,
                "public_page_manifest",
            ),
            _output(
                "release_checksums",
                "site/releases/aws_spend_program/checksums.sha256",
                QUALITY_RELEASE_EVIDENCE,
                "checksum_manifest",
            ),
        ),
        stop_conditions=(
            "artifact_manifest_missing_or_unverifiable",
            "public_source_receipts_missing",
            "stage_hard_stop_would_exceed_target",
        ),
        teardown_attestations=("delete_recipe_present_for_every_resource_class",),
    ),
    SpendBatch(
        stage_id="stage_07_teardown_attestation",
        stage_name="Teardown attestation",
        spend_envelope=SpendEnvelope(500, 450, 500, 50),
        data_asset_outputs=(
            _output(
                "teardown_attestation_bundle",
                "teardown/teardown_attestation_bundle.json",
                TEARDOWN_ATTESTATION,
                "teardown_evidence_bundle",
            ),
            _output(
                "post_teardown_cost_review",
                "teardown/post_teardown_cost_meter_review.json",
                TEARDOWN_ATTESTATION,
                "cost_review",
            ),
        ),
        stop_conditions=(
            "missing_teardown_recipe_or_attestation",
            "stage_hard_stop_would_exceed_target",
            "budget_cash_guard_missing",
        ),
        teardown_attestations=(
            "delete_recipe_present_for_every_resource_class",
            "tagged_resource_inventory_empty_or_explained",
            "post_teardown_cost_meter_reviewed",
        ),
    ),
)


def planned_target_sum_usd(
    batches: tuple[SpendBatch, ...] = STAGED_NON_MUTATING_BATCHES,
) -> int:
    return sum(batch.spend_envelope.planned_usd for batch in batches)


def total_hard_stop_usd(
    batches: tuple[SpendBatch, ...] = STAGED_NON_MUTATING_BATCHES,
) -> int:
    return sum(batch.spend_envelope.hard_stop_usd for batch in batches)


def hard_stop_overrun_detected(
    batches: tuple[SpendBatch, ...] = STAGED_NON_MUTATING_BATCHES,
) -> bool:
    running_total = 0
    for batch in batches:
        running_total += batch.spend_envelope.hard_stop_usd
        if running_total > TARGET_CREDIT_SPEND_USD:
            return True
    return total_hard_stop_usd(batches) > TARGET_CREDIT_SPEND_USD


def _validate_batches(batches: tuple[SpendBatch, ...]) -> None:
    if planned_target_sum_usd(batches) != TARGET_CREDIT_SPEND_USD:
        raise ValueError("planned target sum must equal 19490")
    if hard_stop_overrun_detected(batches):
        raise ValueError("hard stops must not overrun the 19490 target")
    covered_stop_ids = {condition for batch in batches for condition in batch.stop_conditions}
    missing_required = tuple(
        stop_id for stop_id in REQUIRED_HARD_STOPS if stop_id not in covered_stop_ids
    )
    if missing_required:
        raise ValueError(f"missing required hard stops: {missing_required!r}")


def normalize_preflight_evidence(
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, bool]:
    observed = evidence or {}
    return {
        evidence_id: observed.get(evidence_id) is True
        for evidence_id in REQUIRED_PREFLIGHT_EVIDENCE
    }


def missing_preflight_evidence(
    evidence: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    normalized = normalize_preflight_evidence(evidence)
    return tuple(evidence_id for evidence_id, present in normalized.items() if not present)


def preflight_evidence_passes(evidence: Mapping[str, Any] | None = None) -> bool:
    return not missing_preflight_evidence(evidence)


def output_connection_ids(
    batches: tuple[SpendBatch, ...] = STAGED_NON_MUTATING_BATCHES,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(output.connection for batch in batches for output in batch.data_asset_outputs)
    )


def _batch_dicts(batches: tuple[SpendBatch, ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    cumulative = 0
    for batch in batches:
        cumulative += batch.spend_envelope.planned_usd
        result.append(batch.to_dict(cumulative))
    return result


def _hard_stop_rule_dicts() -> list[dict[str, str]]:
    return [
        {
            "rule_id": rule_id,
            "severity": "block",
            "action": "stop_before_live_execution_or_next_batch",
        }
        for rule_id in REQUIRED_HARD_STOPS
    ]


def build_aws_spend_program(
    *,
    preflight_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the offline spend program blueprint as JSON-ready data."""

    batches = STAGED_NON_MUTATING_BATCHES
    _validate_batches(batches)

    normalized_evidence = normalize_preflight_evidence(preflight_evidence)
    missing_evidence = missing_preflight_evidence(preflight_evidence)
    evidence_passed = not missing_evidence

    return {
        "schema_version": "jpcite.aws_spend_program.p0.v1",
        "program_id": PROGRAM_ID,
        "execution_mode": EXECUTION_MODE,
        "target_credit_spend_usd": TARGET_CREDIT_SPEND_USD,
        "target_credit_conversion_usd": TARGET_CREDIT_CONVERSION_USD,
        "planned_target_sum_usd": planned_target_sum_usd(batches),
        "total_hard_stop_usd": total_hard_stop_usd(batches),
        "target_sum_rule": "sum(batch.spend_envelope.planned_usd) == 19490",
        "no_overrun_rule": ("stop before a batch when cumulative hard_stop_usd would exceed 19490"),
        "live_execution_allowed": False,
        "live_execution_gate_state": (
            PREFLIGHT_EVIDENCE_READY_STATE if evidence_passed else LIVE_EXECUTION_BLOCKED_STATE
        ),
        "live_execution_rule": (
            "live execution remains blocked until every required preflight "
            "evidence item passes and a separate operator unlock is recorded "
            "outside this offline blueprint"
        ),
        "preflight_evidence_passed": evidence_passed,
        "preflight_evidence": {
            "required": list(REQUIRED_PREFLIGHT_EVIDENCE),
            "observed": normalized_evidence,
            "missing": list(missing_evidence),
        },
        "hard_stop_rules": _hard_stop_rule_dicts(),
        "official_public_source_families": list(OFFICIAL_PUBLIC_SOURCE_FAMILIES),
        "required_output_connections": list(REQUIRED_OUTPUT_CONNECTIONS),
        "data_asset_output_connections": list(output_connection_ids(batches)),
        "teardown_attestations": [dict(item) for item in TEARDOWN_ATTESTATIONS],
        "batches": _batch_dicts(batches),
    }


def build_spend_program_blueprint(
    *,
    preflight_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Alias with a shorter name for callers that do not need AWS in the symbol."""

    return build_aws_spend_program(preflight_evidence=preflight_evidence)
