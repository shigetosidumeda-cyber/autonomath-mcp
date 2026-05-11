"""Volume rebate tier helper (Wave 21 D4).

Applies a per-request rebate on the base ¥3/req metered price when the
caller's billing-period usage crosses preset thresholds. This is NOT a
discrete SKU — the rebate is computed at usage-report time and surfaced to
Stripe as a ``Subscription Item`` price tier (legacy metered ``tiers``
attribute).

Tiered structure (locked 2026-05-11):

  * 0 …… <  10,000 req / month → ¥3.00 / req (base)
  * 10,000 … < 100,000 req     → ¥2.50 / req (-17%)
  * ≥ 100,000 req              → ¥2.00 / req (-33%)

The rebate is **graduated** (also called "progressive" in Stripe terms):
each request is priced at the tier rate that covers its index within the
period. This matches the Stripe ``tiers_mode='graduated'`` semantics and
keeps the rebate proportional even mid-tier. Volume rebate stacks with
the credit pack (``credit_pack.py``) and yearly prepay
(``yearly_prepay.py``) — when a customer has prepay credit, usage is debited
against the credit first; the volume rebate then applies to whatever burst
spills past the prepay envelope.

Constraints
-----------
- Pure Python, no Stripe SDK import here (caller in
  ``src/jpintel_mcp/billing/stripe_usage.py`` reads the resulting tier list
  and POSTs the matching ``usage_records`` payload).
- All amounts in JPY (zero-decimal) — never store as float.
- Idempotent + side-effect-free: same inputs → same outputs. Operator
  cron is the SOT for monthly reset; this module computes a snapshot only.
- No LLM. Memory ``feedback_no_operator_llm_api`` strictly enforced.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

logger = logging.getLogger("jpintel.billing.volume_rebate")

# ---------------------------------------------------------------------------
# Tier table — bump in lockstep with `docs/_internal/pricing_v0.3.4.md` +
# ToS §19 + the Stripe Product/Price meta fields.
# ---------------------------------------------------------------------------

BASE_RATE_JPY: Final[int] = 3  # ¥3/req (税別)
MID_TIER_FROM: Final[int] = 10_000
TOP_TIER_FROM: Final[int] = 100_000

MID_TIER_RATE_JPY: Final[Decimal] = Decimal("2.50")  # 17% off
TOP_TIER_RATE_JPY: Final[Decimal] = Decimal("2.00")  # 33% off


@dataclass(frozen=True)
class RebateTier:
    """One row of the volume-rebate schedule."""

    up_to_inclusive: int | None  # None = "∞"
    unit_amount_jpy: Decimal


REBATE_SCHEDULE: tuple[RebateTier, ...] = (
    RebateTier(up_to_inclusive=MID_TIER_FROM - 1, unit_amount_jpy=Decimal(BASE_RATE_JPY)),
    RebateTier(up_to_inclusive=TOP_TIER_FROM - 1, unit_amount_jpy=MID_TIER_RATE_JPY),
    RebateTier(up_to_inclusive=None, unit_amount_jpy=TOP_TIER_RATE_JPY),
)


@dataclass(frozen=True)
class RebateApplication:
    """Result of ``apply_rebate(usage_qty)``."""

    qty: int
    total_jpy: Decimal
    avg_rate_jpy: Decimal
    breakdown: tuple[tuple[int, Decimal, Decimal], ...] = field(default_factory=tuple)
    # breakdown rows: (qty_in_tier, tier_rate, subtotal_for_tier)

    def to_dict(self) -> dict[str, object]:
        return {
            "qty": self.qty,
            "total_jpy": str(self.total_jpy),
            "avg_rate_jpy": str(self.avg_rate_jpy),
            "breakdown": [
                {"qty": q, "rate_jpy": str(r), "subtotal_jpy": str(s)}
                for (q, r, s) in self.breakdown
            ],
        }


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def apply_rebate(usage_qty: int) -> RebateApplication:
    """Compute graduated rebate total for ``usage_qty`` requests this period.

    >>> r = apply_rebate(9_999)
    >>> int(r.total_jpy)
    29997
    >>> r2 = apply_rebate(10_000)
    >>> int(r2.total_jpy)  # 9999*3 + 1*2.5
    30000
    >>> r3 = apply_rebate(150_000)
    >>> int(r3.total_jpy)  # 9999*3 + 90000*2.5 + 50001*2
    354999
    """
    if usage_qty <= 0:
        return RebateApplication(qty=0, total_jpy=Decimal(0), avg_rate_jpy=Decimal(0))

    breakdown: list[tuple[int, Decimal, Decimal]] = []
    remaining = usage_qty
    cursor = 0
    for tier in REBATE_SCHEDULE:
        upper = tier.up_to_inclusive
        # tier covers indices [cursor+1 … upper]; qty of indices = upper - cursor
        if upper is None:
            qty_in = remaining
        else:
            qty_in = min(remaining, upper - cursor)
            if qty_in < 0:
                qty_in = 0
        if qty_in <= 0:
            cursor = upper if upper is not None else cursor
            continue
        subtotal = (Decimal(qty_in) * tier.unit_amount_jpy).quantize(Decimal("0.01"))
        breakdown.append((qty_in, tier.unit_amount_jpy, subtotal))
        remaining -= qty_in
        cursor = (upper or cursor) if upper is not None else cursor + qty_in
        if remaining <= 0:
            break

    total = sum((row[2] for row in breakdown), start=Decimal(0))
    avg = (total / Decimal(usage_qty)).quantize(Decimal("0.0001")) if usage_qty else Decimal(0)
    return RebateApplication(
        qty=usage_qty,
        total_jpy=total,
        avg_rate_jpy=avg,
        breakdown=tuple(breakdown),
    )


def stripe_tier_payload() -> list[dict[str, object]]:
    """Render the tier schedule in the Stripe ``Price.tiers`` shape.

    Stripe wants minor units; JPY is zero-decimal so unit_amount IS the yen
    value. Final ``up_to='inf'`` is required by Stripe for graduated tiers.
    """
    out: list[dict[str, object]] = []
    for tier in REBATE_SCHEDULE:
        out.append(
            {
                "up_to": "inf" if tier.up_to_inclusive is None else tier.up_to_inclusive + 1,
                "unit_amount_decimal": str(tier.unit_amount_jpy),
                "flat_amount": 0,
            }
        )
    return out


def rate_at_index(req_index_1based: int) -> Decimal:
    """Return the per-req rate that applies to the Nth request this period."""
    if req_index_1based <= 0:
        raise ValueError("req_index_1based must be >= 1")
    for tier in REBATE_SCHEDULE:
        upper = tier.up_to_inclusive
        if upper is None or req_index_1based <= upper + 1:
            return tier.unit_amount_jpy
    return TOP_TIER_RATE_JPY


def describe_schedule_ja() -> str:
    """One-line Japanese summary for the dashboard / billing console."""
    return (
        f"¥{BASE_RATE_JPY}/req → "
        f"{MID_TIER_FROM:,} 件超で ¥{MID_TIER_RATE_JPY}/req (-17%) → "
        f"{TOP_TIER_FROM:,} 件超で ¥{TOP_TIER_RATE_JPY}/req (-33%) — "
        f"月次グラデュエート / credit pack + yearly prepay と stack 可"
    )


__all__ = [
    "BASE_RATE_JPY",
    "MID_TIER_FROM",
    "MID_TIER_RATE_JPY",
    "REBATE_SCHEDULE",
    "RebateApplication",
    "RebateTier",
    "TOP_TIER_FROM",
    "TOP_TIER_RATE_JPY",
    "apply_rebate",
    "describe_schedule_ja",
    "rate_at_index",
    "stripe_tier_payload",
]
