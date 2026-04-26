# Stripe test-mode smoke runbook

End-to-end proof that the full payment funnel works before launch. Driver
script: `scripts/stripe_smoke_e2e.py`. Unit test (mocks Stripe, runs in CI):
`tests/test_stripe_smoke_unit.py`.

## Prerequisites

1. **Stripe test account** (not live mode).
2. **Create a metered test price in JPY** in the Stripe dashboard
   (test mode → Products → add a recurring metered price, `lookup_key =
   per_request_v3`, `unit_amount = 3` (¥3, 税別 / ¥3.30 税込), currency = JPY,
   `tax_behavior = exclusive`). Note the resulting `price_...` id.
3. **Create a webhook endpoint** in the dashboard (test mode → Developers →
   Webhooks) pointing to your local tunnel (ngrok, stripe CLI forward, or
   just "send test event" for manual mode). Copy the **signing secret**.
4. Export env vars before running:
   ```bash
   export STRIPE_SECRET_KEY_TEST=sk_test_...
   export STRIPE_WEBHOOK_SECRET_TEST=whsec_...
   export STRIPE_PRICE_ID_TEST=price_...
   ```
5. Local repo set up: `pip install -e ".[dev]"` so the script can boot uvicorn
   against its own temp SQLite DB.

## Running

```bash
.venv/bin/python scripts/stripe_smoke_e2e.py
```

Expected runtime: **under 60 seconds**. Creates one test customer + one test
subscription in your Stripe test account, then cancels + deletes them on
cleanup. Nothing touches `data/jpintel.db` (the script uses a temp DB).

Exit 0 on full pass. Every step prints `PASS  <label>` or `FAIL  <label>` with
a short reason, followed by a summary.

## When to run

**Before merging any Stripe billing code change to `main`.** Specifically:

- `src/jpintel_mcp/api/billing.py` edits
- `src/jpintel_mcp/billing/` edits
- Pricing page CTA changes in `site/pricing.html`
- `STRIPE_*` env / config shape changes in `src/jpintel_mcp/config.py`

The unit suite (`tests/test_stripe_smoke_unit.py`) runs on every PR. The full
smoke is a manual gate because it needs network + Stripe credentials.

## Common failures

| Symptom | Likely cause | Fix |
|---|---|---|
| `Stripe auth failed — secret key rejected` | Wrong secret, revoked key, or live-mode key passed as test | Regenerate test key from Stripe → Developers → API keys; ensure `sk_test_` prefix |
| `Stripe price_id not found in test account` | Price exists in live mode, not test | Recreate price in test mode; confirm the id via `stripe prices retrieve <id>` |
| `webhook failed 400: bad signature` | Webhook secret mismatch, or payload was re-encoded between signing and POST | Copy `STRIPE_WEBHOOK_SECRET_TEST` afresh from the test-mode endpoint; do not run script through a proxy that rewrites JSON |
| `webhook failed 503: webhook secret unset` | Script failed to propagate env to the uvicorn child | Check `_start_api()` env pass-through; confirm `STRIPE_WEBHOOK_SECRET` is set in the child |
| `404` on `/v1/billing/checkout` | Router not mounted, or `/v1` prefix stripped | Confirm `billing_router` in `api/main.py` and that the local process booted from `jpintel_mcp.api.main:app` |
| `tier not demoted` after `invoice.payment_failed` | Older handler (pre-2026-04-23) that ignored payment_failed | Pull latest `src/jpintel_mcp/api/billing.py`; handler now calls `update_tier_by_subscription(..., 'free')` |
| `revoked key still accepted` | Middleware cache; `require_key()` not re-reading `revoked_at` | No cache exists by design — check that the DB is the same file the server opened (temp dir path) |
| Script hangs on `API ready at ...` | Port collision or slow startup | `_free_port()` should prevent this; check `proc.stderr` in the script output |

## Security

The script **refuses to run** if:

- `STRIPE_SECRET_KEY_TEST` is missing, empty, or lacks the `sk_test_` prefix
- `STRIPE_SECRET_KEY_TEST` starts with `sk_live_` (explicit guard, even if
  someone overrode the expected var name)
- `STRIPE_WEBHOOK_SECRET_TEST` looks like a live-mode signing secret
- `STRIPE_PRICE_ID_TEST` is not a `price_...` id

These guards exist because this script issues webhooks the server will act on
(demote tier, revoke keys). Firing it against a live Stripe account with
production data would cause real customer impact.

## Related

- `scripts/mcp_smoke.py` — MCP stdio smoke (non-billing)
- `tests/test_billing.py` — 21 unit tests, all-mock, run in CI
- `tests/test_billing_tax.py` — 5 JCT / invoice 制度 tests
- `tests/test_stripe_smoke_unit.py` — 8 signature + webhook roundtrip tests (CI)
