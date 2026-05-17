"""Tests for the F4 4-tier outcome-band pricing module (pricing_v2).

29 tests across:
* PricingTier enum semantics + ordering.
* PRICE_BY_TIER / TIER_BAND_FLOOR / TIER_BAND_CEIL bands.
* price_for_tier accepts both enum + raw letter.
* tier_for_outcome_posture legacy bridge.
* validate_pack_price floor + ceil edges.
* stripe_metering_quantity_for_tier ceil math + call_count multiplier.
* x402_price_yen_for_tier envelope bounds.
* No LLM SDK imports in the module.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def pricing_v2_module() -> object:
    return importlib.import_module("jpintel_mcp.billing.pricing_v2")


def test_pricing_tier_canonical_letters(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert PricingTier.A.value == "A"
    assert PricingTier.B.value == "B"
    assert PricingTier.C.value == "C"
    assert PricingTier.D.value == "D"


def test_all_tiers_canonical_order(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.all_tiers() == (
        PricingTier.A,
        PricingTier.B,
        PricingTier.C,
        PricingTier.D,
    )


def test_price_by_tier_canonical_yen(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PRICE_BY_TIER = pricing_v2_module.PRICE_BY_TIER
    PricingTier = pricing_v2_module.PricingTier
    assert PRICE_BY_TIER[PricingTier.A] == 3
    assert PRICE_BY_TIER[PricingTier.B] == 10
    assert PRICE_BY_TIER[PricingTier.C] == 30
    assert PRICE_BY_TIER[PricingTier.D] == 800


def test_tier_band_floor_and_ceil(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    TIER_BAND_FLOOR = pricing_v2_module.TIER_BAND_FLOOR
    TIER_BAND_CEIL = pricing_v2_module.TIER_BAND_CEIL
    assert TIER_BAND_FLOOR[PricingTier.A] == 3
    assert TIER_BAND_CEIL[PricingTier.A] == 3
    assert TIER_BAND_FLOOR[PricingTier.D] == 100
    assert TIER_BAND_CEIL[PricingTier.D] == 1000


def test_tier_band_collapsed_for_atomic_bundle_composed(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    for t in (PricingTier.A, PricingTier.B, PricingTier.C):
        assert pricing_v2_module.tier_band(t)[0] == pricing_v2_module.tier_band(t)[1]


def test_tier_band_open_for_pack(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    floor, ceil = pricing_v2_module.tier_band(PricingTier.D)
    assert floor == 100
    assert ceil == 1000


def test_price_for_tier_accepts_enum(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    assert pricing_v2_module.price_for_tier(pricing_v2_module.PricingTier.A) == 3


def test_price_for_tier_accepts_raw_letter(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    assert pricing_v2_module.price_for_tier("B") == 10


def test_price_for_tier_returns_none_for_unknown(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    assert pricing_v2_module.price_for_tier("Z") is None
    assert pricing_v2_module.price_for_tier("") is None


def test_tier_for_outcome_posture_low_to_d(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.tier_for_outcome_posture("accepted_artifact_low") == PricingTier.D


def test_tier_for_outcome_posture_standard_to_d(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.tier_for_outcome_posture("accepted_artifact_standard") == PricingTier.D


def test_tier_for_outcome_posture_premium_to_d(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.tier_for_outcome_posture("accepted_artifact_premium") == PricingTier.D


def test_tier_for_outcome_posture_csv_overlay_to_d(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert (
        pricing_v2_module.tier_for_outcome_posture("accepted_artifact_csv_overlay") == PricingTier.D
    )


def test_tier_for_outcome_posture_free_preview_none(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    assert pricing_v2_module.tier_for_outcome_posture("free_preview") is None


def test_tier_for_outcome_posture_unknown_none(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    assert pricing_v2_module.tier_for_outcome_posture("nope") is None


def test_validate_pack_price_strict_for_atomic_tiers(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.validate_pack_price(PricingTier.A, 3) is True
    assert pricing_v2_module.validate_pack_price(PricingTier.A, 4) is False
    assert pricing_v2_module.validate_pack_price(PricingTier.A, 2) is False


def test_validate_pack_price_band_for_pack(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.validate_pack_price(PricingTier.D, 100) is True
    assert pricing_v2_module.validate_pack_price(PricingTier.D, 500) is True
    assert pricing_v2_module.validate_pack_price(PricingTier.D, 1000) is True
    assert pricing_v2_module.validate_pack_price(PricingTier.D, 99) is False
    assert pricing_v2_module.validate_pack_price(PricingTier.D, 1001) is False


def test_validate_pack_price_a5_band(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.validate_pack_price(PricingTier.D, 800) is True
    assert pricing_v2_module.validate_pack_price(PricingTier.D, 801) is True


def test_stripe_metering_atomic_one_unit(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.stripe_metering_quantity_for_tier(PricingTier.A) == 1


def test_stripe_metering_bundle_four_units_ceiling(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.stripe_metering_quantity_for_tier(PricingTier.B) == 4


def test_stripe_metering_composed_ten_units(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.stripe_metering_quantity_for_tier(PricingTier.C) == 10


def test_stripe_metering_pack_267_units(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.stripe_metering_quantity_for_tier(PricingTier.D) == 267


def test_stripe_metering_call_count_multiplier(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.stripe_metering_quantity_for_tier(PricingTier.A, call_count=5) == 5
    assert pricing_v2_module.stripe_metering_quantity_for_tier(PricingTier.D, call_count=2) == 534


def test_stripe_metering_zero_count_raises(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    with pytest.raises(ValueError):
        pricing_v2_module.stripe_metering_quantity_for_tier(PricingTier.A, call_count=0)


def test_stripe_metering_unknown_tier_raises(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        pricing_v2_module.stripe_metering_quantity_for_tier("Z")


def test_tier_c_30_yen(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    """Composed tier ties to ¥30 (7-13 atomic via rule_tree)."""
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.price_for_tier(PricingTier.C) == 30


def test_tier_d_default_800_yen(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.price_for_tier(PricingTier.D) == 800


def test_x402_price_inside_envelope_window(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    PricingTier = pricing_v2_module.PricingTier
    assert pricing_v2_module.x402_price_yen_for_tier(PricingTier.A) == 3
    assert pricing_v2_module.x402_price_yen_for_tier(PricingTier.D) == 800


def test_x402_challenge_constructs_with_tier_price(pricing_v2_module) -> None:  # type: ignore[no-untyped-def]
    """Tier prices must fit inside the [1, 1_000_000] x402 envelope."""
    PricingTier = pricing_v2_module.PricingTier
    for t in (PricingTier.A, PricingTier.B, PricingTier.C, PricingTier.D):
        price = pricing_v2_module.x402_price_yen_for_tier(t)
        assert 1 <= price <= 1_000_000


def test_no_llm_imports_in_pricing_v2() -> None:
    """pricing_v2 module MUST NOT import any LLM SDK."""
    mod = importlib.import_module("jpintel_mcp.billing.pricing_v2")
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for needle in (
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
    ):
        assert needle not in src, f"pricing_v2 imports forbidden LLM SDK: {needle}"
