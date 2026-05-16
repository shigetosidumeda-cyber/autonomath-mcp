from __future__ import annotations

from copy import deepcopy

import pytest

from jpintel_mcp.agent_runtime.packet_skeletons import (
    P0_PACKET_SKELETON_IDS,
    get_packet_skeleton,
)
from jpintel_mcp.agent_runtime.source_receipts import (
    DEFAULT_OBSERVED_AT,
    REQUIRED_CLAIM_FIELDS,
    REQUIRED_GAP_FIELDS,
    REQUIRED_RECEIPT_FIELDS,
    SOURCE_RECEIPT_LEDGER_SCHEMA_VERSION,
    assert_claim_receipt_links,
    build_source_receipt_ledger,
    known_gap,
    public_claim,
    source_receipt,
    source_receipt_contract_issues,
    source_receipt_contract_passed,
)


@pytest.mark.parametrize("outcome_contract_id", P0_PACKET_SKELETON_IDS)
def test_all_p0_skeleton_claims_have_receipts_or_known_gap(
    outcome_contract_id: str,
) -> None:
    skeleton = get_packet_skeleton(outcome_contract_id)

    ledger = build_source_receipt_ledger(skeleton)

    assert ledger["schema_version"] == SOURCE_RECEIPT_LEDGER_SCHEMA_VERSION
    assert ledger["outcome_contract_id"] == outcome_contract_id
    assert ledger["claim_count"] == len(skeleton["claims"])
    assert ledger["source_receipt_count"] == len(skeleton["source_receipts"])
    assert ledger["known_gap_count"] == len(skeleton["known_gaps"])
    assert ledger["public_claims_release_allowed"] is True
    assert ledger["issues"] == []
    assert source_receipt_contract_passed(skeleton) is True
    assert source_receipt_contract_issues(skeleton) == ()


def test_source_receipt_ledger_exposes_claim_to_receipt_graph() -> None:
    skeleton = get_packet_skeleton("company_public_baseline")

    ledger = build_source_receipt_ledger(skeleton)

    graph_by_claim = {edge["claim_id"]: edge for edge in ledger["claim_graph"]}
    assert graph_by_claim["claim_company_name"]["receipt_ids"] == ["sr_company_gbizinfo"]
    assert graph_by_claim["claim_company_name"]["public_claim_export_allowed"] is True
    assert graph_by_claim["claim_company_name"]["missing_receipt_ids"] == []
    inventory_by_receipt = {
        receipt["receipt_id"]: receipt for receipt in ledger["receipt_inventory"]
    }
    assert inventory_by_receipt["sr_company_gbizinfo"]["claim_ids"] == ["claim_company_name"]


def test_source_receipt_primitives_match_packet_skeleton_shape() -> None:
    claim = public_claim("claim_1", "Claim text.", ("receipt_1",))
    receipt = source_receipt("receipt_1", "source_family", "metadata:source")
    gap = known_gap("gap_1", "coverage", "Coverage gap.")

    assert claim == {
        "claim_id": "claim_1",
        "text": "Claim text.",
        "visibility": "public",
        "support_state": "supported",
        "receipt_ids": ["receipt_1"],
    }
    assert receipt == {
        "receipt_id": "receipt_1",
        "source_family_id": "source_family",
        "source_url": "metadata:source",
        "observed_at": DEFAULT_OBSERVED_AT,
        "access_method": "metadata_only",
        "support_state": "direct",
    }
    assert gap == {
        "gap_id": "gap_1",
        "gap_type": "coverage",
        "gap_status": "known_gap",
        "explanation": "Coverage gap.",
    }


def test_claim_receipt_link_assertion_rejects_missing_and_duplicate_receipts() -> None:
    claims = [public_claim("claim_1", "Claim text.", ("receipt_1",))]
    receipts = [source_receipt("receipt_1", "source_family", "metadata:source")]

    assert_claim_receipt_links(claims, receipts)

    with pytest.raises(ValueError, match="unknown source receipt id"):
        assert_claim_receipt_links(
            [public_claim("claim_2", "Claim text.", ("missing_receipt",))],
            receipts,
        )
    with pytest.raises(ValueError, match="duplicate source receipt id"):
        assert_claim_receipt_links(claims, [receipts[0], receipts[0]])


def test_gap_state_claim_is_allowed_as_gap_statement_not_supported_fact() -> None:
    skeleton = get_packet_skeleton("source_receipt_ledger")

    ledger = build_source_receipt_ledger(skeleton)

    gap_edge = {edge["claim_id"]: edge for edge in ledger["claim_graph"]}["claim_registry_gap"]
    assert gap_edge["support_state"] == "gap"
    assert gap_edge["gap_statement_allowed"] is True
    assert gap_edge["public_claim_export_allowed"] is False
    assert ledger["public_claims_release_allowed"] is True


@pytest.mark.parametrize(
    ("record_key", "required_fields"),
    [
        ("claims", REQUIRED_CLAIM_FIELDS),
        ("source_receipts", REQUIRED_RECEIPT_FIELDS),
        ("known_gaps", REQUIRED_GAP_FIELDS),
    ],
)
def test_missing_required_source_receipt_contract_fields_create_blocking_issues(
    record_key: str,
    required_fields: tuple[str, ...],
) -> None:
    skeleton = get_packet_skeleton("company_public_baseline")
    broken = deepcopy(skeleton)
    missing_field = required_fields[0]
    broken[record_key][0].pop(missing_field)

    ledger = build_source_receipt_ledger(broken)

    assert ledger["public_claims_release_allowed"] is False
    assert any(
        issue["code"] == f"{record_key.rstrip('s')}_missing_{missing_field}"
        or issue["code"] == f"{record_key[:-1]}_missing_{missing_field}"
        for issue in ledger["issues"]
    )
    assert source_receipt_contract_passed(broken) is False


def test_unknown_receipt_reference_blocks_public_claim_release() -> None:
    skeleton = get_packet_skeleton("company_public_baseline")
    broken = deepcopy(skeleton)
    broken["claims"][0]["receipt_ids"] = ["sr_missing"]

    ledger = build_source_receipt_ledger(broken)

    assert ledger["public_claims_release_allowed"] is False
    assert ledger["claim_graph"][0]["missing_receipt_ids"] == ["sr_missing"]
    assert any(issue["code"] == "claim_unknown_receipt_id" for issue in ledger["issues"])


def test_absence_claim_enabled_blocks_source_receipt_contract() -> None:
    skeleton = get_packet_skeleton("invoice_registrant_public_check")
    broken = deepcopy(skeleton)
    broken["no_hit_semantics"]["absence_claim_enabled"] = True

    ledger = build_source_receipt_ledger(broken)

    assert ledger["public_claims_release_allowed"] is False
    assert any(issue["code"] == "absence_claim_enabled" for issue in ledger["issues"])
