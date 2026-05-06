#!/usr/bin/env python3
"""Delete the OLD Stripe webhook endpoint after F2 rotation (2026-04-25).

Run AFTER:
  1. F3 has deployed the new STRIPE_WEBHOOK_SECRET (whsec_DB...).
  2. A real webhook event has been delivered + signature-verified to the new endpoint.

Usage (run inside Fly machine where STRIPE_SECRET_KEY=sk_live_... is in env):
  python scripts/delete_old_stripe_webhook.py

The OLD endpoint was created 2026-03-?? and contains the compromised signing secret
that was previously committed to docs/_internal/stripe_tax_setup.md (since redacted).
"""

from __future__ import annotations

import os
import sys

import stripe

OLD_ENDPOINT_ID = "we_1TPAGjL3qgB3rEtw1fh7QHjV"
NEW_ENDPOINT_ID = "we_1TQ1sML3qgB3rEtw9wlLYGUs"


def main() -> int:
    sk = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not sk.startswith("sk_live_"):
        print(f"FAIL  STRIPE_SECRET_KEY missing or wrong mode (prefix={sk[:7]})", file=sys.stderr)
        return 1
    stripe.api_key = sk

    # Sanity: confirm new endpoint exists and is enabled before deleting old.
    new_ep = stripe.WebhookEndpoint.retrieve(NEW_ENDPOINT_ID)
    if new_ep.status != "enabled":
        print(
            f"FAIL  new endpoint {NEW_ENDPOINT_ID} status={new_ep.status} (expected enabled). Aborting.",
            file=sys.stderr,
        )
        return 2
    print(f"INFO  new endpoint {NEW_ENDPOINT_ID} enabled. Proceeding to delete old.", flush=True)

    deleted = stripe.WebhookEndpoint.delete(OLD_ENDPOINT_ID)
    print(f"OK    deleted old endpoint id={deleted.id} deleted={deleted.deleted}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
