# Staging deploy playbook (Fly.io, nrt)

Target: first staging deploy of `jpintel-mcp` on Fly.io Tokyo, ahead of
public launch 2026-05-06. The user runs `flyctl` commands; this doc is the
ordered checklist.

## 1. Pre-flight

- [ ] `.venv/bin/pytest tests/ -q` — all green on current main.
- [ ] `flyctl auth whoami` — correct org.
- [ ] `flyctl version` — recent CLI.
- [ ] Secrets staged locally (do NOT commit): `STRIPE_SECRET_KEY` (test),
      `STRIPE_WEBHOOK_SECRET` (staging endpoint), `STRIPE_PRICE_PER_REQUEST`
      (the single metered price id, ¥0.5/req tax-exclusive), `STRIPE_METER_ID`,
      `STRIPE_BILLING_PORTAL_CONFIG_ID`, `API_KEY_SALT`
      (from `openssl rand -hex 32`), `SENTRY_DSN`, `JPINTEL_CORS_ORIGINS`.
- [ ] Stripe dashboard: create a STAGING webhook endpoint pointing at
      `https://jpintel-mcp.fly.dev/v1/billing/webhook` and copy its
      `whsec_*` — do NOT reuse prod's.

## 2. First-time launch (no-deploy, then wire infra)

```bash
# From repo root. --no-deploy so we can attach a volume and set secrets first.
flyctl launch --no-deploy --region nrt --name jpintel-mcp --org <org>

# Keep the checked-in fly.toml (it already has mounts, health check,
# release_command, rolling deploy, concurrency).
```

Create the volume (single region, single machine — SQLite is not replicated):

```bash
flyctl volumes create jpintel_data --region nrt --size 1
```

Set secrets (one `set` call batches all, triggering one restart later):

```bash
flyctl secrets set \
  STRIPE_SECRET_KEY=sk_test_... \
  STRIPE_WEBHOOK_SECRET=whsec_... \
  STRIPE_PRICE_PER_REQUEST=price_... \
  STRIPE_METER_ID=mtr_... \
  STRIPE_BILLING_PORTAL_CONFIG_ID=bpc_... \
  API_KEY_SALT="$(openssl rand -hex 32)" \
  SENTRY_DSN=https://...@sentry.io/... \
  JPINTEL_CORS_ORIGINS=https://staging.autonomath.ai,http://localhost:3000
```

Deploy:

```bash
flyctl deploy --strategy rolling
```

`release_command` (`python scripts/migrate.py`) runs before traffic shift —
it is idempotent and safe on a fresh `/data` volume.

## 3. Verify

- [ ] `curl https://jpintel-mcp.fly.dev/healthz` returns `{"status":"ok"}`.
- [ ] `curl -H "x-api-key: <seed-key>" https://jpintel-mcp.fly.dev/v1/programs/search?q=test`
      returns JSON with `items` array.
- [ ] `flyctl logs -a jpintel-mcp` shows structlog JSON, one line per request,
      with `request_id` and `path` keys.
- [ ] Trigger dummy error (temporary `/v1/debug/boom` or malformed call) and
      confirm it appears in Sentry staging project within 60s.
- [ ] `flyctl status` shows 1 machine running in nrt, health check `passing`.
- [ ] Stripe CLI: `stripe listen --forward-to https://jpintel-mcp.fly.dev/v1/billing/webhook`
      then `stripe trigger customer.subscription.created` — webhook must
      return 2xx.

## 4. Rollback

```bash
flyctl releases -a jpintel-mcp            # list versions
flyctl releases rollback <version> -a jpintel-mcp
```

Rolling deploy means the previous machine image is retained until the new one
passes health checks. Volume data is untouched by rollback — only code reverts.
If a migration caused the breakage, write and apply a new forward-fix
migration; do NOT attempt to hand-edit `schema_migrations`.

## 5. Smoke test checklist

- [ ] `GET /healthz` — 200.
- [ ] `GET /meta` — 200, non-zero `total_programs`.
- [ ] `GET /v1/programs/search?q=農業` — returns items, `X-Request-Id` header set.
- [ ] `GET /v1/programs/{id}` with a real id — 200, fields populated.
- [ ] `GET /v1/exclusions` — 200.
- [ ] Auth: request with no key — 401; with bad key — 401; with valid key — 200.
- [ ] Rate limit: burst >100 req/day on a free key — 429 after quota exhausts.
- [ ] `POST /v1/billing/webhook` with bad signature — 400.
- [ ] Security headers present: `Strict-Transport-Security`,
      `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.
- [ ] CORS: preflight from staging frontend origin — `Access-Control-Allow-Origin`
      matches origin; origin not in list — CORS blocked.
- [ ] `flyctl ssh console` → `ls /data/` shows `jpintel.db` with non-zero size.
- [ ] First nightly backup lands in `/data/backups/` (or GitHub Actions R2
      depending on chosen wiring — see `scripts/backup.md`).

---

If Fly is hard-down on launch day, DNS-flip to the Cloudflare Pages mirror:
see [docs/_internal/fallback_plan.md](./fallback_plan.md).

---

## 6. Secrets rotation runbook

**Cadence:** annual rotation as baseline + ad-hoc on any suspected exposure
(leaked logs, contractor offboarding, dependency compromise, vendor-side
breach). Rotate in staging first, verify, then repeat in production.

All commands assume the staging app `jpintel-mcp`; for production, swap in
`-a jpintel-mcp-prod` (or the configured app name) and the live Stripe keys.

### `API_KEY_SALT` — HIGH impact, emergency only

**Consequence:** every existing hashed API key in `api_keys.key_hash` is
invalidated at once. All customers must be re-issued keys. Do NOT rotate
casually — coordinate with every paying customer first.

```bash
# 1. Generate new salt (keep this value locally until step 3).
NEW_SALT="$(openssl rand -hex 32)"

# 2. Pre-announce to customers (email + status page), give a rotation window.

# 3. Set and deploy — triggers restart.
flyctl secrets set API_KEY_SALT="$NEW_SALT" -a jpintel-mcp
flyctl deploy --strategy rolling -a jpintel-mcp

# 4. Re-issue keys: for each active customer, regenerate via billing portal
#    or `POST /v1/billing/api-keys/rotate` (admin-only endpoint).
```

### `STRIPE_WEBHOOK_SECRET` — routine

**Consequence:** incoming webhooks will fail signature verification until the
new secret is live. Small window of missed events — Stripe retries for 3 days,
so briefly queued.

```bash
# 1. Stripe Dashboard → Developers → Webhooks → select endpoint → "Roll secret".
#    Copy the new whsec_... value.

# 2. Set it in Fly and redeploy.
flyctl secrets set STRIPE_WEBHOOK_SECRET=whsec_NEW... -a jpintel-mcp
flyctl deploy --strategy rolling -a jpintel-mcp

# 3. Verify: stripe trigger customer.subscription.updated, confirm 2xx in logs.
```

### `STRIPE_SECRET_KEY` — routine but separate test vs live

**Consequence:** outbound Stripe calls (Checkout session create, customer
lookup, meter-based usage record) will fail until the new key is live.

- Test mode key (`sk_test_...`) — staging only
- Live mode key (`sk_live_...`) — production only; never mix
- If rotating due to suspected leak, **also** revoke the old key in Stripe
  Dashboard → Developers → API keys (the rotate button keeps old keys active
  by default).

```bash
# Staging
flyctl secrets set STRIPE_SECRET_KEY=sk_test_NEW... -a jpintel-mcp

# Production
flyctl secrets set STRIPE_SECRET_KEY=sk_live_NEW... -a jpintel-mcp-prod

flyctl deploy --strategy rolling -a <app>
```

### `SENTRY_DSN` — low risk

**Consequence:** until the new DSN is live, new errors are dropped.
No customer-facing impact. DSN is per-project, not per-user.

```bash
# Sentry → Settings → Projects → jpintel-mcp → Client Keys (DSN) → New DSN.
flyctl secrets set SENTRY_DSN=https://NEW@sentry.io/PROJECT_ID -a jpintel-mcp
flyctl deploy --strategy rolling -a jpintel-mcp
# Old DSN can be disabled after a 24h overlap.
```

### Post-rotation verification (all cases)

```bash
flyctl secrets list -a jpintel-mcp                         # confirm digest changed
curl https://jpintel-mcp.fly.dev/healthz                   # service up
curl -H "x-api-key: <known-good-key>" \
  https://jpintel-mcp.fly.dev/v1/programs/search?q=test    # auth still works
flyctl logs -a jpintel-mcp | head -50                      # no startup errors
```

Record the rotation date, reason, and operator in the team's runbook log.
Any rotation done in response to an incident must also be noted in the
incident report ([docs/_internal/incident_runbook.md](./incident_runbook.md)).
