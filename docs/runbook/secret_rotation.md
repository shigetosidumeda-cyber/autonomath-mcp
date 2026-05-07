---
title: Secret rotation runbook
updated: 2026-05-04
operator_only: true
category: secret
---

# Secret rotation runbook

Operator-facing procedure for the five production secrets the §S2 boot gate
enforces (`api/main.py::_assert_production_secrets` + `entrypoint.sh §3`).
Boot fails closed on any missing / placeholder value when `JPINTEL_ENV=prod`.
The full Fly secret inventory (boot-gated + non-gated) lives in
`MASTER_PLAN_v1.md` 付録 D — this runbook is the rotation procedure for
the boot-gated subset only; cross-runbook coverage of the rest:
`docs/runbook/cors_setup.md` (`JPINTEL_CORS_ORIGINS`),
`docs/runbook/search_console_setup.md` (`INDEXNOW_KEY`),
`docs/runbook/disaster_recovery.md` §2 + `docs/runbook/litestream_setup.md`
Step 2 (R2 token quartet shared between snapshot crons + litestream sidecar).

| Secret                       | Cadence       | Generator                             | Notes |
|------------------------------|---------------|---------------------------------------|-------|
| `API_KEY_SALT`               | NEVER rotate  | `openssl rand -base64 32`             | Rotating invalidates every existing API key (re-hashed). One-shot at first launch. |
| `JPINTEL_AUDIT_SEAL_KEYS`    | 90 days       | `openssl rand -base64 64` (per key)   | Comma-separated rotation list. Old key kept for 90 days so existing seals remain verifiable. |
| `AUDIT_SEAL_SECRET`          | only if `JPINTEL_AUDIT_SEAL_KEYS` is unset | same as above | Legacy single-key fallback. Prefer `JPINTEL_AUDIT_SEAL_KEYS`. |
| `STRIPE_WEBHOOK_SECRET`      | Stripe-driven | Stripe Dashboard > Webhooks > Reveal  | Stripe rotates on demand; copy `whsec_…` literal. |
| `STRIPE_SECRET_KEY`          | rare          | Stripe Dashboard > Developers > API keys | Restricted-key recommended; full secret only for billing migrations. |

## Step-by-step: initial provisioning

```bash
# 1. Generate API_KEY_SALT (one-shot, never rotate after launch).
SALT=$(openssl rand -base64 32)
fly secrets set API_KEY_SALT="$SALT" -a autonomath-api

# 2. Generate audit-seal HMAC key (active key only on first launch).
AUDIT_KEY=$(openssl rand -base64 64)
fly secrets set JPINTEL_AUDIT_SEAL_KEYS="$AUDIT_KEY" -a autonomath-api

# 3. Stripe (paste from dashboard, do NOT regenerate via CLI).
fly secrets set STRIPE_SECRET_KEY="sk_live_..." -a autonomath-api
fly secrets set STRIPE_WEBHOOK_SECRET="whsec_..." -a autonomath-api
```

After `fly secrets set` triggers a rolling restart, watch the boot log for the
section §3 line `production secret gate passed (§S2)` — its absence means
either `JPINTEL_ENV` is not `prod` or one of the secrets is still missing.

## Step-by-step: 90-day audit-seal rotation

```bash
# 1. Generate the new key. Keep the old one in the comma-separated list so
#    existing seals stay verifiable for the rotation window.
NEW_KEY=$(openssl rand -base64 64)
OLD_KEYS=$(fly secrets list -a autonomath-api -j | jq -r '.[] | select(.Name=="JPINTEL_AUDIT_SEAL_KEYS") | .Value')
# (fly does not echo secret values; copy from the operator's password manager.)
fly secrets set JPINTEL_AUDIT_SEAL_KEYS="$NEW_KEY,$OLD_KEYS" -a autonomath-api

# 2. After 90 days, drop the oldest key. New seals always sign with the
#    leftmost key in the list; verification accepts any.
fly secrets set JPINTEL_AUDIT_SEAL_KEYS="$NEW_KEY" -a autonomath-api
```

## Step-by-step: Stripe webhook rotation

Stripe drives this — never rotate proactively without a reason (a leaked
`whsec_…`, a webhook endpoint change, or a Stripe-issued key revocation).

```bash
# 1. In the Stripe Dashboard, go to Developers > Webhooks > endpoint > Roll secret.
# 2. Stripe shows the new secret ONCE; paste it into Fly:
fly secrets set STRIPE_WEBHOOK_SECRET="whsec_..." -a autonomath-api
# 3. Stripe accepts BOTH the old + new secret for ~24h, so the rolling restart
#    has time to land before old-secret signatures stop validating.
```

## Verify

```bash
# 1. Local smoke (must NOT crash with [BOOT FAIL]):
JPINTEL_ENV=dev .venv/bin/python -c "from jpintel_mcp.api.main import _assert_production_secrets; _assert_production_secrets()"

# 2. Local smoke that DOES crash (sanity check the gate):
JPINTEL_ENV=prod API_KEY_SALT=dev-salt \
  .venv/bin/python -c "from jpintel_mcp.api.main import _assert_production_secrets; _assert_production_secrets()"
# → SystemExit: [BOOT FAIL] API_KEY_SALT must be set ...

# 3. Production verify (after deploy):
fly logs -a autonomath-api | grep -E "(production secret gate passed|BOOT FAIL)"

# 4. Pre-commit grep gate (CI):
.venv/bin/pytest tests/test_no_default_secrets_in_prod.py -v
```

## Anti-patterns

* **Do NOT** rotate `API_KEY_SALT` post-launch. Every customer's API key is
  hashed with the salt; a rotation invalidates all existing keys and forces a
  customer-wide re-issue. The §S2 boot gate accepts any value ≥32 chars; it
  does not (and cannot) detect a rotation event.
* **Do NOT** commit `.env.production` or `fly.toml` `[env]` blocks containing
  any of the secrets above. The CI grep gate
  (`tests/test_no_default_secrets_in_prod.py`) blocks any sample file
  carrying a forbidden salt; do not bypass it with `--no-verify`.
* **Do NOT** weaken the boot gate to "warn but continue" — every production
  outage in the secret-rotation history was a silent placeholder propagating
  to the hashing layer.

## Rollback

If a rotation triggered a `[BOOT FAIL]` line on the next Fly machine and the
service is now refusing connections, roll the affected secret back to its
previous value from the operator keystore (1Password). `fly secrets set`
triggers a rolling restart on each call, so the rollback takes ~10 s once
the previous value is in hand.

```bash
# 1. Pull the previous value from 1Password (Fly does NOT echo secret values).
PREV_VAL="<paste from operator keystore>"

# 2. Re-set the affected secret. Replace SECRET_NAME with the one rolled.
fly secrets set SECRET_NAME="$PREV_VAL" -a autonomath-api

# 3. Verify boot succeeds.
fly logs -a autonomath-api | grep -E "(production secret gate passed|BOOT FAIL)" | tail -5
```

Special case — `JPINTEL_AUDIT_SEAL_KEYS` partial rollback: if the new
key landed but verification of older seals started failing, append the
previous key back to the comma-separated list (do NOT replace) so both
are accepted during the rotation window:

```bash
fly secrets set JPINTEL_AUDIT_SEAL_KEYS="$NEW_KEY,$PREV_KEY" -a autonomath-api
```

For `STRIPE_WEBHOOK_SECRET` rollback: Stripe accepts both old + new for
~24h after a roll, so re-setting the previous `whsec_…` is safe within
that window. Past 24h, signatures from the old secret start rejecting
and rollback is no longer possible — the only recovery is a forward roll
on the Stripe Dashboard side.
