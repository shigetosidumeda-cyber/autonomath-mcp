# Stripe Webhook Signing Secret Rotation Runbook

**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26

Operator-only — do not link from public docs. Excluded from mkdocs build via
`exclude_docs: _internal/` (`mkdocs.yml`).

**Scope**: Routine and emergency rotation of the Stripe webhook signing
secret (`STRIPE_WEBHOOK_SECRET`, format `whsec_…`). Covers planned rotation
cadence, leaked-secret response, signature mismatch debugging, and event
backlog reconciliation when webhooks fail.

For Stripe webhook receipt failures other than signing secret mismatch
(e.g. application 5xx, endpoint URL drift), see `incident_runbook.md` §(b).

For broader Stripe billing recovery (chargeback, refund), see
`operators_playbook.md` §2 / §3.

---

## 1. Why this matters

Stripe webhooks deliver:

- `customer.subscription.created` → triggers API key issuance
- `invoice.paid` → records payment, sustains active subscription
- `invoice.payment_failed` → triggers dunning email + key suspension
- `customer.subscription.updated` → tier / price changes
- `customer.subscription.deleted` → revokes API key

Every event is signed by Stripe with the **endpoint signing secret**
(`whsec_…`). The receiver (`src/jpintel_mcp/api/billing.py`) verifies the
signature against `STRIPE_WEBHOOK_SECRET` env. If verification fails:

- The HTTP response is `400 invalid signature`.
- Stripe retries with exponential backoff for 3 days.
- If still failing at 3 days, the event is permanently discarded.
- A discarded `invoice.paid` means a paid customer never gets their key.
- A discarded `customer.subscription.deleted` means a canceled
  subscription continues to consume API quota.

Both failure modes are user-facing service breakdowns and consumer-law
risks (see 消契法 § 8 in `launch_compliance_checklist.md` §4). Rotation
therefore has zero-tolerance for downtime errors.

---

## 2. Rotation cadence

| Trigger | Cadence | Path |
| --- | --- | --- |
| Routine | Every 12 months | §3 (planned rotation) |
| Suspected leak | Immediate (T+0) | §4 (emergency rotation) |
| Confirmed leak | Immediate + post-incident review | §4 + `breach_notification_sop.md` |
| Stripe webhook endpoint URL change (e.g. domain change) | One-shot | §3 (treat as planned) |
| Webhook event signature mismatch in logs (sustained > 5 min) | Investigate first; rotate if root cause is secret drift | §5 (debug) → §3 (rotate if needed) |

The 12-month routine is calendar-anchored. Set a reminder on
2027-04-26 for the next planned rotation.

---

## 3. Planned rotation procedure

Estimated total time: 15-20 min, plus ~5 min Stripe retry catch-up. Total
service impact: zero (overlap window prevents drop).

### Step 1. Open Stripe Dashboard webhook settings

1. https://dashboard.stripe.com → Developers → Webhooks
2. Filter to **Live mode** (toggle top-left).
3. Locate endpoint `https://api.autonomath.ai/v1/billing/webhook`.
4. Confirm 5 events subscribed:
   - `customer.subscription.created`
   - `invoice.paid`
   - `invoice.payment_failed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`

If event list is incomplete: add missing ones before rotation. Mismatched
event subscription is a separate failure mode that rotation does not fix.

### Step 2. Generate the new signing secret

1. On the endpoint detail page → "Signing secret" section.
2. Click "Roll secret" (Stripe terminology) → confirms a new `whsec_…`
   value.

**Critical:** Stripe gives a "secret expiry window" (default 24h) during
which both the old and new secrets are valid. This is the rotation
overlap. Set the expiry window to **24 hours** if not already at the
maximum.

3. Click "Show" on the new secret. Copy the full `whsec_…` string.
4. Do **not** close this tab — you need to invalidate the old secret
   here in Step 6.

### Step 3. Push the new secret to Fly.io

```bash
flyctl secrets set STRIPE_WEBHOOK_SECRET='whsec_NEW_VALUE_HERE' \
  -a autonomath-api
```

Fly.io triggers a rolling deploy automatically (~30-60s). The new machine
has both the new secret in env and the codebase that verifies signatures.

### Step 4. Verify the new secret is active

```bash
flyctl status -a autonomath-api
# expect: most recent release shows "deployed", machines started
```

```bash
# Send a test event from Stripe Dashboard
# Webhooks → endpoint → "Send test webhook" → choose "invoice.paid" → Send
```

Then check Fly logs:

```bash
flyctl logs -a autonomath-api | grep -E 'webhook|signature' | tail -20
```

Expected:
- New event ID logged
- No `webhook_signature_invalid` errors
- HTTP 200 response

If `400 invalid signature` appears: the new secret is wrong. Re-copy from
Stripe Dashboard (watch for trailing whitespace or accidental quote
characters), re-run Step 3.

### Step 5. Confirm overlap window: old secret still works

Stripe is still sending real events in production using the old signature.
The 24h overlap window means both secrets validate. To confirm:

1. Wait 5-10 min.
2. Stripe Dashboard → Webhooks → endpoint → "Recent events" tab.
3. Last 10 events should all show "Successful" (200) — they were signed
   with the old secret but verify against the overlap.

If any show "Failed": the overlap window has misbehaved (rare). Skip to
§6 backlog recovery.

### Step 6. Invalidate the old secret

Return to the Stripe Dashboard tab from Step 2.

1. The page now shows "Active signing secret" (new) + "Expiring signing
   secret" (old) with a countdown.
2. Click "Expire now" on the old secret → confirms.
3. Old secret is invalidated immediately. Only the new one accepts.

If you skip this step, the old secret expires automatically at the 24h
mark — no harm in waiting, but explicit invalidation is cleaner for the
audit trail.

### Step 7. Verify production traffic post-cutover

```bash
# Wait 5 min for fresh real events to flow through
flyctl logs -a autonomath-api | grep -E 'webhook|signature' | tail -50
```

All entries should be 200. Any `webhook_signature_invalid` here means a
real production event was rejected — escalate to §6.

### Step 8. Update password manager

1Password vault `Bookyou` → item `stripe_webhook_secret_live` → update
to the new `whsec_…` value. Add a note with the rotation date and the
operator initials.

### Step 9. Log the rotation

Append to `research/secret_rotations.log`:

```
2026-04-26T14:30+09:00 | STRIPE_WEBHOOK_SECRET | planned | overlap_window=24h | operator=umeda | ticket=N/A
```

If file does not exist, create it as an append-only log.

---

## 4. Emergency rotation (suspected or confirmed leak)

Estimated time: 5-10 min. Service impact: < 30 seconds of webhook
verification gaps if executed without overlap.

### Step 1. Confirm the trigger

The leak signal could be:

- A `whsec_…` string spotted in a public location (GitHub, pastebin, X).
- A grep match for `whsec_` in repo history (`git log -p | grep whsec_`).
- A 1Password breach notification.
- A laptop / phone theft where 1Password autounlock could have been
  exploited.
- A fraudulent webhook event verifying with the current secret (unlikely
  but possible if attacker has the secret).

If the trigger is "suspected" but unverified: still rotate. Cost is low,
benefit is high.

### Step 2. Open Stripe Dashboard fast path

Navigate to: Developers → Webhooks → endpoint detail page.

### Step 3. Roll secret with **0-second** overlap

1. Click "Roll secret".
2. **Set expiry window to "Expire immediately"** (or set to 0 minutes).
3. Confirm. The old secret is dead instantly.

This is the dangerous knob: any in-flight webhook signed with the old
secret will fail verification. Stripe will retry, but events fired in the
~30 seconds between roll and Fly.io secret update will fail their first
attempt.

### Step 4. Update Fly.io immediately

```bash
flyctl secrets set STRIPE_WEBHOOK_SECRET='whsec_NEW_VALUE_HERE' \
  -a autonomath-api
```

Fly deploys in ~30s. During the deploy, no requests are dropped (Fly does
rolling deploy, old machine drains while new starts).

### Step 5. Verify and reconcile

Same as planned Step 4-7. Then immediately:

```bash
# Pull the last 1 hour of webhook delivery attempts from Stripe
# Dashboard → Webhooks → endpoint → "Recent events" → filter "Failed" → last 1h
```

For each failed event, click "Resend" or use:

```bash
stripe events resend evt_XXXXXXXX --live
```

This re-fires with the new (now-active) secret and succeeds.

### Step 6. Log the emergency rotation + open breach review

Append to `research/secret_rotations.log`:

```
2026-04-26T14:30+09:00 | STRIPE_WEBHOOK_SECRET | emergency | overlap_window=0s | trigger=<github_leak | laptop_theft | other> | operator=umeda | ticket=<incident_id>
```

If the leak was confirmed (not just suspected): this is a personal-data-
adjacent incident. Open the breach SOP at
`breach_notification_sop.md` and follow §1 trigger evaluation. The
webhook secret itself is not personal data, but a leaked secret + access
to webhook URL would let an attacker forge `customer.subscription.created`
events and provision API keys for fake customer IDs (PII manipulation
risk).

---

## 5. Debugging signature mismatch (no rotation needed yet)

Sustained `webhook_signature_invalid` errors might not require rotation.
Diagnose first.

### Symptom 1. Single event fails, others succeed

Most likely cause: corrupt request payload in transit (Cloudflare proxy
modifying headers, gzip handling, etc.).

```bash
# Inspect the failing event
flyctl logs -a autonomath-api | grep webhook_signature_invalid | tail -5
# Note the event_id from the log line
```

Stripe Dashboard → Developers → Events → search by event_id → "View
delivery attempts" → check the actual payload Stripe sent vs. what we
received. Compare byte-for-byte (Stripe shows both).

If they differ: Cloudflare or Fly is modifying the body. Check
`api/billing.py` for `request.body()` consumption — body must be read
raw, not via `request.json()` which re-serializes and changes signature.

### Symptom 2. All events fail

Most likely: secret drift between Stripe and Fly.

```bash
# Pull the secret from Fly (will only show "set" / "not set", not value)
flyctl secrets list -a autonomath-api | grep STRIPE_WEBHOOK_SECRET
```

Compare with Stripe Dashboard. If they obviously differ (e.g. Fly shows
"set" date 2025-10-01 and Stripe shows "active since 2026-04-15"), Fly
has the old secret. Re-do §3 (planned rotation) to sync.

### Symptom 3. Intermittent failures correlated with deploy

The `STRIPE_WEBHOOK_SECRET` env var was overwritten by a deploy without
explicit `flyctl secrets set`.

Check `fly.toml` for any `[env]` section that hardcodes secrets — there
should be none. Secrets must come from `flyctl secrets set` only.

If found: remove from `fly.toml`, re-set via flyctl, redeploy.

### Symptom 4. New endpoint URL on Stripe doesn't match Fly

Someone changed the endpoint URL on Stripe Dashboard but the secret
shown is for the new URL. The old secret continues working for the old
URL until the old endpoint is deleted.

Check Stripe Dashboard for multiple endpoints with similar names. There
should be exactly one Live endpoint at `https://api.autonomath.ai/v1/billing/webhook`.
Delete duplicates.

---

## 6. Webhook event backlog reconciliation

When webhooks fail (any reason: rotation gap, app down, secret mismatch),
events accumulate at Stripe's end. Recovery has two phases.

### Phase 1: Stripe-side replay (preferred, < 30 days old events)

Stripe retains failed event delivery records for 30 days. To replay:

```bash
# Authenticate to Stripe CLI (one-time)
stripe login --interactive

# List failed events in the last hour
stripe events list \
  --type 'customer.subscription.*,invoice.*' \
  --created.gte $(date -d '1 hour ago' +%s) \
  --limit 100 \
  --live

# Resend a specific event
stripe events resend evt_XXXXXXXX --live

# Bulk resend (script)
for evt in $(stripe events list --created.gte $(date -d '1 hour ago' +%s) \
              --limit 100 --live --format json | jq -r '.data[] | select(.pending_webhooks > 0) | .id'); do
  stripe events resend $evt --live
  sleep 0.2
done
```

Verify in Fly logs that resends succeed.

### Phase 2: On-Fly backlog dump (fallback for partial outages)

`api/billing.py` does **not currently** dump failed events to disk for
later reconciliation. This is a TODO.

**Recommended implementation** (deferred to first incident):

In `api/billing.py` webhook handler, on signature verification failure,
write the raw payload + timestamp to:

```
data/stripe_event_backlog/<unix_timestamp>_<random_8_hex>.json
```

The directory is `.gitignore`d (verify before first use; pattern
`data/stripe_event_backlog/` should be in `.gitignore`).

To reconcile manually:

```bash
flyctl ssh console -a autonomath-api -C 'ls -la /app/data/stripe_event_backlog/'

# For each file, manually decide:
# - subscription.created → does the customer have an api_key already? if not, provision
# - invoice.paid → does the subscription show paid status? if not, mark paid + extend
# - subscription.deleted → is the api_key revoked? if not, revoke

flyctl ssh console -a autonomath-api -C \
  'cat /app/data/stripe_event_backlog/<file>.json | jq'
```

After reconciliation, move processed files to:

```
data/stripe_event_backlog/processed/<unix_timestamp>_<random>.json
```

Retain for 90 days (match invoice retention), then delete.

### Phase 3: Stripe Dashboard reconciliation (last resort, > 30d old)

For events older than 30 days, Stripe no longer retains delivery records.
Reconcile by direct query:

1. Stripe Dashboard → Customers → for each affected customer
2. Compare Subscription state in Stripe vs. `api_keys` row in DB
3. If subscription is active but `api_keys` row is revoked → reactivate
   (set `revoked_at = NULL`, regenerate key, send rotation email)
4. If subscription is canceled but `api_keys` row is active → revoke
   (`UPDATE api_keys SET revoked_at = datetime('now') WHERE …`)

This is high-touch. Best to never reach this phase by always running
Phase 1 within 30 days of any webhook outage.

---

## 7. Monitoring + alerting

### Cloudflare Health Check is not enough

The `/v1/am/health/deep` endpoint (`health_monitoring_runbook.md`) does
not probe webhook receipt. It probes the API surface.

### Sentry alert rule (recommended)

Sentry → Alerts → Create alert:

- Trigger: `event.tag.endpoint = "/v1/billing/webhook"` AND `event.level
  = "error"` AND `count > 5 in 5min`
- Action: Email to `info@bookyou.net`
- Threshold: 5 errors in 5 minutes = ~5% failure rate at typical event
  volume of ~100/hour

If alert fires: open Stripe Dashboard webhook page, check event
delivery success rate, follow §5 debug.

### Stripe Dashboard manual check (weekly)

Operator weekly task (in `operator_daily.md` / `operators_playbook.md`):

1. Stripe Dashboard → Webhooks → endpoint → "Recent events"
2. Sort by status: Failed
3. Failure rate over last 7 days should be < 1%
4. If higher: investigate per §5

### Stripe-side webhook failure auto-notify

Stripe Dashboard → Settings → Notifications → enable "Webhook delivery
failures". Alerts to the dashboard owner email when Stripe's retry
exhausts. This is a backstop in case Sentry misses something.

---

## 8. Failure-rate thresholds and escalation

| Failure rate | Window | Action |
| --- | --- | --- |
| < 1% | Any | None — Stripe normal retry handles it |
| 1-5% | 1 hour | Investigate per §5 within 4h |
| > 5% | 30 min | Operator alert (Sentry rule); investigate within 1h |
| > 10% sustained > 1h | Any | Treat as outage; consider §4 emergency rotation if root cause is secret-related; otherwise `incident_runbook.md` §(b) |
| 100% for > 10 min | Any | Stripe is rejecting all events; could be: secret drift, app down, signature verification code regression. Roll back recent deploys (`flyctl releases rollback`) before rotating |

---

## 9. Cross-references

- `incident_runbook.md` §(b) — Stripe webhook dead-lettering
- `breach_notification_sop.md` — if leak confirmed
- `operators_playbook.md` §2 / §3 — Stripe disputes / refunds
- `env_setup_guide.md` — STRIPE_WEBHOOK_SECRET storage location
- `deploy_staging.md` — staging webhook rotation parity
- `launch_compliance_checklist.md` §1 — webhook endpoint configuration
  pre-launch
- `stripe_tax_setup.md` — Stripe Tax configuration (not affected by
  webhook rotation)

---

最終更新: 2026-04-26
責任者: 代表 梅田茂利 (Bookyou株式会社, T8010001213708, info@bookyou.net)
