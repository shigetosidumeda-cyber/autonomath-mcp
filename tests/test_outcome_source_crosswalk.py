from pathlib import Path

import pytest

from jpintel_mcp.agent_runtime.accounting_csv_profiles import build_accounting_csv_profiles
from jpintel_mcp.agent_runtime.algorithm_blueprints import ALGORITHM_BLUEPRINT_IDS
from jpintel_mcp.agent_runtime.aws_spend_program import STAGED_NON_MUTATING_BATCHES
from jpintel_mcp.agent_runtime.outcome_catalog import build_outcome_catalog
from jpintel_mcp.agent_runtime.outcome_source_crosswalk import (
    ACCOUNTING_CSV_PROFILE_KEYS,
    CATALOG_VERSION,
    INTERNAL_NON_DOMAIN_DEPENDENCY_TYPES,
    OutcomeSourceCrosswalkEntry,
    SourceCategoryLink,
    build_outcome_source_crosswalk,
    build_outcome_source_crosswalk_shape,
    get_outcome_source_crosswalk_entry,
    validate_outcome_source_crosswalk,
)
from jpintel_mcp.agent_runtime.public_source_domains import (
    build_public_source_domain_catalog,
)


def test_crosswalk_covers_every_outcome_catalog_slug_once() -> None:
    outcomes = build_outcome_catalog()
    crosswalk = build_outcome_source_crosswalk()
    shape = build_outcome_source_crosswalk_shape()

    outcome_slugs = [entry.deliverable_slug for entry in outcomes]
    crosswalk_slugs = [entry.deliverable_slug for entry in crosswalk]

    assert crosswalk_slugs == outcome_slugs
    assert len(crosswalk_slugs) == len(set(crosswalk_slugs))
    assert shape["schema_version"] == CATALOG_VERSION
    assert shape["covered_deliverable_slugs"] == outcome_slugs


def test_every_public_source_category_reference_exists() -> None:
    known_categories = {policy.source_category for policy in build_public_source_domain_catalog()}

    for entry in build_outcome_source_crosswalk():
        assert set(entry.public_source_categories) <= known_categories
        assert entry.source_category_links
        assert entry.public_source_categories
        assert entry.public_source_family_ids


def test_every_public_outcome_source_family_is_linked_to_a_category() -> None:
    outcomes = {entry.deliverable_slug: entry for entry in build_outcome_catalog()}

    for entry in build_outcome_source_crosswalk():
        outcome = outcomes[entry.deliverable_slug]
        expected_source_families = {
            dependency.source_family_id
            for dependency in outcome.source_dependencies
            if dependency.dependency_type not in INTERNAL_NON_DOMAIN_DEPENDENCY_TYPES
        }

        assert expected_source_families <= set(entry.public_source_family_ids)


def test_every_algorithm_blueprint_reference_exists() -> None:
    known_algorithm_ids = set(ALGORITHM_BLUEPRINT_IDS)

    for entry in build_outcome_source_crosswalk():
        assert set(entry.algorithm_blueprint_ids) <= known_algorithm_ids
        assert "evidence_join" in entry.algorithm_blueprint_ids
        assert "no_hit_semantics" in entry.algorithm_blueprint_ids


def test_csv_deliverables_map_to_accounting_csv_profiles() -> None:
    outcomes = {entry.deliverable_slug: entry for entry in build_outcome_catalog()}
    known_profile_keys = {profile.profile_key for profile in build_accounting_csv_profiles()}

    assert set(ACCOUNTING_CSV_PROFILE_KEYS) == known_profile_keys
    for entry in build_outcome_source_crosswalk():
        outcome = outcomes[entry.deliverable_slug]

        if outcome.requires_user_csv:
            assert set(entry.accounting_csv_profile_keys) == known_profile_keys
            assert entry.requires_csv_overlay is True
            assert {
                "csv_to_public_counterparty_matching",
                "subsidy_regulation_eligibility_triage_without_verdict",
            } & set(entry.algorithm_blueprint_ids)
        else:
            assert entry.accounting_csv_profile_keys == ()
            assert entry.requires_csv_overlay is False


def test_every_aws_stage_reference_exists_in_spend_program() -> None:
    known_stage_ids = {batch.stage_id for batch in STAGED_NON_MUTATING_BATCHES}

    for entry in build_outcome_source_crosswalk():
        assert set(entry.aws_stage_ids) <= known_stage_ids
        assert "stage_01_official_source_inventory" in entry.aws_stage_ids
        assert "stage_04_claim_graph_packet_factory" in entry.aws_stage_ids
        assert "stage_05_quality_eval_gap_review" in entry.aws_stage_ids
        assert "stage_06_release_artifact_packaging" in entry.aws_stage_ids


def test_crosswalk_lookup_and_validation_fail_closed() -> None:
    entry = get_outcome_source_crosswalk_entry("accounting-csv-public-counterparty-check")

    assert entry.accounting_csv_profile_keys == ACCOUNTING_CSV_PROFILE_KEYS
    assert "csv_to_public_counterparty_matching" in entry.algorithm_blueprint_ids
    assert "tax" in entry.public_source_categories

    with pytest.raises(ValueError, match="unknown outcome source crosswalk slug"):
        get_outcome_source_crosswalk_entry("missing-deliverable")

    with pytest.raises(ValueError, match="coverage mismatch"):
        validate_outcome_source_crosswalk(())

    with pytest.raises(ValueError, match="public_source_categories reference unknown values"):
        validate_outcome_source_crosswalk(
            (
                OutcomeSourceCrosswalkEntry(
                    deliverable_slug="company-public-baseline",
                    source_category_links=(
                        SourceCategoryLink(
                            source_category="unlisted_public_category",
                            source_family_ids=("gBizINFO", "nta_invoice", "edinet"),
                        ),
                    ),
                    algorithm_blueprint_ids=("evidence_join",),
                    aws_stage_ids=("stage_01_official_source_inventory",),
                ),
                *build_outcome_source_crosswalk()[1:],
            )
        )


def test_crosswalk_shape_is_deterministic_and_serializable() -> None:
    first = build_outcome_source_crosswalk_shape()
    second = build_outcome_source_crosswalk_shape()

    assert first == second
    assert first["algorithm_blueprint_ids"] == list(ALGORITHM_BLUEPRINT_IDS)
    assert first["accounting_csv_profile_keys"] == list(ACCOUNTING_CSV_PROFILE_KEYS)
    assert first["aws_stage_ids"] == [batch.stage_id for batch in STAGED_NON_MUTATING_BATCHES]
    assert all("public_source_categories" in entry for entry in first["crosswalk"])
    assert all("requires_csv_overlay" in entry for entry in first["crosswalk"])


def test_crosswalk_module_has_no_network_aws_or_io_dependencies() -> None:
    module_source = Path("src/jpintel_mcp/agent_runtime/outcome_source_crosswalk.py").read_text()
    forbidden_tokens = (
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "urllib",
        "socket",
        "subprocess",
        "import csv",
        "open(",
        "openai",
        "anthropic",
    )

    assert not any(token in module_source.lower() for token in forbidden_tokens)
