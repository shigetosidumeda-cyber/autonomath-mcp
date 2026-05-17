"""Tests for V3 Agent-Economy First pricing (billing/pricing_v3).

V3 collapses the V2 outcome-band billable_units so each tier stays
inside the agent-economy skip threshold (Sonnet 4.6 self-compose).
Unit price stays ¥3 (CLAUDE.md hard guard); only ``billable_units``
per tier changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jpintel_mcp.billing.pricing_v3 import (
    BILLABLE_UNITS_BY_TIER,
    HAIKU_45_PRICE_PER_TURN_JPY,
    OPUS_47_PRICE_PER_TURN_JPY,
    PRICE_BY_TIER,
    PRICING_VERSION,
    SONNET_46_PRICE_PER_TURN_JPY,
    SONNET_TURNS_BY_TIER,
    TIER_BAND_CEIL,
    TIER_BAND_FLOOR,
    PricingTier,
    agent_compete_table,
    all_tiers,
    billable_units_for_tier,
    haiku_self_compose_price_jpy,
    jpcite_saving_vs_opus_pct,
    jpcite_saving_vs_sonnet_pct,
    migrate_v2_units_to_v3,
    opus_self_compose_price_jpy,
    price_for_tier,
    sonnet_self_compose_price_jpy,
    stripe_metering_quantity_for_tier,
    tier_band,
    validate_pack_price,
    x402_price_yen_for_tier,
)


def test_pricing_version_string_is_v3() -> None:
    assert PRICING_VERSION == "v3"


def test_four_tiers_exactly() -> None:
    assert all_tiers() == (PricingTier.A, PricingTier.B, PricingTier.C, PricingTier.D)
    assert len(PRICE_BY_TIER) == 4
    assert len(BILLABLE_UNITS_BY_TIER) == 4


def test_billable_units_per_tier_match_spec() -> None:
    assert BILLABLE_UNITS_BY_TIER[PricingTier.A] == 1
    assert BILLABLE_UNITS_BY_TIER[PricingTier.B] == 2
    assert BILLABLE_UNITS_BY_TIER[PricingTier.C] == 4
    assert BILLABLE_UNITS_BY_TIER[PricingTier.D] == 10


def test_yen_prices_per_tier_match_spec() -> None:
    assert PRICE_BY_TIER[PricingTier.A] == 3
    assert PRICE_BY_TIER[PricingTier.B] == 6
    assert PRICE_BY_TIER[PricingTier.C] == 12
    assert PRICE_BY_TIER[PricingTier.D] == 30


def test_unit_price_invariant_3_yen() -> None:
    for tier in all_tiers():
        assert PRICE_BY_TIER[tier] == BILLABLE_UNITS_BY_TIER[tier] * 3


def test_billable_units_for_tier_lookup() -> None:
    assert billable_units_for_tier("A") == 1
    assert billable_units_for_tier("B") == 2
    assert billable_units_for_tier("C") == 4
    assert billable_units_for_tier("D") == 10
    assert billable_units_for_tier("Z") is None


def test_price_for_tier_lookup() -> None:
    assert price_for_tier(PricingTier.A) == 3
    assert price_for_tier("D") == 30
    assert price_for_tier("z") is None


def test_atomic_tiers_band_collapses_to_point() -> None:
    for tier in (PricingTier.A, PricingTier.B, PricingTier.C):
        floor, ceil = tier_band(tier)
        assert floor == ceil


def test_tier_d_band_30_to_120_yen() -> None:
    assert tier_band(PricingTier.D) == (30, 120)
    assert TIER_BAND_FLOOR[PricingTier.D] == 30
    assert TIER_BAND_CEIL[PricingTier.D] == 120


def test_validate_pack_price_strict_for_atomic_tiers() -> None:
    assert validate_pack_price(PricingTier.A, 3) is True
    assert validate_pack_price(PricingTier.A, 4) is False
    assert validate_pack_price(PricingTier.B, 6) is True
    assert validate_pack_price(PricingTier.B, 5) is False
    assert validate_pack_price(PricingTier.C, 12) is True
    assert validate_pack_price(PricingTier.C, 13) is False


def test_validate_pack_price_band_for_tier_d() -> None:
    assert validate_pack_price(PricingTier.D, 30) is True
    assert validate_pack_price(PricingTier.D, 60) is True
    assert validate_pack_price(PricingTier.D, 90) is True
    assert validate_pack_price(PricingTier.D, 120) is True
    assert validate_pack_price(PricingTier.D, 29) is False
    assert validate_pack_price(PricingTier.D, 121) is False


def test_stripe_metering_tier_a_one_unit() -> None:
    assert stripe_metering_quantity_for_tier(PricingTier.A) == 1


def test_stripe_metering_tier_b_two_units() -> None:
    assert stripe_metering_quantity_for_tier(PricingTier.B) == 2


def test_stripe_metering_tier_c_four_units() -> None:
    assert stripe_metering_quantity_for_tier(PricingTier.C) == 4


def test_stripe_metering_tier_d_ten_units() -> None:
    assert stripe_metering_quantity_for_tier(PricingTier.D) == 10


def test_stripe_metering_scales_with_call_count() -> None:
    assert stripe_metering_quantity_for_tier(PricingTier.A, call_count=5) == 5
    assert stripe_metering_quantity_for_tier(PricingTier.D, call_count=3) == 30


def test_stripe_metering_zero_count_raises() -> None:
    with pytest.raises(ValueError, match="call_count must be"):
        stripe_metering_quantity_for_tier(PricingTier.A, call_count=0)


def test_stripe_metering_unknown_tier_raises() -> None:
    with pytest.raises(ValueError, match="unknown tier"):
        stripe_metering_quantity_for_tier("Z")


def test_x402_price_matches_tier_yen() -> None:
    assert x402_price_yen_for_tier(PricingTier.A) == 3
    assert x402_price_yen_for_tier(PricingTier.B) == 6
    assert x402_price_yen_for_tier(PricingTier.C) == 12
    assert x402_price_yen_for_tier(PricingTier.D) == 30


def test_x402_unknown_tier_raises() -> None:
    with pytest.raises(ValueError, match="unknown tier"):
        x402_price_yen_for_tier("Z")


def test_migrate_v2_unit_1_stays_1() -> None:
    assert migrate_v2_units_to_v3(1) == 1
    assert migrate_v2_units_to_v3(0) == 1


def test_migrate_v2_unit_b_band_collapses_to_2() -> None:
    assert migrate_v2_units_to_v3(2) == 2
    assert migrate_v2_units_to_v3(3) == 2
    assert migrate_v2_units_to_v3(5) == 2


def test_migrate_v2_unit_c_band_collapses_to_4() -> None:
    assert migrate_v2_units_to_v3(10) == 4
    assert migrate_v2_units_to_v3(20) == 4


def test_migrate_v2_unit_d_band_collapses_to_10() -> None:
    assert migrate_v2_units_to_v3(33) == 10
    assert migrate_v2_units_to_v3(100) == 10
    assert migrate_v2_units_to_v3(167) == 10
    assert migrate_v2_units_to_v3(267) == 10
    assert migrate_v2_units_to_v3(333) == 10


def test_sonnet_self_compose_prices() -> None:
    assert sonnet_self_compose_price_jpy(PricingTier.A) == 3.75
    assert sonnet_self_compose_price_jpy(PricingTier.B) == 7.50
    assert sonnet_self_compose_price_jpy(PricingTier.C) == 15.0
    assert sonnet_self_compose_price_jpy(PricingTier.D) == 30.0


def test_opus_self_compose_prices() -> None:
    assert opus_self_compose_price_jpy(PricingTier.A) == 9.375
    assert opus_self_compose_price_jpy(PricingTier.D) == 75.0


def test_haiku_self_compose_prices() -> None:
    assert haiku_self_compose_price_jpy(PricingTier.A) == 1.5
    assert haiku_self_compose_price_jpy(PricingTier.D) == 12.0


def test_jpcite_wins_vs_sonnet_on_a_b_c() -> None:
    assert jpcite_saving_vs_sonnet_pct(PricingTier.A) > 0
    assert jpcite_saving_vs_sonnet_pct(PricingTier.B) > 0
    assert jpcite_saving_vs_sonnet_pct(PricingTier.C) > 0


def test_jpcite_at_parity_with_sonnet_on_d() -> None:
    assert jpcite_saving_vs_sonnet_pct(PricingTier.D) == 0.0


def test_jpcite_saves_vs_opus_60_pct_on_d() -> None:
    assert jpcite_saving_vs_opus_pct(PricingTier.D) == 60.0


def test_agent_compete_table_has_4_rows() -> None:
    table = agent_compete_table()
    assert len(table) == 4
    for row in table:
        for key in (
            "tier",
            "billable_units",
            "jpcite_price_jpy",
            "sonnet_turns",
            "sonnet_price_jpy",
            "sonnet_saving_pct",
            "opus_price_jpy",
            "opus_saving_pct",
            "haiku_price_jpy",
        ):
            assert key in row


def test_no_llm_imports_in_pricing_v3() -> None:
    import jpintel_mcp.billing.pricing_v3 as m

    src = Path(m.__file__).read_text(encoding="utf-8")
    for needle in ("anthropic", "openai", "google.generativeai", "claude_agent_sdk"):
        assert needle not in src


def test_tier_prices_strictly_increasing() -> None:
    prices = [PRICE_BY_TIER[t] for t in all_tiers()]
    assert prices == sorted(prices)
    assert prices == [3, 6, 12, 30]


def test_baseline_constants_unchanged() -> None:
    assert SONNET_46_PRICE_PER_TURN_JPY == 3.75
    assert OPUS_47_PRICE_PER_TURN_JPY == 9.375
    assert HAIKU_45_PRICE_PER_TURN_JPY == 1.5


def test_sonnet_turn_counts_per_tier() -> None:
    assert SONNET_TURNS_BY_TIER[PricingTier.A] == 1
    assert SONNET_TURNS_BY_TIER[PricingTier.B] == 2
    assert SONNET_TURNS_BY_TIER[PricingTier.C] == 4
    assert SONNET_TURNS_BY_TIER[PricingTier.D] == 8
