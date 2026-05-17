"""Agent-economy-first 4-tier pricing (v3) — re-balances v2 billable_units.

Background
----------
V2 (F4) layered four outcome bands (¥3 / ¥10 / ¥30 / ¥100..¥1000) on top of the
canonical ¥3/req metered baseline. Empirically agents already pay Sonnet 4.6
≈¥3.75 per turn (LLM-self-compose at the user side). V2's Tier B-D priced at
3x / 10x / 33-333x quickly broke agent economics: a Sonnet 4-turn compose at
¥15 won over a jpcite Tier C ¥30 call, and a Sonnet 8-turn workflow at ¥30 won
over Tier D ¥100+ packs. The agent skipped jpcite and the SaaS-on-top stack
turned upside down.

V3 rebalances the billable_units so each tier remains **strictly cheaper than**
the equivalent Sonnet 4.6 self-compose, while still letting jpcite recover
upstream corpus-build cost via composition density. Unit price stays ¥3
(CLAUDE.md non-negotiable); only `billable_units` per tier changes.

The four tiers (V3)
-------------------
* **Tier A — Atomic (1 unit = ¥3 / call)**: 1 atomic MCP / REST call.
  - vs Sonnet 1 turn ¥3.75 → jpcite ¥3 wins by ¥0.75.
* **Tier B — Composed (2 units = ¥6 / call)**: 2-5 atomic calls composed at
  server-side. (V2 was 3 units / ¥9.)
  - vs Sonnet 2 turn ¥7.50 → jpcite ¥6 wins by ¥1.50.
* **Tier C — Heavy (4 units = ¥12 / call)**: 4-13 atomic calls composed in a
  rule_tree. (V2 was 10 units / ¥30.)
  - vs Sonnet 4 turn ¥15 → jpcite ¥12 wins by ¥3.
* **Tier D — Workflow (10 units = ¥30 / call)**: full composed deliverable
  workflow. (V2 was 33-333 units / ¥99-¥999.)
  - vs Sonnet 8 turn ¥30 → jpcite ¥30 **at parity** but with Opus-grade
    quality (≈ Opus 4 turn ¥75 → 60% cheaper).

D-tier band is `[¥30, ¥120]` so the A5 multi-pack bundle (2-4 sub-D packs in
one logical call) can stay one call: A5 = 20..40 billable_units = ¥60..¥120.

Migration vs V2
---------------
* V2 (B=3 / C=10 / D=33-333) → V3 (B=2 / C=4 / D=10).
* Non-destructive: `pricing_version` field tags each envelope so callers
  can pin to v2 or v3 explicitly during rollout.

Non-negotiable
--------------
* Unit price stays ¥3 (CLAUDE.md). Only ``billable_units`` changes.
* No subscription SKU.
* No LLM imports — pure Python lookup.
* Backwards compatible: V2 module untouched; V3 sits alongside it.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from .pricing_v2 import PricingTier

PRICING_VERSION: Final[str] = "v3"

# V3 billable_units + yen prices ----------------------------------------------

#: V3 canonical billable_units per tier. Each unit = ¥3 metered.
BILLABLE_UNITS_BY_TIER: Final[MappingProxyType[PricingTier, int]] = MappingProxyType(
    {
        PricingTier.A: 1,
        PricingTier.B: 2,
        PricingTier.C: 4,
        PricingTier.D: 10,
    }
)

#: V3 canonical yen price per tier. Equal to BILLABLE_UNITS_BY_TIER * ¥3.
PRICE_BY_TIER: Final[MappingProxyType[PricingTier, int]] = MappingProxyType(
    {
        PricingTier.A: 3,
        PricingTier.B: 6,
        PricingTier.C: 12,
        PricingTier.D: 30,
    }
)

TIER_BAND_FLOOR: Final[MappingProxyType[PricingTier, int]] = MappingProxyType(
    {
        PricingTier.A: 3,
        PricingTier.B: 6,
        PricingTier.C: 12,
        PricingTier.D: 30,
    }
)

TIER_BAND_CEIL: Final[MappingProxyType[PricingTier, int]] = MappingProxyType(
    {
        PricingTier.A: 3,
        PricingTier.B: 6,
        PricingTier.C: 12,
        PricingTier.D: 120,
    }
)


SONNET_46_PRICE_PER_TURN_JPY: Final[float] = 3.75
OPUS_47_PRICE_PER_TURN_JPY: Final[float] = 9.375
HAIKU_45_PRICE_PER_TURN_JPY: Final[float] = 1.5

SONNET_TURNS_BY_TIER: Final[MappingProxyType[PricingTier, int]] = MappingProxyType(
    {
        PricingTier.A: 1,
        PricingTier.B: 2,
        PricingTier.C: 4,
        PricingTier.D: 8,
    }
)


# Lookups ---------------------------------------------------------------------


def billable_units_for_tier(tier: PricingTier | str) -> int | None:
    """Return V3 ``billable_units`` for ``tier`` (``None`` for unknown)."""
    try:
        canonical = PricingTier(tier) if not isinstance(tier, PricingTier) else tier
    except ValueError:
        return None
    return BILLABLE_UNITS_BY_TIER[canonical]


def price_for_tier(tier: PricingTier | str) -> int | None:
    """Return V3 yen price for ``tier`` (``None`` for unknown)."""
    try:
        canonical = PricingTier(tier) if not isinstance(tier, PricingTier) else tier
    except ValueError:
        return None
    return PRICE_BY_TIER[canonical]


def validate_pack_price(tier: PricingTier, price_jpy: int) -> bool:
    """Return ``True`` iff ``price_jpy`` is inside the V3 tier band."""
    if price_jpy < TIER_BAND_FLOOR[tier]:
        return False
    return price_jpy <= TIER_BAND_CEIL[tier]


def stripe_metering_quantity_for_tier(
    tier: PricingTier | str,
    *,
    call_count: int = 1,
) -> int:
    """Return Stripe metered ``quantity`` for ``tier`` (V3 units * call_count)."""
    units = billable_units_for_tier(tier)
    if units is None:
        raise ValueError(f"unknown tier: {tier!r}")
    if call_count < 1:
        raise ValueError(f"call_count must be >= 1, got {call_count}")
    return units * call_count


def x402_price_yen_for_tier(tier: PricingTier | str) -> int:
    """Return yen price to wire into ``X402Challenge.price_yen``."""
    price = price_for_tier(tier)
    if price is None:
        raise ValueError(f"unknown tier: {tier!r}")
    if not (1 <= price <= 1_000_000):
        raise ValueError(f"tier {tier!r} price {price} outside x402 window")
    return price


def migrate_v2_units_to_v3(v2_units: int) -> int:
    """Convert legacy V2 billable_units to V3 equivalents (closest-band)."""
    if v2_units <= 1:
        return 1
    if v2_units <= 5:
        return 2
    if v2_units <= 20:
        return 4
    return 10


def all_tiers() -> tuple[PricingTier, ...]:
    return (PricingTier.A, PricingTier.B, PricingTier.C, PricingTier.D)


def tier_band(tier: PricingTier) -> tuple[int, int]:
    return (TIER_BAND_FLOOR[tier], TIER_BAND_CEIL[tier])


# 3-baseline value_proxy ------------------------------------------------------


def sonnet_self_compose_price_jpy(tier: PricingTier | str) -> float:
    try:
        canonical = PricingTier(tier) if not isinstance(tier, PricingTier) else tier
    except ValueError as exc:
        raise ValueError(f"unknown tier: {tier!r}") from exc
    return SONNET_TURNS_BY_TIER[canonical] * SONNET_46_PRICE_PER_TURN_JPY


def opus_self_compose_price_jpy(tier: PricingTier | str) -> float:
    try:
        canonical = PricingTier(tier) if not isinstance(tier, PricingTier) else tier
    except ValueError as exc:
        raise ValueError(f"unknown tier: {tier!r}") from exc
    return SONNET_TURNS_BY_TIER[canonical] * OPUS_47_PRICE_PER_TURN_JPY


def haiku_self_compose_price_jpy(tier: PricingTier | str) -> float:
    try:
        canonical = PricingTier(tier) if not isinstance(tier, PricingTier) else tier
    except ValueError as exc:
        raise ValueError(f"unknown tier: {tier!r}") from exc
    return SONNET_TURNS_BY_TIER[canonical] * HAIKU_45_PRICE_PER_TURN_JPY


def jpcite_saving_vs_sonnet_pct(tier: PricingTier | str) -> float:
    jpcite_price = price_for_tier(tier)
    if jpcite_price is None:
        raise ValueError(f"unknown tier: {tier!r}")
    sonnet_price = sonnet_self_compose_price_jpy(tier)
    return round(100.0 * (sonnet_price - jpcite_price) / sonnet_price, 1)


def jpcite_saving_vs_opus_pct(tier: PricingTier | str) -> float:
    jpcite_price = price_for_tier(tier)
    if jpcite_price is None:
        raise ValueError(f"unknown tier: {tier!r}")
    opus_price = opus_self_compose_price_jpy(tier)
    return round(100.0 * (opus_price - jpcite_price) / opus_price, 1)


def agent_compete_table() -> tuple[dict[str, float | int | str], ...]:
    """Return the canonical jpcite-vs-LLM decision matrix (3-baseline)."""
    rows: list[dict[str, float | int | str]] = []
    for tier in all_tiers():
        rows.append(
            {
                "tier": tier.value,
                "billable_units": BILLABLE_UNITS_BY_TIER[tier],
                "jpcite_price_jpy": PRICE_BY_TIER[tier],
                "sonnet_turns": SONNET_TURNS_BY_TIER[tier],
                "sonnet_price_jpy": round(sonnet_self_compose_price_jpy(tier), 2),
                "sonnet_saving_pct": jpcite_saving_vs_sonnet_pct(tier),
                "opus_price_jpy": round(opus_self_compose_price_jpy(tier), 2),
                "opus_saving_pct": jpcite_saving_vs_opus_pct(tier),
                "haiku_price_jpy": round(haiku_self_compose_price_jpy(tier), 2),
            }
        )
    return tuple(rows)


__all__ = [
    "BILLABLE_UNITS_BY_TIER",
    "HAIKU_45_PRICE_PER_TURN_JPY",
    "OPUS_47_PRICE_PER_TURN_JPY",
    "PRICE_BY_TIER",
    "PRICING_VERSION",
    "PricingTier",
    "SONNET_46_PRICE_PER_TURN_JPY",
    "SONNET_TURNS_BY_TIER",
    "TIER_BAND_CEIL",
    "TIER_BAND_FLOOR",
    "agent_compete_table",
    "all_tiers",
    "billable_units_for_tier",
    "haiku_self_compose_price_jpy",
    "jpcite_saving_vs_opus_pct",
    "jpcite_saving_vs_sonnet_pct",
    "migrate_v2_units_to_v3",
    "opus_self_compose_price_jpy",
    "price_for_tier",
    "sonnet_self_compose_price_jpy",
    "stripe_metering_quantity_for_tier",
    "tier_band",
    "validate_pack_price",
    "x402_price_yen_for_tier",
]
