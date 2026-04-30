# Stripe Webhook URL Migration: zeimu-kaikei.ai → jpcite.com

**Owner**: 梅田茂利 (info@bookyou.net)
**Created**: 2026-04-30
**Status**: USER ACTION REQUIRED — code-side migration complete, Stripe Dashboard not yet flipped

Operator-only — do not link from public docs. Excluded from mkdocs build via
`exclude_docs: _internal/` (`mkdocs.yml`).

---

## Why this doc exists

The brand transition `zeimu-kaikei.ai → jpcite.com` is complete on the code
side (see §1 verification). The Stripe Dashboard webhook endpoint URL is
configured **outside the repo** — it cannot be migrated by editing code.
This doc records the manual user action needed to complete the cutover, and
the procedure for verifying it landed.

For background on the rotation procedure (signing secret refresh, debugging,
backlog reconciliation), see `stripe_webhook_rotation_runbook.md`. **This doc
covers URL migration only**, not signing secret rotation.

---

## 1. Code-side state (already complete)

Verified 2026-04-30. Search results below establish that the repo no longer
hardcodes `zeimu-kaikei.ai` for any Stripe redirect URL.

```bash
# Stripe billing module — must be 0
grep -rln "zeimu-kaikei" src/jpintel_mcp/billing/
# (empty)

# Stripe checkout/portal/dunning paths in api/billing.py — must be 0
grep -n "zeimu-kaikei" src/jpintel_mcp/api/billing.py
# (empty)

# Smoke test — must use jpcite.com
grep -n "success_url\|cancel_url" scripts/stripe_smoke_e2e.py
# 257:    "success_url": "https://jpcite.com/dashboard?session={CHECKOUT_SESSION_ID}",
# 258:    "cancel_url": "https://jpcite.com/pricing",
```

Where redirect URLs flow:

- **`success_url` / `cancel_url`** for `POST /v1/billing/checkout` are
  caller-supplied (frontend builds them from `window.location.origin`). Once
  served from `https://jpcite.com`, they auto-resolve to jpcite. See
  `site/go.html` lines 499-502 and `site/pricing.html` lines 379-380.
- **`return_url`** for `POST /v1/me/billing-portal` is built server-side
  from the request's origin in `src/jpintel_mcp/api/me.py:1166`
  (`return_url = f"{_origin_from_request(request)}/dashboard"`). When the
  dashboard is served from jpcite.com the return path matches.
- **Dunning email portal pointer** in `src/jpintel_mcp/api/billing.py:133`
  is hardcoded to `https://jpcite.com/billing/portal`. No further change
  needed.

The remaining `zeimu-kaikei.ai` strings in `src/jpintel_mcp/config.py:241-243`
are intentional CORS allowlist entries, retained until the legacy brand is
fully retired. They do not affect Stripe redirects.

---

## 2. USER ACTION — flip Stripe Dashboard webhook URL

The webhook URL Stripe POSTs to is configured at
**Stripe Dashboard → Developers → Webhooks → endpoint**, not in code.
Its likely current value is `https://api.zeimu-kaikei.ai/v1/billing/webhook`
(the legacy brand). It must be updated to
`https://api.jpcite.com/v1/billing/webhook` once `api.jpcite.com` is live
(parallel agent task — DNS + Cloudflare + Fly).

### Pre-flight check

Before flipping the URL, confirm `api.jpcite.com` resolves and serves the
webhook receiver:

```bash
# DNS resolution
dig +short api.jpcite.com
# expect: a non-empty answer pointing at Cloudflare or Fly.io edge

# Webhook endpoint surface (rejects unsigned POST with 400 — that's
# the desired behavior; it confirms the route exists)
curl -i -X POST https://api.jpcite.com/v1/billing/webhook \
  -H 'Content-Type: application/json' \
  -d '{}'
# expect: HTTP/2 400 with body containing "invalid signature" or
# "missing signature" (canonical envelope from billing.py)
```

If either check fails: do not flip the URL. The parallel agent owning
`api.jpcite.com` is not yet done. Loop them and wait.

### Flip procedure

1. Login to Stripe Dashboard: https://dashboard.stripe.com
2. Toggle to **Live mode** (top-left corner — critical, do not edit Test
   mode endpoints).
3. Navigate: **Developers → Webhooks**.
4. Click the existing endpoint (URL likely
   `https://api.zeimu-kaikei.ai/v1/billing/webhook`).
5. Click **"Update details"** (top-right of endpoint detail page).
6. Change the URL from
   `https://api.zeimu-kaikei.ai/v1/billing/webhook` to
   `https://api.jpcite.com/v1/billing/webhook`.
7. Confirm 5 events are still subscribed (Stripe preserves these on URL
   update, but verify):
   - `customer.subscription.created`
   - `invoice.paid`
   - `invoice.payment_failed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
8. Save.

### Verify with a test event

1. Same endpoint detail page → **"Send test webhook"** button.
2. Choose `invoice.paid`.
3. Click **Send**.
4. Wait ~5 seconds, then check Fly logs:

```bash
flyctl logs -a autonomath-api | grep -E 'webhook|signature' | tail -20
```

Expected:
- A new event ID logged.
- HTTP 200 response.
- No `webhook_signature_invalid`.

If you see `400 invalid signature`: the signing secret on Fly does not match
the new endpoint. The signing secret is per-endpoint in Stripe — if the URL
update created a new endpoint behind the scenes (Stripe sometimes does this
on URL change), the secret needs rotation. Run §3 of
`stripe_webhook_rotation_runbook.md` (Planned Rotation) to sync.

If the test event succeeds: production traffic will succeed too.

### Post-flip monitoring

For the first hour after the flip, watch:

```bash
# Continuous tail
flyctl logs -a autonomath-api | grep webhook
```

```bash
# Stripe Dashboard → Developers → Webhooks → endpoint → "Recent events"
# Filter by "Failed"
# Expected count: 0
```

If failures appear: see §5 of `stripe_webhook_rotation_runbook.md` (Debug
signature mismatch).

---

## 3. Rollback procedure

If the new URL fails for > 5 minutes and the cause is not obvious:

1. Stripe Dashboard → endpoint detail → **"Update details"** → revert URL to
   `https://api.zeimu-kaikei.ai/v1/billing/webhook`.
2. Save.
3. Verify with test event (should succeed since DNS for the legacy brand is
   still active per `config.py` CORS allowlist + the legacy Fly app).
4. Investigate the jpcite.com webhook failure mode before re-attempting.

The legacy `api.zeimu-kaikei.ai` route remains operational until both:

- This URL flip is verified successful.
- The legacy brand is formally retired (CLAUDE.md "Common gotchas" §CORS
  allowlist note will be updated to drop the zeimu-kaikei entries).

---

## 4. Log the migration

After the flip succeeds, append to `research/secret_rotations.log` (same
audit trail as signing secret rotations):

```
2026-04-XX-T-HH:MM+09:00 | STRIPE_WEBHOOK_URL | brand_migration | from=api.zeimu-kaikei.ai to=api.jpcite.com | operator=umeda | ticket=N/A
```

If the file does not exist, create it as an append-only log.

---

## 5. Cross-references

- `stripe_webhook_rotation_runbook.md` — signing secret rotation (separate
  concern from URL migration)
- `incident_runbook.md` §(b) — webhook receipt failures (general)
- `autonomath_com_dns_runbook.md` — DNS configuration patterns
- `jpcite_cloudflare_setup.md` — Cloudflare Pages + DNS for jpcite.com

---

最終更新: 2026-04-30
責任者: 代表 梅田茂利 (Bookyou株式会社, T8010001213708, info@bookyou.net)
