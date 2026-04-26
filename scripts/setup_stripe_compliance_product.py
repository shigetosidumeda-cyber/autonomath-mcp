#!/usr/bin/env python3
"""Idempotent Stripe Product + Price creator for 法令改正アラート (Compliance Alerts).

Creates (or finds) a Stripe Product tagged with
`metadata.autonomath_product = 'compliance_alerts'` and a recurring
Price of ¥500/月 with `lookup_key = 'compliance_alerts_monthly_v1'`.

Re-running is safe: the script searches by metadata + lookup_key and
only creates what is missing.

Requires:
    STRIPE_SECRET_KEY — live or test key (the script prints the Stripe
                        environment it detected before making changes).

Usage:
    .venv/bin/python scripts/setup_stripe_compliance_product.py
    .venv/bin/python scripts/setup_stripe_compliance_product.py --dry-run

Output (stdout, machine-readable):
    product_id=prod_xxx
    price_id=price_xxx
    lookup_key=compliance_alerts_monthly_v1
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

try:
    import stripe
except ImportError:  # pragma: no cover
    print("FAIL stripe SDK not installed — run `pip install -e \".[dev]\"`", file=sys.stderr)
    sys.exit(2)


PRODUCT_NAME = "AutonoMath Compliance Alerts"
PRODUCT_DESCRIPTION = (
    "法令改正アラート — 補助金・電帳法・インボイス・融資・行政処分の変更を24時間以内に通知。"
    " Bookyou 株式会社 (T8010001213708) が運営。¥500/月 税別 (Stripe Tax)。"
)
PRODUCT_METADATA_KEY = "autonomath_product"
PRODUCT_METADATA_VALUE = "compliance_alerts"

PRICE_LOOKUP_KEY = "compliance_alerts_monthly_v1"
PRICE_UNIT_AMOUNT = 500  # ¥500, tax_behavior=exclusive (Stripe Tax adds 消費税)
PRICE_CURRENCY = "jpy"
PRICE_INTERVAL = "month"


def _stripe_mode_label(key: str) -> str:
    if key.startswith("sk_test_"):
        return "test"
    if key.startswith("sk_live_"):
        return "live"
    return "unknown"


def _find_product() -> dict[str, Any] | None:
    """Return the existing compliance_alerts Product, or None.

    We search Stripe's Product list with `active=true` and match on
    `metadata.autonomath_product`. There is no server-side filter for
    metadata, so we paginate client-side. The expected volume is tiny
    (< 20 products total for this account), so a single list call is
    enough.
    """
    for prod in stripe.Product.list(active=True, limit=100).auto_paging_iter():
        md = prod.get("metadata") or {}
        if md.get(PRODUCT_METADATA_KEY) == PRODUCT_METADATA_VALUE:
            return prod
    return None


def _find_price(product_id: str) -> dict[str, Any] | None:
    """Return the existing ¥500/月 recurring Price on this Product, or None.

    Matches by `lookup_key` (unique per account). If the key is present
    elsewhere Stripe will refuse to create a duplicate; we detect that
    case up front.
    """
    prices = stripe.Price.list(lookup_keys=[PRICE_LOOKUP_KEY], limit=5)
    for p in prices.data:
        if p.get("product") == product_id and p.get("active"):
            return p
    return None


def ensure(dry_run: bool) -> dict[str, str]:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        print("FAIL STRIPE_SECRET_KEY not set", file=sys.stderr)
        sys.exit(2)
    stripe.api_key = key
    api_version = os.environ.get("STRIPE_API_VERSION", "2024-11-20.acacia")
    if api_version:
        stripe.api_version = api_version
    mode = _stripe_mode_label(key)
    print(f"stripe_mode={mode}", file=sys.stderr)

    product = _find_product()
    if product is None:
        print("product.missing — will create", file=sys.stderr)
        if dry_run:
            return {"product_id": "(dry-run)", "price_id": "(dry-run)", "lookup_key": PRICE_LOOKUP_KEY}
        product = stripe.Product.create(
            name=PRODUCT_NAME,
            description=PRODUCT_DESCRIPTION,
            metadata={PRODUCT_METADATA_KEY: PRODUCT_METADATA_VALUE},
            tax_code="txcd_10103001",  # SaaS / Software as a Service (JP 10%)
        )
        print(f"product.created id={product['id']}", file=sys.stderr)
    else:
        print(f"product.exists id={product['id']}", file=sys.stderr)

    price = _find_price(product["id"])
    if price is None:
        print("price.missing — will create", file=sys.stderr)
        if dry_run:
            return {
                "product_id": product["id"],
                "price_id": "(dry-run)",
                "lookup_key": PRICE_LOOKUP_KEY,
            }
        price = stripe.Price.create(
            product=product["id"],
            lookup_key=PRICE_LOOKUP_KEY,
            unit_amount=PRICE_UNIT_AMOUNT,
            currency=PRICE_CURRENCY,
            recurring={"interval": PRICE_INTERVAL},
            tax_behavior="exclusive",  # Stripe Tax 適用 — 税別 ¥500, 税込 ¥550
            metadata={PRODUCT_METADATA_KEY: PRODUCT_METADATA_VALUE},
        )
        print(f"price.created id={price['id']}", file=sys.stderr)
    else:
        print(f"price.exists id={price['id']}", file=sys.stderr)

    return {
        "product_id": product["id"],
        "price_id": price["id"],
        "lookup_key": PRICE_LOOKUP_KEY,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="setup_stripe_compliance_product",
        description="Create (or locate) the Stripe Product + Price for Compliance Alerts.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Describe what would be created; do not call Stripe.Create.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        out = ensure(dry_run=args.dry_run)
    except stripe.StripeError as exc:  # pragma: no cover — runtime only
        print(f"FAIL stripe error: {exc}", file=sys.stderr)
        return 1
    for k, v in out.items():
        print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
