---
title: Stripe Chargeback Response Runbook
updated: 2026-05-07
operator_only: true
category: billing
---

# Stripe Chargeback Response Runbook (G3)

**Owner**: 梅田茂利 (info@bookyou.net) — solo zero-touch
**Operator**: Bookyou株式会社 (T8010001213708)
**Last reviewed**: 2026-05-07
**Related**: `docs/runbook/stripe_live_activation.md` (account setup that this runbook assumes is already complete), `docs/runbook/stripe_meter_events_migration.md` (the meter event source of truth that backs evidence packs), `src/jpintel_mcp/api/_audit_seal.py` (cryptographic proof of usage = primary evidence), `src/jpintel_mcp/api/audit_seal.py` (`GET /v1/me/audit_seal/{call_id}` re-verify endpoint).

When a customer disputes a Stripe charge, the operator has a **strict 7-day
SLA from notification to representment submission**. Missing the deadline
loses the dispute by default — Stripe debits the disputed amount + ¥1,500
dispute fee. This runbook turns a dispute notification into a representment
package within that window.

## 1. Detection

```text
A. Email from `disputes@stripe.com` titled
   "[Action Required] Dispute received — autonomath-api".
B. Stripe Dashboard → Payments → Disputes shows a new row with
   `status=needs_response` and `due_by=<7 days from now>`.
C. Sentry alert `stripe_dispute_received` (webhook event
   `charge.dispute.created` triggers a low-volume alert).
```

**Pre-state self-check** (60 sec — capture the dispute identifiers before
the email gets buried):

```bash
# Open the email + Stripe Dashboard side-by-side.
# Dispute object key fields to copy into the post-incident note:
#   - dispute_id              (du_...)
#   - charge_id               (ch_... or pi_...)
#   - amount_disputed         (matches the original charge minus refunds)
#   - reason                  (one of: duplicate / fraudulent / product_not_received /
#                              product_unacceptable / subscription_canceled / unrecognized /
#                              credit_not_processed / general)
#   - due_by                  (the 7-day deadline — this runbook's hard SLA)
#   - evidence_details.has_evidence  (false until you submit the rep)
#   - evidence_details.past_due   (false; if true STOP — already lost)
```

If `past_due=true`: the dispute is already lost. Skip to §6 (post-loss
ledger update). Do **NOT** submit late evidence — Stripe ignores it and the
attempt looks like operator confusion in any future audit.

## 2. The 5 reason codes that matter for jpcite

The product is metered API access at ¥3/billable unit. The customer landscape
makes some Stripe reasons mechanically rare:

| Reason (Stripe code)      | Likelihood | Primary evidence we attach                        |
|---------------------------|------------|----------------------------------------------------|
| `unrecognized`            | **high**   | audit_seal proof of usage + IP/UA logs + ToS link  |
| `fraudulent`              | medium     | audit_seal + 3-D Secure attempt log + customer email|
| `product_not_received`    | medium     | audit_seal proof that API requests succeeded       |
| `duplicate`               | low        | Stripe ledger showing only one paid invoice        |
| `product_unacceptable`    | low        | ToS + change log (but: a court could still rule against us) |
| `subscription_canceled`   | n/a        | (no subscriptions — we are pure usage-metered)     |
| `credit_not_processed`    | low        | refund history + customer email thread             |
| `general`                 | medium     | catch-all — attach everything in §3                |

The `unrecognized` and `product_not_received` cases are the bread-and-butter
defenses for a metered API: the audit_seal envelope is **cryptographic
non-repudiation** of every call.

## 3. Build the evidence package

```bash
# 3a. Find the customer's API key from the charge_id.
flyctl ssh console -a autonomath-api
sqlite3 /data/jpintel.db <<'SQL'
.headers on
.mode column
SELECT customer_id, stripe_customer_id, api_key_id, created_at
FROM api_keys
WHERE stripe_customer_id IN (
  SELECT customer FROM stripe_charges WHERE id = '<charge_id>' OR payment_intent = '<pi_id>'
);
SQL
exit

# 3b. Pull every metered request signed under that api_key_id during the
#     billing period. Each row carries an HMAC-signed audit_seal.
sqlite3 /data/jpintel.db <<'SQL' > /tmp/evidence-<dispute_id>.jsonl
.mode json
SELECT call_id, ts_jst, route, status, audit_seal_hmac, snapshot_id
FROM audit_seals
WHERE api_key_id = '<api_key_id>'
  AND ts_jst >= '<billing_period_start>'
  AND ts_jst <  '<billing_period_end>'
ORDER BY ts_jst ASC;
SQL

# 3c. Pin one or two seals to be re-verifiable by Stripe's reviewer (or by a
#     court). Pick the first call and the last call of the period.
curl -fsS https://api.jpcite.com/v1/me/audit_seal/<first_call_id>  | jq . > /tmp/evidence-<dispute_id>-first.json
curl -fsS https://api.jpcite.com/v1/me/audit_seal/<last_call_id>   | jq . > /tmp/evidence-<dispute_id>-last.json
# Each response is a fully self-contained envelope: payload bytes + HMAC + key id.
# Stripe's reviewer cannot run our verifier, but they can see the deterministic
# shape and the embedded key rotation pointer.
```

The audit_seal proof comprises:

* `call_id` — UUID assigned at request time
* `ts_jst` — request timestamp in JST
* `route` — the endpoint that served the call
* `status` — HTTP status (200 / 4xx / 5xx)
* `snapshot_id` — corpus snapshot the response was computed against
* `audit_seal_hmac` — HMAC-SHA256 over the canonical payload, signed with
  `JPINTEL_AUDIT_SEAL_KEYS` (90-day rotation, prior keys retained — see
  `docs/runbook/secret_rotation.md` §"90-day audit-seal rotation")

This is the strongest evidence available because the signing key is on Fly
secrets, never echoed back to the API surface, and the verifier accepts any
key in the rotation list.

## 4. Submit the representment in Stripe Dashboard

Stripe Dashboard → Disputes → click the row → **Submit Evidence**. Fill the
fields exactly:

```text
Customer name                  : <api_keys.contact_name>
Customer email                 : <api_keys.contact_email>
Customer purchase IP           : <usage_events.ip from the first audit row>
Product description            : "jpcite metered API access (¥3/billable
                                  unit). Customer ID <stripe_customer_id>
                                  consumed N calls during the billing
                                  period. Each call is cryptographically
                                  signed (HMAC-SHA256) and re-verifiable
                                  via GET /v1/me/audit_seal/{call_id}."
Service date                   : <billing_period_start> through <billing_period_end>
Service documentation          : Upload /tmp/evidence-<dispute_id>.jsonl
                                 (rename to evidence.jsonl in the upload).
Receipt                        : Stripe-issued receipt URL (auto-included).
Customer signature             : N/A (API product, no signature collected).
Customer communication         : ToS acceptance timestamp (from
                                  api_keys.tos_accepted_at + git commit
                                  hash of the live ToS document).
Refund policy                  : Link to https://jpcite.com/legal/terms
                                  (specifically the "請求と払戻し" section).
Refund policy disclosure       : Link to the same ToS URL.
Cancellation policy            : "Customer can revoke API key at any time
                                  via /v1/me/api-keys/{id} DELETE; revocation
                                  stops further metering immediately."
Uncategorized text             : Append the audit_seal recipe (see §5)
                                  for the dispute reviewer to follow if
                                  they want independent verification.
```

Click **Submit**. Stripe immediately moves the dispute to
`status=under_review`. The bank's call typically returns in 60–90 days.

## 5. Audit-seal verification recipe (for inclusion in the rep)

```text
1. Decode the JWT-style audit_seal envelope in evidence.jsonl:
   - `payload`  — JSON canonical form
   - `key_id`   — points at the active or retired signing key
   - `hmac`     — HMAC-SHA256(payload, key)
2. The payload contains:
   - call_id (UUID)
   - api_key_id (hashed, salted with API_KEY_SALT — irreversible)
   - ts_jst, route, status, snapshot_id
3. Independent verification:
   - GET https://api.jpcite.com/v1/me/audit_seal/{call_id}
   - This endpoint is metered (¥3) and returns the original envelope,
     allowing the reviewer to confirm Bookyou株式会社 still attests
     to the call.
4. Key rotation:
   - The 90-day rotation list is comma-separated in
     JPINTEL_AUDIT_SEAL_KEYS (Fly secret). Old keys remain active for
     verification for 90 days, so calls signed up to 90 days ago can
     still be re-verified.
```

## 6. Post-loss ledger update (only if the dispute is lost)

If Stripe rules against the operator, the chargeback debits the disputed
amount + the ¥1,500 fee:

```bash
# 6a. Reflect the loss in the local Stripe mirror so internal accounting
#     stays in sync with Stripe.
flyctl ssh console -a autonomath-api -C "python /app/scripts/stripe_reconcile.py --since <billing_period_start>"

# 6b. If the lost dispute reason was `unrecognized` and the audit_seal trail
#     was clean, this is a bank-side false negative — file a Stripe
#     "request review" via the dashboard. Stripe's threshold for review is
#     low if the evidence package was complete; about 1 in 4 reviews flip.
```

## 7. Verify (every dispute response must complete this)

```bash
# 7a. Stripe Dashboard → Disputes → row shows status=under_review and
#     "Evidence submitted" timestamp.

# 7b. The evidence file is archived locally (durable, off-Fly) for 7 years
#     per Bookyou株式会社 books-and-records obligations.
mkdir -p ~/jpcite-evidence/<yyyy>/<mm>/
cp /tmp/evidence-<dispute_id>*.{jsonl,json} ~/jpcite-evidence/<yyyy>/<mm>/

# 7c. The originating Sentry issue (`stripe_dispute_received` event for this
#     dispute_id) is annotated with the evidence file path and resolved.

# 7d. CHANGELOG.md is appended with a one-line note (no PII).
```

## 8. Rollback

There is no rollback for a submitted representment — Stripe accepts only
one evidence submission per dispute. If a critical flaw is discovered in
the package after submit, contact Stripe Support **immediately** (within
24 h) requesting a re-submission window. Stripe occasionally grants this
when the original submission is incomplete; outside the 24 h window, the
submitted evidence stands.

## 9. Failure modes

* **`due_by` already passed when the email lands**: Stripe's notification
  email occasionally arrives the same day as the deadline if SES delays.
  Submit immediately if any time remains (Stripe accepts late submissions
  up to a few hours past `due_by` in practice but officially the SLA is
  the timestamp).
* **API key was rotated mid-billing-period**: the audit_seal trail still
  works because seals are signed against `JPINTEL_AUDIT_SEAL_KEYS` (server
  secret), not the customer's API key hash. The api_key_id rotation is a
  customer-side bookkeeping detail, not a verification break.
* **`audit_seals` table empty for the disputed period**: catastrophic — it
  means usage was never persisted (likely a code regression or migration
  089 not applied). Stripe will lose the dispute by default. After the
  fact, escalate to `docs/runbook/sentry_alert_escalation.md` §"backfill
  required" because the pricing model itself is unsupportable without
  audit_seal coverage.
* **Customer claims they never received API responses but ledger shows
  status=200**: the audit_seal proof is sufficient. Stripe's bar for
  "product_not_received" on an API product is met by HTTP 200 + signed seal.
* **Stripe restricted-key permission error during `stripe_reconcile.py`**:
  the restricted key may lack `disputes:read`. Update its scope in Stripe
  Dashboard → Developers → API keys; do NOT replace with the unrestricted
  secret key (security regression).

## 10. Items needing user action (one-time prerequisites)

* `STRIPE_WEBHOOK_SECRET` set per `docs/runbook/secret_rotation.md` so the
  `charge.dispute.created` webhook fires the Sentry alert.
* `JPINTEL_AUDIT_SEAL_KEYS` set + 90-day rotation calendar reminder per
  `docs/runbook/secret_rotation.md`. Without an active signing key the
  audit_seal proof is unverifiable and §3-§5 collapse.
* Stripe Dashboard → Disputes notifications routed to `info@bookyou.net`
  (not a shared inbox) so the 7-day SLA isn't blown by a mis-routed email.
* ToS URL `https://jpcite.com/legal/terms` reachable + version-pinned
  (commit hash visible in the page footer) so §4 can cite a specific
  revision.
