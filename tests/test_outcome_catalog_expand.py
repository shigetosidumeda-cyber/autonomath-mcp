"""Outcome catalog expansion gate (14 → 30 outcomes).

The on-disk catalog at ``site/releases/rc1-p0-bootstrap/outcome_contract_catalog.json``
is a cross-analysis derived superset of the Python builder. Master plan §3.3
priority outputs and the AWS canary deep cross-analysis produce far more
packet types than the original 14 P0 outcomes; this catalog captures all of
them so agents can preview cost and select the cheapest sufficient route.

These tests verify:

  - The disk catalog contains 30+ paid outcomes (was 14).
  - Each new outcome has a non-empty packet_ids list.
  - Each new outcome's cost_preview entry uses the canonical
    {free, light, mid, heavy} band set with prices {0, 300, 600, 900}.
  - Every entry exposes a free preview endpoint (master plan §1).
  - ``known_gaps`` values stay within the 7-enum allowed by
    ``cost_preview_catalog.schema.json``.
  - The 2 free controls (agent_routing_decision + cost_preview) keep
    ``billable: false`` and price 0.
  - The .well-known mirror stays byte-identical to the release-pinned copy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPSULE_DIR = REPO_ROOT / "site" / "releases" / "rc1-p0-bootstrap"
OUTCOME_CATALOG = CAPSULE_DIR / "outcome_contract_catalog.json"
COST_PREVIEW_RELEASE = CAPSULE_DIR / "cost_preview_catalog.json"
COST_PREVIEW_WELL_KNOWN = (
    REPO_ROOT / "site" / ".well-known" / "jpcite-cost-preview.json"
)

ORIGINAL_14_PAID_OUTCOMES = {
    "company_public_baseline",
    "invoice_registrant_public_check",
    "application_strategy",
    "regulation_change_watch",
    "local_government_permit_obligation_map",
    "court_enforcement_citation_pack",
    "public_statistics_market_context",
    "client_monthly_review",
    "csv_overlay_public_check",
    "cashbook_csv_subsidy_fit_screen",
    "source_receipt_ledger",
    "evidence_answer",
    "foreign_investor_japan_public_entry_brief",
    "healthcare_regulatory_public_check",
}

EXPECTED_NEW_OUTCOMES = {
    "houjin_360_full_packet",
    "program_lineage_packet",
    "acceptance_probability_cohort_packet",
    "enforcement_industry_heatmap_packet",
    "invoice_houjin_cross_check_packet",
    "program_law_amendment_impact_packet",
    "cohort_program_recommendation_packet",
    "vendor_due_diligence_packet",
    "succession_program_matching_packet",
    "regulatory_change_radar_packet",
    "tax_treaty_japan_inbound_packet",
    "subsidy_application_timeline_packet",
    "bid_opportunity_matching_packet",
    "permit_renewal_calendar_packet",
    "local_government_subsidy_aggregator_packet",
    "kanpou_gazette_watch_packet",
}

FREE_OUTCOMES = {"agent_routing_decision", "cost_preview"}

CANONICAL_BAND_PRICES = {"free": 0, "light": 300, "mid": 600, "heavy": 900}

CANONICAL_GAP_ENUM = {
    "pricing_or_cap_unconfirmed",
    "source_freshness_unconfirmed",
    "coverage_thin",
    "schema_drift_possible",
    "approval_token_semantics_pending",
    "idempotency_window_provisional",
    "free_preview_endpoint_pending",
}


def _load_list(path: Path) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", json.loads(path.read_text(encoding="utf-8")))


def _load_dict(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def test_outcome_contract_catalog_has_30_plus_paid_outcomes() -> None:
    outcomes = _load_list(OUTCOME_CATALOG)
    paid = [o for o in outcomes if o["billable"] is True]
    free = [o for o in outcomes if o["billable"] is False]

    assert len(free) == 2, f"expected 2 free controls, got {len(free)}"
    assert len(paid) >= 30, f"expected 30+ paid outcomes, got {len(paid)}"


def test_original_14_paid_outcomes_preserved() -> None:
    outcomes = _load_list(OUTCOME_CATALOG)
    ids = {o["outcome_contract_id"] for o in outcomes if o["billable"] is True}
    missing = ORIGINAL_14_PAID_OUTCOMES - ids
    assert not missing, f"original 14 paid outcomes missing from catalog: {missing}"


def test_all_16_new_outcomes_present() -> None:
    outcomes = _load_list(OUTCOME_CATALOG)
    ids = {o["outcome_contract_id"] for o in outcomes}
    missing = EXPECTED_NEW_OUTCOMES - ids
    assert not missing, f"expected new outcomes missing: {missing}"


def test_every_new_outcome_has_non_empty_packet_ids() -> None:
    outcomes = _load_list(OUTCOME_CATALOG)
    for outcome in outcomes:
        if outcome["outcome_contract_id"] in EXPECTED_NEW_OUTCOMES:
            packet_ids = outcome.get("packet_ids", [])
            assert packet_ids, (
                f"{outcome['outcome_contract_id']} has empty packet_ids"
            )
            assert isinstance(packet_ids, list)
            assert all(isinstance(pid, str) and pid for pid in packet_ids)


def test_cost_preview_catalog_covers_all_30_plus_outcomes() -> None:
    outcomes = _load_list(OUTCOME_CATALOG)
    preview = _load_dict(COST_PREVIEW_RELEASE)
    outcome_ids = {o["outcome_contract_id"] for o in outcomes}
    preview_ids = {e["outcome_contract_id"] for e in preview["entries"]}

    missing = outcome_ids - preview_ids
    extra = preview_ids - outcome_ids
    assert not missing, f"cost_preview missing entries for: {missing}"
    assert not extra, f"cost_preview has stray entries: {extra}"
    assert len(preview["entries"]) >= 32


def test_new_outcomes_use_canonical_price_bands() -> None:
    preview = _load_dict(COST_PREVIEW_RELEASE)
    for entry in preview["entries"]:
        if entry["outcome_contract_id"] not in EXPECTED_NEW_OUTCOMES:
            continue
        band = entry["cost_band"]
        price = entry["estimated_price_jpy"]
        assert band in CANONICAL_BAND_PRICES, (
            f"{entry['outcome_contract_id']} band {band} not canonical"
        )
        assert price == CANONICAL_BAND_PRICES[band], (
            f"{entry['outcome_contract_id']} band={band} price={price} drift"
        )
        # New outcomes must be paid (band != free) since the 2 free controls
        # were already in the original surface.
        assert band != "free", (
            f"{entry['outcome_contract_id']} new outcomes must be paid"
        )


def test_every_new_outcome_has_free_preview_available() -> None:
    preview = _load_dict(COST_PREVIEW_RELEASE)
    for entry in preview["entries"]:
        if entry["outcome_contract_id"] not in EXPECTED_NEW_OUTCOMES:
            continue
        assert entry["free_preview_available"] is True, (
            f"{entry['outcome_contract_id']} missing free preview"
        )
        ep = entry["preview_endpoint"]
        assert ep and ep.startswith(("/", "mcp:")), (
            f"{entry['outcome_contract_id']} preview_endpoint {ep!r} invalid"
        )


def test_new_outcomes_known_gaps_respect_7_enum() -> None:
    preview = _load_dict(COST_PREVIEW_RELEASE)
    for entry in preview["entries"]:
        if entry["outcome_contract_id"] not in EXPECTED_NEW_OUTCOMES:
            continue
        gaps = entry.get("known_gaps", [])
        assert isinstance(gaps, list)
        # At least 1 known_gap and max 3 per master plan constraints.
        assert 1 <= len(gaps) <= 3, (
            f"{entry['outcome_contract_id']} known_gaps count {len(gaps)} "
            f"outside [1, 3]"
        )
        for gap in gaps:
            assert gap in CANONICAL_GAP_ENUM, (
                f"{entry['outcome_contract_id']} unknown gap marker: {gap}"
            )


def test_free_controls_remain_billable_false() -> None:
    outcomes = _load_list(OUTCOME_CATALOG)
    free_by_id = {
        o["outcome_contract_id"]: o
        for o in outcomes
        if o["outcome_contract_id"] in FREE_OUTCOMES
    }
    assert set(free_by_id.keys()) == FREE_OUTCOMES
    for outcome_id, outcome in free_by_id.items():
        assert outcome["billable"] is False, f"{outcome_id} must stay free"
        assert outcome["no_hit_semantics"] == "no_hit_not_absence"
        assert outcome["cheapest_sufficient_route_required"] is True
        assert outcome["public_claims_require_receipts"] is True

    preview = _load_dict(COST_PREVIEW_RELEASE)
    free_entries = {
        e["outcome_contract_id"]: e
        for e in preview["entries"]
        if e["outcome_contract_id"] in FREE_OUTCOMES
    }
    for outcome_id, entry in free_entries.items():
        assert entry["cost_band"] == "free", outcome_id
        assert entry["estimated_price_jpy"] == 0, outcome_id


def test_well_known_mirror_stays_byte_identical_to_release_pinned() -> None:
    """The .well-known/jpcite-cost-preview.json must equal the release-pinned
    catalog byte-for-byte (test_cost_preview_catalog enforces the same
    contract; we re-verify here to gate the expansion landing)."""
    release_body = COST_PREVIEW_RELEASE.read_text(encoding="utf-8")
    well_known_body = COST_PREVIEW_WELL_KNOWN.read_text(encoding="utf-8")
    assert release_body == well_known_body


def test_all_entries_carry_jpcite_cost_jpy_3_in_expanded_catalog() -> None:
    preview = _load_dict(COST_PREVIEW_RELEASE)
    for entry in preview["entries"]:
        assert entry["jpcite_cost_jpy"] == 3, (
            f"{entry['outcome_contract_id']} drifted off ¥3/req base"
        )


def test_null_cap_paid_entries_carry_pricing_or_cap_unconfirmed() -> None:
    """Master plan §7: paid outcomes with null daily cap must declare
    ``pricing_or_cap_unconfirmed`` so the agent can detect provisional
    pricing."""
    preview = _load_dict(COST_PREVIEW_RELEASE)
    for entry in preview["entries"]:
        if entry["cost_band"] == "free":
            continue
        if entry["cap_per_day"] is None:
            assert "pricing_or_cap_unconfirmed" in entry["known_gaps"], (
                f"{entry['outcome_contract_id']} has null cap but no "
                f"pricing_or_cap_unconfirmed gap"
            )
