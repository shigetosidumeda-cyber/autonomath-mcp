---
title: Stripe Meter Events Migration PoC
updated: 2026-05-04
operator_only: true
category: deploy
---

# Stripe Meter Events Migration PoC Runbook

**Owner**: 梅田茂利 (info@bookyou.net) — solo zero-touch
**Operator**: Bookyou株式会社 (T8010001213708)
**Status**: DRAFT — PoC only. To be merged after `stripe-version-check-weekly`
fires a sunset alert against the current pin (`2024-11-20.acacia`).
**Branch**: `feature/stripe-meter-events-migration`
**Last reviewed**: 2026-05-04

## Why this runbook exists

Our metered billing pipeline pins API version `2024-11-20.acacia` (see
`src/jpintel_mcp/billing/stripe_usage.py`). Stripe's legacy
`subscription_items/{si}/usage_records` endpoint is on a multi-year
deprecation track; the modern surface is **Meter Events** (`/v1/billing/meter_events`).
When `scripts/cron/stripe_version_check.py` (P1) flags either:

  * `Deprecated|Sunset|End of life` against our pin in
    https://docs.stripe.com/upgrades, or
  * Our pin appearing in the upgrades RSS feed in proximity to
    deprecation keywords, or
  * A `Stripe-Sunset-At` header being populated on a probe call,

we open this runbook and execute the migration in the order below. The
PoC branch holds the code skeleton so we are not coding the migration
under deadline pressure — only verifying + flipping flags.

The PoC branch (`feature/stripe-meter-events-migration`) does NOT modify
production code paths until merged. It introduces gated alternates so we
can A/B the legacy `usage_records` path against the new `meter_events`
path on a small slice of traffic before cutting over.

## Pre-flight checklist (do once, ahead of need)

- [ ] Branch `feature/stripe-meter-events-migration` exists and tracks `main`.
- [ ] Stripe Dashboard → Billing → Meters: verify the meter
      `jpcite_request_meter` exists with `event_name = "jpcite.request"`,
      `aggregation = sum`, `payload_value_key = quantity`.
- [ ] Stripe Dashboard → Billing → Products & prices: verify the metered
      price is wired to the new meter (Meter ID populated, NOT the legacy
      "metered usage" plan).
- [ ] `STRIPE_METER_EVENT_NAME` is settable in `flyctl secrets set` (env
      var defined in `src/jpintel_mcp/billing/stripe_usage.py:_meter_event_name`).
- [ ] Sentry rule `webhook_handler_exception_rate` is active so we see any
      regression in the cutover within 1h.

## Migration steps (when sunset is announced)

### Step 1 — Verify alert is real (5 min)

```bash
# Re-run the check manually to confirm the hit is reproducible.
flyctl ssh console -a autonomath-api -C \
  "/opt/venv/bin/python /app/scripts/cron/stripe_version_check.py"
# Inspect Sentry inbox for `stripe_api_version_deprecated_in_docs`
# / `stripe_api_version_in_rss_deprecation` / `stripe_api_version_sunset_header_present`.
```

If only one of three signals fires and `Stripe-Sunset-At` is empty, you
have months of runway. If `Stripe-Sunset-At` is populated, the deadline
is at the value of that header.

### Step 2 — Upgrade pin to the latest API version (15 min)

The Meter Events API is available on every API version released after
2024-06-20. Bumping the pin alone unblocks meter_events without immediately
removing the legacy `usage_records` path.

```bash
git checkout feature/stripe-meter-events-migration
git pull origin feature/stripe-meter-events-migration
# Update PIN in three places (must stay in sync):
#   1. src/jpintel_mcp/billing/stripe_usage.py — stripe.api_version
#   2. src/jpintel_mcp/api/billing.py — stripe.api_version
#   3. scripts/cron/stripe_version_check.py — PIN constant
# Then run the test suite locally; webhook tests must still pass.
.venv/bin/pytest tests/billing tests/api/test_billing.py -x
```

### Step 3 — Wire the meter_events shim behind a flag (30 min)

In `src/jpintel_mcp/billing/stripe_usage.py`, add a branch:

```python
if os.environ.get("STRIPE_USE_METER_EVENTS", "").lower() in {"1", "true", "yes"}:
    # New path: POST /v1/billing/meter_events with payload
    #   event_name=STRIPE_METER_EVENT_NAME (default "jpcite.request")
    #   payload={"value": str(quantity), "stripe_customer_id": customer_id}
    #   identifier=billing_idempotency_key  (replaces idempotency_key)
    stripe.billing.MeterEvent.create(
        event_name=os.environ.get("STRIPE_METER_EVENT_NAME", "jpcite.request"),
        payload={"value": str(quantity), "stripe_customer_id": customer_id},
        identifier=billing_idempotency_key,
    )
else:
    # Legacy path retained until we cut all subscriptions over.
    stripe.SubscriptionItem.create_usage_record(...)
```

Same flag gate goes in `scripts/cron/stripe_usage_backfill.py`'s worker
shim (the worker calls into `stripe_usage.report_usage_async`, so the
flag at the source covers both hot path and backfill).

### Step 4 — A/B test on 1 customer (24 h)

```bash
# Pick the operator's own subscription as the canary.
flyctl secrets set STRIPE_USE_METER_EVENTS=true STRIPE_METER_EVENT_NAME=jpcite.request
# Wait one billing cycle (or 24h, whichever is shorter).
# Verify in Stripe Dashboard → Billing → Subscriptions:
#   - Usage on canary subscription matches our DB usage_events count for the window.
#   - No "metered_usage_record_invalid" or "no_meter_for_event" errors in
#     Stripe Events log.
```

### Step 5 — Cut over (5 min, after canary green)

```bash
# Already on. Just verify all newly-issued subscriptions use the new
# metered price (not the legacy one). Stripe Checkout payload uses
# settings.stripe_price_id — point that at the meter-backed price ID.
flyctl secrets set STRIPE_PRICE_ID=price_<new_meter_backed>
# Stripe migrates existing subscriptions on next renewal automatically
# when the new price is set on the product. No bulk rewrite needed.
```

### Step 6 — Drop the legacy branch (post 90-day stability)

After 90 days with zero `metered_usage_record_*` errors in Sentry, delete
the `if STRIPE_USE_METER_EVENTS` branch and the env var, leaving only the
meter_events path. Bump `pyproject.toml` minor version, document in
CHANGELOG.md.

## Rollback

If the canary shows usage drift > 5% between our `usage_events` and
Stripe's reported meter total within 24h:

```bash
flyctl secrets unset STRIPE_USE_METER_EVENTS
# Re-deploy will go back to the legacy usage_records path on the same pin.
# stripe_usage_backfill cron will heal any rows posted to meter_events
# while the flag was on — Stripe accepts both for some weeks during the
# overlap window.
```

If the legacy path is already sunset by the time we roll back, manual
reconciliation via `scripts/cron/stripe_reconcile.py --replay-window 24h`
is required. This is a defined runbook (see `disaster_recovery.md` §3.5).

## Related files

- `src/jpintel_mcp/billing/stripe_usage.py` — hot-path Stripe call
- `scripts/cron/stripe_usage_backfill.py` — durable retry path
- `scripts/cron/stripe_version_check.py` — sunset detection
- `scripts/cron/stripe_reconcile.py` — daily DB ↔ Stripe diff
- `monitoring/sentry_alert_rules.yml` — alert wiring
- `MASTER_PLAN_v1.md` chapter 8 P1 — context for this runbook
