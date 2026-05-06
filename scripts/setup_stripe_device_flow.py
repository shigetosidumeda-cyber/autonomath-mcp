#!/usr/bin/env python3
# ===========================================================================
# RUNBOOK — run this script once per Stripe environment before launch
# ===========================================================================
#
# Prerequisites:
#   1. A live Stripe account with metered billing enabled.
#   2. The STRIPE_SECRET_KEY env var set to the live secret key
#      (sk_live_...). Test key (sk_test_...) is fine for dry-run / staging.
#
# Steps:
#   .venv/bin/python scripts/setup_stripe_device_flow.py
#
# The script will:
#   - Look up or create the ¥3/req metered Price (lookup_key="per_request_v3")
#   - Print the Price ID that must go into STRIPE_PRICE_PER_REQUEST
#
# After running, set the emitted value as a Fly secret:
#   fly secrets set STRIPE_PRICE_PER_REQUEST=price_... -a <your-fly-app>
#
# The device flow (POST /v1/device/complete) and the main checkout flow
# (POST /v1/billing/checkout) both read STRIPE_PRICE_PER_REQUEST from env.
# Both flows share the same Price — no duplicate Prices needed.
#
# This script does NOT create a webhook endpoint or portal configuration.
# Those are managed by scripts/setup_stripe_compliance_product.py and the
# Stripe Dashboard. Run this script ONCE; re-running is a no-op (idempotent).
# ===========================================================================
"""Ensure Stripe is configured for the device-flow activation page.

Idempotent bootstrap: run this once per Stripe environment (test / live)
to verify the ¥3/req metered Price exists and print the values you need
to put into STRIPE_PRICE_PER_REQUEST. If the Price already exists
(lookup_key="per_request_v3") this script is a no-op + sanity check.

What it does:

    1. Looks up the metered Price by lookup_key="per_request_v3".
    2. If absent, creates it (Product + Price, ¥3/req 外税).
    3. Prints out the STRIPE_PRICE_PER_REQUEST value to paste into .env /
       Fly secrets.
    4. Notes on Apple Pay / Google Pay: Stripe Checkout enables them
       automatically when `automatic_payment_methods` is active in the
       dashboard — we do NOT set a hardcoded `payment_method_types` list
       (that would SUPPRESS the wallets). This script just confirms the
       live price is reachable; the actual Checkout call is in
       src/jpintel_mcp/api/billing.py::create_checkout.

Reuse note: we deliberately share the SAME price with the main billing
flow — one metered Price per environment. The device flow issues an
`am_device_` prefixed key, but the Stripe subscription is identical to
what /v1/billing/checkout creates. This keeps dunning / webhook code in
api/billing.py as the single source of truth for subscription lifecycle.

Usage:
    .venv/bin/python scripts/setup_stripe_device_flow.py          # test mode (default env)
    STRIPE_SECRET_KEY=sk_live_... .venv/bin/python scripts/setup_stripe_device_flow.py
"""

from __future__ import annotations

import os
import sys

try:
    import stripe
except ImportError:
    print('FAIL  stripe SDK not installed — run `pip install -e ".[dev]"`', file=sys.stderr)
    sys.exit(2)

# Match billing/stripe_usage.py — pinned to 2024-11-20.acacia for legacy
# metered usage_records compatibility. If this script ever lives under a
# newer api_version, the Price create flow below must move to Meter-based
# billing. Keeping the pin here makes the mismatch obvious.
STRIPE_API_VERSION = os.environ.get("STRIPE_API_VERSION", "2024-11-20.acacia")

# Canonical lookup_key. DO NOT change this value casually — it is the
# reuse hook that prevents accidental duplicate Prices across runs.
# v3 corresponds to the live ¥3/req Price (price_1TPw8sL3qgB3rEtw4GyG4DHi
# per docs/_internal/COORDINATION_2026-04-25.md).
LOOKUP_KEY = "per_request_v3"

# Price shape: ¥3 per unit, JPY, metered (recurring.usage_type=metered),
# tax_behavior=exclusive (外税). Stripe's JPY is zero-decimal so
# unit_amount is in yen directly. ¥3 税別 (¥3.30 税込 with JCT 10%).
UNIT_AMOUNT_JPY = 3


def _configure() -> str:
    secret = os.environ.get("STRIPE_SECRET_KEY") or ""
    if not secret:
        print("FAIL  STRIPE_SECRET_KEY is not set", file=sys.stderr)
        sys.exit(2)
    stripe.api_key = secret
    stripe.api_version = STRIPE_API_VERSION
    return secret


def _find_price() -> stripe.Price | None:
    prices = stripe.Price.list(lookup_keys=[LOOKUP_KEY], limit=10, active=True)
    data = prices.get("data", []) if isinstance(prices, dict) else prices.data
    if not data:
        return None
    # Sort by created_at desc and return the newest. We never create more
    # than one with this lookup_key, but a defensive pick works if an
    # operator accidentally created a second one by hand.
    active = [p for p in data if getattr(p, "active", True)]
    if not active:
        return None
    active.sort(key=lambda p: getattr(p, "created", 0), reverse=True)
    return active[0]


def _create_product_and_price() -> stripe.Price:
    product = stripe.Product.create(
        name="AutonoMath — ¥3/req metered",
        description=(
            "AutonoMath Japanese public-program API + MCP server. "
            "Pure metered ¥3/request 税別 (¥3.30 税込). Operated by "
            "Bookyou株式会社 (T8010001213708)."
        ),
    )
    price = stripe.Price.create(
        product=product.id,
        currency="jpy",
        unit_amount=UNIT_AMOUNT_JPY,
        recurring={
            "interval": "month",
            "usage_type": "metered",
            "aggregate_usage": "sum",
        },
        lookup_key=LOOKUP_KEY,
        tax_behavior="exclusive",
        nickname="AutonoMath per-request v2 (¥1, exclusive)",
    )
    return price


def main() -> int:
    secret = _configure()
    mode = "live" if secret.startswith("sk_live_") else "test"
    print(f"[setup_stripe_device_flow] mode={mode} api_version={STRIPE_API_VERSION}")

    existing = _find_price()
    if existing is not None:
        price = existing
        print(f"[setup_stripe_device_flow] REUSE existing Price: {price.id}")
    else:
        print(f"[setup_stripe_device_flow] no Price with lookup_key={LOOKUP_KEY!r}; creating one")
        price = _create_product_and_price()
        print(f"[setup_stripe_device_flow] CREATED Price: {price.id}")

    # Emit the one env var the device-flow / billing code needs.
    print("")
    print("=== Paste into .env / Fly secrets ===")
    print(f"STRIPE_PRICE_PER_REQUEST={price.id}")
    print("")
    print("Apple Pay / Google Pay:")
    print("  Enabled automatically by Stripe Checkout's")
    print("  'automatic_payment_methods' flag — no hardcoded payment_method_types")
    print("  list in src/jpintel_mcp/api/billing.py::create_checkout.")
    print("  Configure wallet availability in Stripe Dashboard →")
    print("    Settings → Payments → Payment methods → 'Wallets'.")
    print("")
    print("Device flow reuse:")
    print("  site/go.html POSTs /v1/billing/checkout with a customer_email")
    print("  and the same metered Price. The device_code activation happens")
    print("  after Stripe redirects back with session_id — see device_flow.py::complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
