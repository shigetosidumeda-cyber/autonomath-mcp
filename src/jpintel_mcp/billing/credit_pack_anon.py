"""Anonymous over-quota ad-hoc credit packs (small ¥300 / ¥1,500 / ¥3,000 sizes).

Distinct from the enterprise lump-sum lane in `credit_pack.py` (¥300K / ¥1M /
¥3M) — this surface is for the **anonymous 3 req/IP/day** path who hit the
free ceiling and want a one-shot top-up *without* signing up for an API key
or a Stripe subscription.

Strict ¥3/req metered pricing remains unchanged. This is purely an optional
ad-hoc credit; no tier, no monthly plan, no minimum. The pack is a Stripe
one-time `Price` (mode='payment'), redeemed via Stripe Checkout. The redeem
code is then bound to the buyer's IP (or to an issued lightweight token)
and decremented per request on the same metered path used by API-key users
— the only difference is the credit source (`credit_pack_id`) recorded in
the `usage_events` row.

Pack lineup (matches pricing.html and migration 215):

  * ¥300   → 100 req   (¥3.00/req — list price, zero discount)
  * ¥1,500 → 500 req   (¥3.00/req — list price, zero discount)
  * ¥3,000 → 1,000 req (¥3.00/req — list price, zero discount)

There is **no per-pack discount** because that would be a tier in disguise.
Volume rebate at the 1M req/month threshold is handled retrospectively by
`scripts/cron/volume_rebate.py` via Stripe Credit Notes (see D2 doc).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import types


logger = logging.getLogger("jpintel.billing.credit_pack_anon")

# Pack lineup. The req count is derived from amount_jpy / ¥3 (list price);
# keep the mapping explicit so a future price change cannot silently shift
# pack contents without an audit.
ANON_PACK_SIZES_JPY: frozenset[int] = frozenset({300, 1_500, 3_000})
ANON_PACK_REQ_COUNT: dict[int, int] = {
    300: 100,
    1_500: 500,
    3_000: 1_000,
}

# Stripe metadata key identifying an anonymous credit-pack invoice / checkout
# session in the webhook handler. Distinct from the enterprise
# `credit_pack` kind so the two flows never confuse the dispatch logic.
ANON_CREDIT_PACK_METADATA_KIND: str = "credit_pack_anon"


class AnonCreditPackPurchaseRequest(BaseModel):
    """POST /v1/billing/credit/anon/purchase body."""

    amount_jpy: Literal[300, 1_500, 3_000] = Field(
        ..., description="Pack size in JPY. One of 300 / 1500 / 3000."
    )
    return_url: str | None = Field(
        default=None,
        max_length=512,
        description="Optional URL Stripe redirects to after checkout.",
    )


class AnonCreditPackPurchaseResponse(BaseModel):
    """POST /v1/billing/credit/anon/purchase response."""

    checkout_url: str
    req_count: int
    amount_jpy: int


def pack_req_count(amount_jpy: int) -> int:
    """Return the request count granted by a pack of `amount_jpy`."""
    if amount_jpy not in ANON_PACK_SIZES_JPY:
        raise ValueError(
            f"amount_jpy must be one of {sorted(ANON_PACK_SIZES_JPY)}, got {amount_jpy}"
        )
    return ANON_PACK_REQ_COUNT[amount_jpy]


def create_anon_credit_pack_checkout(
    stripe_client: types.ModuleType,
    amount_jpy: int,
    *,
    success_url: str,
    cancel_url: str,
    idempotency_key: str | None = None,
) -> Any:
    """Create a Stripe Checkout Session for an anonymous ad-hoc credit pack.

    Uses `mode='payment'` (one-time) with `price_data` inline so we do not
    have to pre-provision a Stripe Price object per pack tier — that would
    couple Stripe dashboard config to deploy. Metadata carries the pack size
    + req_count so the webhook can re-derive both without re-reading line
    items.
    """
    if amount_jpy not in ANON_PACK_SIZES_JPY:
        raise ValueError(
            f"amount_jpy must be one of {sorted(ANON_PACK_SIZES_JPY)}, got {amount_jpy}"
        )
    req_count = ANON_PACK_REQ_COUNT[amount_jpy]
    description = f"jpcite anonymous credit pack ¥{amount_jpy:,} ({req_count} req)"
    metadata = {
        "kind": ANON_CREDIT_PACK_METADATA_KIND,
        "amount_jpy": str(amount_jpy),
        "req_count": str(req_count),
    }
    create_kwargs: dict[str, Any] = {
        "mode": "payment",
        "line_items": [
            {
                "quantity": 1,
                "price_data": {
                    "currency": "jpy",
                    "unit_amount": amount_jpy,
                    "product_data": {
                        "name": description,
                        "metadata": metadata,
                    },
                },
            }
        ],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": metadata,
        "payment_intent_data": {"metadata": metadata},
    }
    if idempotency_key:
        create_kwargs["idempotency_key"] = idempotency_key
    return stripe_client.checkout.Session.create(**create_kwargs)


def metadata_req_count(obj: Any) -> int | None:
    """Read `metadata.req_count` from a Stripe object / dict."""
    md: Any
    if isinstance(obj, dict):
        md = obj.get("metadata") or {}
    else:
        md = getattr(obj, "metadata", None) or {}
    raw: Any = md.get("req_count") if isinstance(md, dict) else getattr(md, "req_count", None)
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def is_anon_credit_pack_event(obj: Any) -> bool:
    """True if a Stripe checkout.session / invoice event is an anon credit pack."""
    md: Any
    if isinstance(obj, dict):
        md = obj.get("metadata") or {}
    else:
        md = getattr(obj, "metadata", None) or {}
    kind: Any = md.get("kind") if isinstance(md, dict) else getattr(md, "kind", None)
    return bool(kind == ANON_CREDIT_PACK_METADATA_KIND)


def default_success_url() -> str:
    """Resolve the success redirect URL from env, defaulting to the public site."""
    return os.environ.get(
        "JPCITE_CREDIT_PACK_SUCCESS_URL",
        "https://jpcite.com/credit-pack-success.html",
    )


def default_cancel_url() -> str:
    """Resolve the cancel redirect URL from env, defaulting to pricing."""
    return os.environ.get(
        "JPCITE_CREDIT_PACK_CANCEL_URL",
        "https://jpcite.com/pricing.html#api-paid",
    )


__all__ = [
    "ANON_CREDIT_PACK_METADATA_KIND",
    "ANON_PACK_REQ_COUNT",
    "ANON_PACK_SIZES_JPY",
    "AnonCreditPackPurchaseRequest",
    "AnonCreditPackPurchaseResponse",
    "create_anon_credit_pack_checkout",
    "default_cancel_url",
    "default_success_url",
    "is_anon_credit_pack_event",
    "metadata_req_count",
    "pack_req_count",
]
