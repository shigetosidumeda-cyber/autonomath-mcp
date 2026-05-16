from __future__ import annotations

import json
from pathlib import Path

import pytest

from jpintel_mcp.agent_runtime.defaults import CAPSULE_ID, OUTCOME_CONTRACT_PACKET_IDS
from jpintel_mcp.agent_runtime.outcome_catalog import build_outcome_catalog
from jpintel_mcp.agent_runtime.packet_skeletons import (
    BILLING_CONTRACT_ID,
    NO_HIT_SEMANTICS,
    P0_PACKET_SKELETON_DEFERRED_REASONS,
    P0_PACKET_SKELETON_IDS,
    build_packet_skeleton_catalog,
    get_packet_skeleton,
)

REQUIRED_SKELETON_KEYS = {
    "claims",
    "source_receipts",
    "known_gaps",
    "no_hit_semantics",
    "billing_contract_id",
}


def test_p0_packet_skeleton_catalog_tracks_outcome_catalog_or_deferred_reason() -> None:
    skeleton_catalog = build_packet_skeleton_catalog()
    outcome_catalog = build_outcome_catalog()
    outcome_ids = tuple(entry.outcome_contract_id for entry in outcome_catalog)
    deferred_ids = set(P0_PACKET_SKELETON_DEFERRED_REASONS)
    skeleton_ids = set(skeleton_catalog)

    assert tuple(skeleton_catalog) == P0_PACKET_SKELETON_IDS
    assert skeleton_ids | deferred_ids == set(outcome_ids)
    assert skeleton_ids.isdisjoint(deferred_ids)
    assert deferred_ids <= set(outcome_ids)
    assert (
        tuple(outcome_id for outcome_id in outcome_ids if outcome_id not in deferred_ids)
        == P0_PACKET_SKELETON_IDS
    )
    assert P0_PACKET_SKELETON_DEFERRED_REASONS == {}


@pytest.mark.parametrize("outcome_contract_id", P0_PACKET_SKELETON_IDS)
def test_each_p0_packet_skeleton_has_required_contract_surface(outcome_contract_id: str) -> None:
    skeleton = get_packet_skeleton(outcome_contract_id)

    assert set(skeleton) >= REQUIRED_SKELETON_KEYS
    assert skeleton["schema_version"] == "jpcite.packet_skeleton.p0.v1"
    assert skeleton["capsule_id"] == CAPSULE_ID
    assert skeleton["outcome_contract_id"] == outcome_contract_id
    assert skeleton["billing_contract_id"] == BILLING_CONTRACT_ID
    assert skeleton["packet_ids"] == list(OUTCOME_CONTRACT_PACKET_IDS[outcome_contract_id])
    assert skeleton["claims"]
    assert skeleton["source_receipts"]
    assert skeleton["known_gaps"]
    assert skeleton["no_hit_semantics"] == {
        "rule": NO_HIT_SEMANTICS,
        "absence_claim_enabled": False,
        "wording": "No hit is reported as an observed search result only, not as proof of absence.",
    }

    receipt_ids = {receipt["receipt_id"] for receipt in skeleton["source_receipts"]}
    assert all(claim["visibility"] == "public" for claim in skeleton["claims"])
    assert all(set(claim["receipt_ids"]) <= receipt_ids for claim in skeleton["claims"])


def test_packet_skeleton_receipts_cover_public_outcome_dependencies() -> None:
    outcomes = {entry.outcome_contract_id: entry for entry in build_outcome_catalog()}

    for outcome_contract_id in P0_PACKET_SKELETON_IDS:
        entry = outcomes[outcome_contract_id]
        skeleton = get_packet_skeleton(outcome_contract_id)
        receipt_families = {receipt["source_family_id"] for receipt in skeleton["source_receipts"]}
        public_dependency_families = {
            dependency.source_family_id
            for dependency in entry.source_dependencies
            if not dependency.user_csv
        }
        tenant_csv_families = {
            dependency.source_family_id
            for dependency in entry.source_dependencies
            if dependency.user_csv
        }

        assert public_dependency_families <= receipt_families
        assert receipt_families.isdisjoint(tenant_csv_families)


@pytest.mark.parametrize(
    "outcome_contract_id",
    [
        "invoice_registrant_public_check",
        "local_government_permit_obligation_map",
        "court_enforcement_citation_pack",
        "public_statistics_market_context",
        "cashbook_csv_subsidy_fit_screen",
        "foreign_investor_japan_public_entry_brief",
        "healthcare_regulatory_public_check",
    ],
)
def test_new_catalog_skeletons_expose_receipts_gaps_and_no_hit_semantics(
    outcome_contract_id: str,
) -> None:
    skeleton = get_packet_skeleton(outcome_contract_id)

    assert skeleton["source_receipts"]
    assert skeleton["known_gaps"]
    assert skeleton["no_hit_semantics"]["rule"] == NO_HIT_SEMANTICS
    assert skeleton["no_hit_semantics"]["absence_claim_enabled"] is False


def test_p0_packet_skeletons_are_deterministic_and_mutation_isolated() -> None:
    first = build_packet_skeleton_catalog()
    second = build_packet_skeleton_catalog()

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    first["company_public_baseline"]["claims"][0]["text"] = "mutated"
    fresh = get_packet_skeleton("company_public_baseline")

    assert fresh["claims"][0]["text"] == "Public-source company name placeholder."


def test_unknown_packet_skeleton_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown P0 packet skeleton"):
        get_packet_skeleton("not_a_p0_packet")


@pytest.mark.parametrize(
    ("outcome_contract_id", "summary_key", "public_source_families"),
    [
        ("csv_overlay_public_check", "csv_summary", {"nta_invoice", "gBizINFO"}),
        ("cashbook_csv_subsidy_fit_screen", "cashbook_summary", {"jgrants", "sme_agency"}),
    ],
)
def test_csv_skeletons_keep_private_facts_non_public(
    outcome_contract_id: str,
    summary_key: str,
    public_source_families: set[str],
) -> None:
    skeleton = get_packet_skeleton(outcome_contract_id)
    private_overlay = skeleton["private_overlay"]
    outcome = {entry.outcome_contract_id: entry for entry in build_outcome_catalog()}[
        outcome_contract_id
    ]
    tenant_csv_families = {
        dependency.source_family_id
        for dependency in outcome.source_dependencies
        if dependency.user_csv
    }

    assert private_overlay["tenant_scope"] == "tenant_private"
    assert private_overlay["redaction_policy"] == "hash_only_private_facts"
    assert private_overlay["raw_csv_retained"] is False
    assert private_overlay["raw_csv_logged"] is False
    assert private_overlay["raw_csv_sent_to_aws"] is False
    assert private_overlay["public_surface_export_allowed"] is False
    assert private_overlay["source_receipt_compatible"] is False

    for private_fact in private_overlay["private_fact_examples"]:
        assert set(private_fact) == {
            "record_id",
            "derived_fact_type",
            "value_fingerprint_hash",
            "public_claim_support",
            "source_receipt_compatible",
            "raw_value_retained",
        }
        assert private_fact["value_fingerprint_hash"].startswith("sha256:")
        assert private_fact["public_claim_support"] is False
        assert private_fact["source_receipt_compatible"] is False
        assert private_fact["raw_value_retained"] is False

    assert all(claim["visibility"] == "public" for claim in skeleton["claims"])
    assert all(
        receipt["source_family_id"] in public_source_families
        for receipt in skeleton["source_receipts"]
    )
    assert all(
        receipt["source_family_id"] not in tenant_csv_families
        for receipt in skeleton["source_receipts"]
    )
    assert skeleton[summary_key]["tenant_scope"] == "tenant_private"
    assert skeleton[summary_key]["export_state"] == "redacted_summary_only"
    assert skeleton[summary_key]["raw_row_values_included"] is False
    assert "private_overlay" not in json.dumps(skeleton["claims"], sort_keys=True)
    assert "value_fingerprint_hash" not in json.dumps(skeleton["source_receipts"], sort_keys=True)


def test_application_strategy_skeleton_is_candidate_only_and_review_gated() -> None:
    skeleton = get_packet_skeleton("application_strategy")

    assert skeleton["quality"]["human_review_required"] is True
    assert "professional_interpretation_required" in skeleton["quality"]["human_review_reasons"]
    assert (
        skeleton["strategy_sections"]["ranked_candidates"][0]["recommendation_state"]
        == "candidate_for_review"
    )
    assert skeleton["strategy_sections"]["ranked_candidates"][0]["not_a_verdict"] is True
    assert "application_eligibility_verdict" in skeleton["strategy_sections"]["do_not_claim"]
    assert {gap["gap_id"] for gap in skeleton["known_gaps"]} >= {
        "gap_private_input_unverified",
        "gap_compatibility_unknown",
    }


def test_client_monthly_review_skeleton_keeps_private_notes_out_of_public_claims() -> None:
    skeleton = get_packet_skeleton("client_monthly_review")

    assert skeleton["quality"]["human_review_required"] is True
    assert skeleton["monthly_review"]["review_month"] == "2026-05"
    assert (
        skeleton["monthly_review"]["copy_paste_client_messages"][0]["requires_human_review"] is True
    )
    assert {gap["gap_id"] for gap in skeleton["known_gaps"]} >= {
        "gap_private_client_notes_minimized",
        "gap_current_month_freshness",
    }

    public_claims = json.dumps(skeleton["claims"], sort_keys=True)
    assert "private_client_notes" not in public_claims
    assert "copy_paste_client_messages" not in public_claims


def test_packet_skeleton_module_has_no_network_llm_or_file_runtime_dependencies() -> None:
    module_source = Path("src/jpintel_mcp/agent_runtime/packet_skeletons.py").read_text()
    forbidden_tokens = (
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "urllib",
        "openai",
        "anthropic",
        "import csv",
        "open(",
    )

    assert not any(token in module_source for token in forbidden_tokens)
