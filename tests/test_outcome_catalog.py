from pathlib import Path

import pytest

from jpintel_mcp.agent_runtime.outcome_catalog import (
    CATALOG_VERSION,
    NO_HIT_SEMANTICS,
    OutcomeCatalogEntry,
    SourceDependency,
    build_outcome_catalog,
    build_outcome_catalog_shape,
    get_outcome_by_slug,
    high_value_deliverables,
    validate_outcome_catalog,
)

EXPECTED_SLUGS = [
    "company-public-baseline",
    "invoice-registrant-public-check",
    "subsidy-grant-candidate-pack",
    "law-regulation-change-watch",
    "local-government-permit-obligation-map",
    "court-enforcement-citation-pack",
    "public-statistics-market-context",
    "client-monthly-public-watchlist",
    "accounting-csv-public-counterparty-check",
    "cashbook-csv-subsidy-fit-screen",
    "source-receipt-ledger",
    "evidence-answer-citation-pack",
    "foreign-investor-japan-public-entry-brief",
    "healthcare-regulatory-public-check",
]


def test_outcome_catalog_has_deterministic_agent_facing_shape() -> None:
    catalog = build_outcome_catalog()
    shape = build_outcome_catalog_shape()

    assert [entry.deliverable_slug for entry in catalog] == EXPECTED_SLUGS
    assert shape["schema_version"] == CATALOG_VERSION
    assert shape["no_hit_semantics"] == NO_HIT_SEMANTICS
    assert [entry["deliverable_slug"] for entry in shape["deliverables"]] == EXPECTED_SLUGS
    assert all(entry.precomputed_output is True for entry in catalog)
    assert all(entry.agent_facing is True for entry in catalog)


def test_deliverable_slugs_are_unique_and_slug_safe() -> None:
    catalog = build_outcome_catalog()
    slugs = [entry.deliverable_slug for entry in catalog]

    assert len(slugs) == len(set(slugs))
    assert all(slug == slug.lower() for slug in slugs)
    assert all(set(slug) <= set("abcdefghijklmnopqrstuvwxyz0123456789-") for slug in slugs)

    with pytest.raises(ValueError, match="duplicate deliverable slugs"):
        validate_outcome_catalog((catalog[0], catalog[0]))


def test_no_request_time_llm_or_live_runtime_dependency() -> None:
    catalog = build_outcome_catalog()
    shape = build_outcome_catalog_shape()

    assert shape["request_time_llm_dependency"] is False
    assert shape["live_network_dependency"] is False
    assert shape["live_aws_dependency"] is False
    assert shape["api_wiring_required"] is False
    assert all(entry.request_time_llm_dependency is False for entry in catalog)
    assert all(entry.live_network_dependency is False for entry in catalog)
    assert all(entry.live_aws_dependency is False for entry in catalog)
    assert all(entry.api_wiring_required is False for entry in catalog)

    module_source = Path("src/jpintel_mcp/agent_runtime/outcome_catalog.py").read_text()
    forbidden_tokens = (
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "urllib",
        "openai",
        "anthropic",
        "bedrock",
        "import csv",
        "open(",
    )
    assert not any(token in module_source for token in forbidden_tokens)


def test_every_high_value_deliverable_has_sources_and_billing_posture() -> None:
    high_value = high_value_deliverables()

    assert {entry.deliverable_slug for entry in high_value} == set(EXPECTED_SLUGS)
    for entry in high_value:
        assert entry.source_dependencies
        assert entry.evidence_dependency_types
        assert entry.pricing_posture.startswith("accepted_artifact")
        assert entry.billing_posture in {
            "billable_after_user_accepts_artifact",
            "billable_after_csv_consent_and_artifact_acceptance",
        }


def test_japanese_public_official_info_use_cases_are_represented() -> None:
    official_info_entries = [
        entry
        for entry in build_outcome_catalog()
        if "japanese_public_official_info" in entry.use_case_tags
    ]
    represented_tags = {tag for entry in official_info_entries for tag in entry.use_case_tags}
    source_families = {
        dependency.source_family_id
        for entry in official_info_entries
        for dependency in entry.source_dependencies
    }

    assert official_info_entries
    assert represented_tags >= {
        "company_registry",
        "invoice_registry",
        "subsidy_grants",
        "law_regulation",
        "local_government",
        "court_enforcement",
        "public_statistics",
        "tax_accounting_csv_overlay",
    }
    assert source_families >= {
        "gBizINFO",
        "nta_invoice",
        "edinet",
        "egov_law",
        "jgrants",
        "estat",
        "local_government_notice",
        "courts_jp",
        "mhlw_notice",
    }


def test_cached_public_sources_vs_user_csv_boundary_is_explicit() -> None:
    catalog = build_outcome_catalog()
    public_only = [entry for entry in catalog if not entry.requires_user_csv]
    csv_required = [entry for entry in catalog if entry.requires_user_csv]

    assert {entry.deliverable_slug for entry in csv_required} == {
        "accounting-csv-public-counterparty-check",
        "cashbook-csv-subsidy-fit-screen",
    }
    assert all(
        entry.input_requirement == "cached_official_public_only"
        and entry.cached_official_public_sources_sufficient is True
        for entry in public_only
    )
    assert all(
        entry.input_requirement == "cached_public_plus_user_csv"
        and entry.cached_official_public_sources_sufficient is False
        for entry in csv_required
    )
    assert all(
        not any(dependency.user_csv for dependency in entry.source_dependencies)
        for entry in public_only
    )
    assert all(
        any(
            dependency.dependency_type == "tenant_private_csv_overlay"
            and dependency.user_csv is True
            for dependency in entry.source_dependencies
        )
        for entry in csv_required
    )


def test_catalog_lookup_and_validation_fail_closed() -> None:
    entry = get_outcome_by_slug("law-regulation-change-watch")

    assert entry.outcome_contract_id == "regulation_change_watch"
    assert "official_law_regulation" in entry.evidence_dependency_types

    with pytest.raises(ValueError, match="unknown outcome deliverable slug"):
        get_outcome_by_slug("missing-deliverable")
    with pytest.raises(ValueError, match="request-time LLM dependency"):
        OutcomeCatalogEntry(
            deliverable_slug="bad-llm-deliverable",
            display_name="Bad LLM deliverable",
            outcome_contract_id="bad_llm_deliverable",
            user_segments=("agent_builder",),
            high_value=True,
            use_case_tags=("japanese_public_official_info",),
            source_dependencies=(
                SourceDependency(
                    dependency_type="official_law_regulation",
                    source_family_id="egov_law",
                    source_role="law text",
                    cached_official_or_public=True,
                ),
            ),
            pricing_posture="accepted_artifact_standard",
            billing_posture="billable_after_user_accepts_artifact",
            input_requirement="cached_official_public_only",
            cached_official_public_sources_sufficient=True,
            requires_user_csv=False,
            request_time_llm_dependency=True,
        )
