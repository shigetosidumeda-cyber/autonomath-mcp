"""Stream C: outcome catalog estimated_price_jpy gate.

All 14 P0 deliverables must declare a positive ``estimated_price_jpy`` in
the public release capsule and the Python catalog. The user-locked pricing
table is checked exactly (cents matter for billing reconciliation) and the
release capsule JSON + Python ``build_outcome_catalog_shape`` agree.

This is a *gate* — the facade quotes prices from these surfaces and the
billing ledger reconciles against them. A regression to ``null``, ``0``, or
a drift between the JSON capsule and the Python catalog is a launch
blocker, not a warning.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jpintel_mcp.agent_runtime.defaults import (
    build_accepted_artifact_pricing,
    build_bootstrap_bundle,
)
from jpintel_mcp.agent_runtime.outcome_catalog import (
    build_outcome_catalog,
    build_outcome_catalog_shape,
)
from jpintel_mcp.agent_runtime.pricing_policy import (
    PRICE_BY_PRICING_POSTURE,
    price_for_pricing_posture,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CAPSULE_DIR = REPO_ROOT / "site" / "releases" / "rc1-p0-bootstrap"
OUTCOME_CATALOG_JSON = CAPSULE_DIR / "outcome_catalog.json"
ACCEPTED_ARTIFACT_PRICING_JSON = CAPSULE_DIR / "accepted_artifact_pricing.json"

EXPECTED_DELIVERABLE_COUNT = 14

# User-locked pricing table for Stream C (Wave 49). These are billed prices in
# JPY (税抜 base ¥3/req model scaled to outcome size). The test asserts the
# table is met exactly — both as the Python catalog shape and as the public
# JSON capsule. Drifting any single value here without a coordinated bump in
# the pricing policy is a launch blocker.
EXPECTED_PRICES_BY_OUTCOME_CONTRACT_ID: dict[str, int] = {
    "company_public_baseline": 600,
    "invoice_registrant_public_check": 300,
    "application_strategy": 900,
    "regulation_change_watch": 600,
    "local_government_permit_obligation_map": 900,
    "court_enforcement_citation_pack": 600,
    "public_statistics_market_context": 600,
    "client_monthly_review": 900,
    "csv_overlay_public_check": 900,
    "cashbook_csv_subsidy_fit_screen": 900,
    "source_receipt_ledger": 600,
    "evidence_answer": 600,
    "foreign_investor_japan_public_entry_brief": 900,
    "healthcare_regulatory_public_check": 600,
}


@pytest.fixture(scope="module")
def outcome_catalog_json() -> dict:
    return json.loads(OUTCOME_CATALOG_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def accepted_artifact_pricing_json() -> dict:
    return json.loads(ACCEPTED_ARTIFACT_PRICING_JSON.read_text(encoding="utf-8"))


def test_python_catalog_has_14_deliverables_all_priced_positive() -> None:
    catalog = build_outcome_catalog()
    assert len(catalog) == EXPECTED_DELIVERABLE_COUNT

    for entry in catalog:
        price_jpy = price_for_pricing_posture(entry.pricing_posture)
        assert price_jpy is not None, (
            f"{entry.outcome_contract_id} pricing posture {entry.pricing_posture} has no price"
        )
        assert price_jpy > 0, (
            f"{entry.outcome_contract_id} estimated_price_jpy must be > 0 (got {price_jpy})"
        )


def test_python_catalog_shape_estimated_price_jpy_matches_user_locked_table() -> None:
    shape = build_outcome_catalog_shape()
    deliverables = shape["deliverables"]
    assert len(deliverables) == EXPECTED_DELIVERABLE_COUNT

    observed: dict[str, int] = {}
    for entry in deliverables:
        outcome_contract_id = entry["outcome_contract_id"]
        price_value = entry.get("estimated_price_jpy")
        assert price_value is not None, (
            f"{outcome_contract_id} missing estimated_price_jpy in catalog shape"
        )
        assert isinstance(price_value, int), (
            f"{outcome_contract_id} estimated_price_jpy must be int "
            f"(got {type(price_value).__name__})"
        )
        assert price_value > 0, (
            f"{outcome_contract_id} estimated_price_jpy must be > 0 (got {price_value})"
        )
        observed[outcome_contract_id] = price_value

    assert observed == EXPECTED_PRICES_BY_OUTCOME_CONTRACT_ID


def test_release_capsule_outcome_catalog_json_estimated_price_jpy_matches(
    outcome_catalog_json: dict,
) -> None:
    deliverables = outcome_catalog_json["deliverables"]
    assert len(deliverables) == EXPECTED_DELIVERABLE_COUNT, (
        f"release capsule expected {EXPECTED_DELIVERABLE_COUNT} deliverables, "
        f"got {len(deliverables)}"
    )

    observed: dict[str, int] = {}
    for entry in deliverables:
        outcome_contract_id = entry["outcome_contract_id"]
        price_value = entry.get("estimated_price_jpy")
        assert price_value is not None, (
            f"{outcome_contract_id} missing estimated_price_jpy in release capsule"
        )
        assert isinstance(price_value, int) and price_value > 0, (
            f"{outcome_contract_id} estimated_price_jpy invalid in release "
            f"capsule (got {price_value!r})"
        )
        observed[outcome_contract_id] = price_value

    assert observed == EXPECTED_PRICES_BY_OUTCOME_CONTRACT_ID


def test_accepted_artifact_pricing_rules_cover_all_14_outcomes(
    accepted_artifact_pricing_json: dict,
) -> None:
    rules = accepted_artifact_pricing_json.get("deliverable_pricing_rules") or []
    assert len(rules) == EXPECTED_DELIVERABLE_COUNT, (
        f"accepted_artifact_pricing must declare {EXPECTED_DELIVERABLE_COUNT} "
        f"deliverable_pricing_rules, got {len(rules)}"
    )

    observed: dict[str, int] = {}
    for rule in rules:
        outcome_contract_id = rule["outcome_contract_id"]
        price_value = rule.get("estimated_price_jpy")
        assert isinstance(price_value, int) and price_value > 0, (
            f"{outcome_contract_id} estimated_price_jpy invalid in "
            f"accepted_artifact_pricing (got {price_value!r})"
        )
        assert rule.get("billable_only_after_accepted_artifact") is True
        observed[outcome_contract_id] = price_value

    assert observed == EXPECTED_PRICES_BY_OUTCOME_CONTRACT_ID


def test_python_pricing_rules_builder_matches_user_locked_table() -> None:
    pricing = build_accepted_artifact_pricing()
    rules = pricing.deliverable_pricing_rules
    assert len(rules) == EXPECTED_DELIVERABLE_COUNT

    observed = {rule.outcome_contract_id: rule.estimated_price_jpy for rule in rules}
    assert observed == EXPECTED_PRICES_BY_OUTCOME_CONTRACT_ID

    for rule in rules:
        assert rule.estimated_price_jpy > 0
        assert rule.billable_only_after_accepted_artifact is True


def test_bootstrap_bundle_pricing_is_internally_consistent() -> None:
    """The catalog shape and the pricing rules must agree per-outcome.

    The facade reads estimated_price_jpy from the catalog and the ledger
    reconciles against the pricing rules. A divergence between the two would
    let the facade quote one price and the ledger charge another.
    """

    bundle = build_bootstrap_bundle()
    catalog_prices = {
        entry["outcome_contract_id"]: entry["estimated_price_jpy"]
        for entry in bundle["outcome_catalog"]["deliverables"]
    }
    rule_prices = {
        rule["outcome_contract_id"]: rule["estimated_price_jpy"]
        for rule in bundle["accepted_artifact_pricing"]["deliverable_pricing_rules"]
    }

    assert catalog_prices == rule_prices == EXPECTED_PRICES_BY_OUTCOME_CONTRACT_ID


def test_pricing_policy_table_is_consistent_with_user_locked_prices() -> None:
    """Sanity-check: every pricing posture referenced by the catalog has a
    deterministic JPY price in ``PRICE_BY_PRICING_POSTURE``."""

    catalog = build_outcome_catalog()
    used_postures = {entry.pricing_posture for entry in catalog}
    for posture in used_postures:
        assert posture in PRICE_BY_PRICING_POSTURE, (
            f"pricing posture {posture} used by catalog but missing from PRICE_BY_PRICING_POSTURE"
        )
        assert PRICE_BY_PRICING_POSTURE[posture] > 0, (
            f"pricing posture {posture} must have positive JPY price"
        )
