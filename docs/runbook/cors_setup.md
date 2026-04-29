# CORS Setup Runbook — `JPINTEL_CORS_ORIGINS`

> **Status**: One-time Fly secret + redeploy each time the marketing host
> changes. Cloudflare Pages auto-deploys static HTML, but the API origin
> allowlist lives on Fly and must be updated separately.
>
> **Owner**: 梅田茂利 / info@bookyou.net
> **Last reviewed**: 2026-04-29 (zeimu-kaikei.ai launch)

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
- Anything reachable from `<script>` on `zeimu-kaikei.ai`

Same-origin (no `Origin` header) and server-to-server callers (curl, Stripe
webhook, Anthropic relay) are **not** affected.

## Required origins (production)

Apex AND www must both be listed. Cloudflare Pages serves the marketing
site canonically at apex, but `www` is also accessible (CNAME flatten) and
some clients will hit it. The API host (`api.zeimu-kaikei.ai`) is also
included for the dashboard / audit-log subdomain self-referential calls.
Both `zeimu-kaikei.ai` and `autonomath.ai` are kept while the brand
crossover lasts (autonomath.ai redirects to zeimu-kaikei.ai but is still
a registered marketing host).

```
https://zeimu-kaikei.ai
https://www.zeimu-kaikei.ai
https://api.zeimu-kaikei.ai
https://autonomath.ai
https://www.autonomath.ai
```

## Apply

```bash
flyctl secrets set \
  JPINTEL_CORS_ORIGINS="https://zeimu-kaikei.ai,https://www.zeimu-kaikei.ai,https://api.zeimu-kaikei.ai,https://autonomath.ai,https://www.autonomath.ai" \
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
  -H "Origin: https://zeimu-kaikei.ai" \
  -H "Content-Type: application/json" \
  -X POST https://api.zeimu-kaikei.ai/v1/programs/prescreen \
  -d '{"profile":{"prefecture":"東京都"}}'

# Should return 403 origin_not_allowed.
curl -i \
  -H "Origin: https://evil.example.com" \
  -H "Content-Type: application/json" \
  -X POST https://api.zeimu-kaikei.ai/v1/programs/prescreen \
  -d '{"profile":{"prefecture":"東京都"}}'

# Preflight (OPTIONS) — should also 200 / 403 along the same axis.
curl -i \
  -X OPTIONS https://api.zeimu-kaikei.ai/v1/programs/prescreen \
  -H "Origin: https://zeimu-kaikei.ai" \
  -H "Access-Control-Request-Method: POST"
```

## Failure mode (what we just fixed)

2026-04-29 launch persona walk: prescreen UI returned `Failed to fetch`
100% of the time because `JPINTEL_CORS_ORIGINS` was set to
`https://autonomath.ai,https://www.autonomath.ai` only — the marketing
brand had moved to `zeimu-kaikei.ai` but the Fly secret had not been
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
export JPINTEL_CORS_ORIGINS="http://localhost:3000,http://localhost:8080,https://zeimu-kaikei.ai"
```

The `Origin` header from `localhost:3000` would otherwise be 403'd by the
production-default list.
