---
title: CORS Setup Runbook — JPINTEL_CORS_ORIGINS
updated: 2026-05-07
operator_only: true
category: secret
---

# CORS Setup Runbook — `JPINTEL_CORS_ORIGINS`

> **Status**: One-time Fly secret + redeploy each time the marketing host
> changes. Cloudflare Pages auto-deploys static HTML, but the API origin
> allowlist lives on Fly and must be updated separately.
>
> **Owner**: 梅田茂利 / info@bookyou.net
> **Last reviewed**: 2026-04-29 (jpcite.com launch)

## What this gates

`OriginEnforcementMiddleware` (see
`src/jpintel_mcp/api/middleware/origin_enforcement.py`) **short-circuits**
any browser request whose `Origin` header is not on the allowlist with HTTP
403 `origin_not_allowed`. It runs **before** any route handler — so a
forgotten origin breaks every browser-side feature simultaneously:

- Homepage prescreen UI (`POST /v1/programs/prescreen`)
- Saved searches (`/v1/saved_searches/*`)
- Customer webhooks dashboard (`/v1/webhooks/*`)
- Audit log (`/v1/audit/*`)
- Anything reachable from `<script>` on `jpcite.com`

Same-origin (no `Origin` header) and server-to-server callers (curl, Stripe
webhook, Anthropic relay) are **not** affected.

## Required origins (production)

Apex must be listed. `www.jpcite.com` is redirect-source only and should
301 to apex before Pages serves HTML, but it remains in the API allowlist
until cached browser sessions and old bookmarks have aged out. The API host
(`api.jpcite.com`) is also included for dashboard / audit-log
self-referential calls. Both `jpcite.com` and `autonomath.ai` are kept while
the brand crossover lasts (autonomath.ai redirects to jpcite.com but is
still a registered marketing host).

```
https://jpcite.com
https://www.jpcite.com
https://api.jpcite.com
https://autonomath.ai
https://www.autonomath.ai
```

## Apply

```bash
flyctl secrets set \
  JPINTEL_CORS_ORIGINS="https://jpcite.com,https://www.jpcite.com,https://api.jpcite.com,https://autonomath.ai,https://www.autonomath.ai" \
  -a autonomath-api
```

Fly will hot-restart the machine (~10 s). Verify with:

```bash
flyctl ssh console -a autonomath-api -C "printenv JPINTEL_CORS_ORIGINS"
```

## Verify (live)

```bash
# Should return 200 with the expected JSON payload.
curl -i \
  -H "Origin: https://jpcite.com" \
  -H "Content-Type: application/json" \
  -X POST https://api.jpcite.com/v1/programs/prescreen \
  -d '{"profile":{"prefecture":"東京都"}}'

# Should return 403 origin_not_allowed.
curl -i \
  -H "Origin: https://evil.example.com" \
  -H "Content-Type: application/json" \
  -X POST https://api.jpcite.com/v1/programs/prescreen \
  -d '{"profile":{"prefecture":"東京都"}}'

# Preflight (OPTIONS) — should also 200 / 403 along the same axis.
curl -i \
  -X OPTIONS https://api.jpcite.com/v1/programs/prescreen \
  -H "Origin: https://jpcite.com" \
  -H "Access-Control-Request-Method: POST"
```

## Failure mode (what we just fixed)

2026-04-29 launch persona walk: prescreen UI returned `Failed to fetch`
100% of the time because `JPINTEL_CORS_ORIGINS` was set to
`https://autonomath.ai,https://www.autonomath.ai` only — the marketing
brand had moved to `jpcite.com` but the Fly secret had not been
updated. Every browser-side fetch from the new host returned HTTP 403
`origin_not_allowed`. Fix: re-set the secret to include the full list
above.

## Adding a new origin (e.g., a partner embed)

1. Append to the list above (keep it as one source of truth).
2. Update the `cors_origins` `default=` in `src/jpintel_mcp/config.py`
   so a fresh Fly machine without the secret still serves the right list.
3. Re-run the `flyctl secrets set` command.
4. Update this runbook's "Required origins" section.
5. Verify with the curl block above using the new `Origin`.

## Removing an origin

Same steps but with the origin removed. Allow at least 24h grace if the
removed origin was production traffic — the 403 response is hard, no
graceful degradation.

## Local dev override

```bash
export JPINTEL_CORS_ORIGINS="http://localhost:3000,http://localhost:8080,https://jpcite.com"
```

The `Origin` header from `localhost:3000` would otherwise be 403'd by the
production-default list.

## Rollback

If a new `JPINTEL_CORS_ORIGINS` value broke browser-side traffic
(spike of HTTP 403 `origin_not_allowed` in `fly logs -a autonomath-api`),
roll back to the last known-good value:

```bash
# 1. Recover the previous value from Fly secret history (operator keystore /
#    1Password should also carry it). Fly does NOT echo secret values, so
#    this must come from the operator's offline note, not flyctl.
LAST_GOOD="https://jpcite.com,https://www.jpcite.com,https://api.jpcite.com,https://autonomath.ai,https://www.autonomath.ai"

# 2. Re-set and trigger rolling restart.
flyctl secrets set JPINTEL_CORS_ORIGINS="$LAST_GOOD" -a autonomath-api

# 3. Verify with the curl block in "Verify (live)" above. Both jpcite.com
#    and any newly added partner origin must return 200; an unknown origin
#    must return 403.
flyctl ssh console -a autonomath-api -C "printenv JPINTEL_CORS_ORIGINS"
```

Recovery time is ~10 s (Fly hot restart). The `OriginEnforcementMiddleware`
short-circuits at request-arrival time, so the rolled-back value takes
effect on the very next request — no cache invalidation required.
