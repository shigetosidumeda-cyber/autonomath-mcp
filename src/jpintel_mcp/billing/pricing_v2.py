"""F4 4-tier outcome-band pricing (v2) — additive to ¥3/req metered baseline.

Tier A=¥3 atomic / B=¥10 bundle / C=¥30 composed / D=¥100..¥1000 pack.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final


class PricingTier(StrEnum):
    """Canonical pricing tier letters for the F4 4-tier outcome model."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"


PRICE_BY_TIER: Final[MappingProxyType[PricingTier, int]] = MappingProxyType(
    {
        PricingTier.A: 3,
        PricingTier.B: 10,
        PricingTier.C: 30,
        PricingTier.D: 800,
    }
)


TIER_BAND_FLOOR: Final[MappingProxyType[PricingTier, int]] = MappingProxyType(
    {
        PricingTier.A: 3,
        PricingTier.B: 10,
        PricingTier.C: 30,
        PricingTier.D: 100,
    }
)

TIER_BAND_CEIL: Final[MappingProxyType[PricingTier, int]] = MappingProxyType(
    {
        PricingTier.A: 3,
        PricingTier.B: 10,
        PricingTier.C: 30,
        PricingTier.D: 1000,
    }
)


_POSTURE_TO_TIER: Final[MappingProxyType[str, PricingTier | None]] = MappingProxyType(
    {
        "free_preview": None,
        "accepted_artifact_low": PricingTier.D,
        "accepted_artifact_standard": PricingTier.D,
        "accepted_artifact_premium": PricingTier.D,
        "accepted_artifact_csv_overlay": PricingTier.D,
    }
)


def price_for_tier(tier: PricingTier | str) -> int | None:
    """Return the canonical yen price for ``tier``."""
    try:
        canonical = PricingTier(tier) if not isinstance(tier, PricingTier) else tier
    except ValueError:
        return None
    return PRICE_BY_TIER[canonical]


def tier_for_outcome_posture(posture: str) -> PricingTier | None:
    """Map a legacy ``accepted_artifact_*`` posture to the v2 tier letter."""
    return _POSTURE_TO_TIER.get(posture)


def validate_pack_price(tier: PricingTier, price_jpy: int) -> bool:
    """Return True iff ``price_jpy`` is inside the tier's yen band."""
    if price_jpy < TIER_BAND_FLOOR[tier]:
        return False
    return price_jpy <= TIER_BAND_CEIL[tier]


def stripe_metering_quantity_for_tier(
    tier: PricingTier | str,
    *,
    call_count: int = 1,
) -> int:
    """Return the Stripe metered ``quantity`` to report for ``tier``."""
    price = price_for_tier(tier)
    if price is None:
        raise ValueError(f"unknown tier: {tier!r}")
    if call_count < 1:
        raise ValueError(f"call_count must be >= 1, got {call_count}")
    base = PRICE_BY_TIER[PricingTier.A]
    units_per_call = (price + base - 1) // base
    return units_per_call * call_count


def x402_price_yen_for_tier(tier: PricingTier | str) -> int:
    """Return the yen price to wire into an ``X402Challenge.price_yen``."""
    price = price_for_tier(tier)
    if price is None:
        raise ValueError(f"unknown tier: {tier!r}")
    if not (1 <= price <= 1_000_000):
        raise ValueError(f"tier {tier!r} price {price} outside x402 [1, 1_000_000] window")
    return price


def all_tiers() -> tuple[PricingTier, ...]:
    """Return the four canonical tiers in canonical order (A → D)."""
    return (PricingTier.A, PricingTier.B, PricingTier.C, PricingTier.D)


def tier_band(tier: PricingTier) -> tuple[int, int]:
    """Return ``(floor, ceil)`` yen band for ``tier``."""
    return (TIER_BAND_FLOOR[tier], TIER_BAND_CEIL[tier])


__all__ = [
    "PRICE_BY_TIER",
    "PricingTier",
    "TIER_BAND_CEIL",
    "TIER_BAND_FLOOR",
    "all_tiers",
    "price_for_tier",
    "stripe_metering_quantity_for_tier",
    "tier_band",
    "tier_for_outcome_posture",
    "validate_pack_price",
    "x402_price_yen_for_tier",
]
