# API domain migration: api.zeimu-kaikei.ai → api.jpcite.com

Status: **In progress (parallel-serve phase)**
Owner: ops (solo)
Last updated: 2026-04-30

## TL;DR

`api.jpcite.com` is the **canonical** API domain going forward. It matches
the rest of the brand surface (site, dashboard, docs, OpenAPI `servers`
entry). `api.zeimu-kaikei.ai` is the **legacy** domain that still has
live customers and MCP clients pointing at it.

Both hostnames resolve to the **same** Fly.io app (`autonomath-api`).
Requests served via the legacy hostname carry RFC 8594 `Deprecation`,
RFC 9745 `Sunset`, and RFC 8288 `Link: rel="successor-version"`
headers. Body and status code are unchanged — the legacy domain is
**fully functional**, just labelled as deprecated.

There is **no scheduled hard-cutover date.** Cutover is triggered by
traffic-share data, not a calendar entry.

## DNS / Fly setup

Both records point at the same Fly app. Custom-domain provisioning for
`api.jpcite.com` is owned by the deploy / DNS agent (separate work
item); the application-side wiring (this doc) does NOT depend on the
legacy DNS record changing.

| Hostname              | DNS target              | Fly cert | Notes                              |
| --------------------- | ----------------------- | -------- | ---------------------------------- |
| `api.jpcite.com`      | `autonomath-api.fly.dev` | issued   | Canonical. Listed in OpenAPI `servers`. |
| `api.zeimu-kaikei.ai` | `autonomath-api.fly.dev` | issued   | Legacy. Stays live indefinitely.   |

Fly app + DNS:

```
flyctl certs add api.jpcite.com -a autonomath-api
# DNS: CNAME api.jpcite.com → autonomath-api.fly.dev
```

CORS allowlist (`JPINTEL_CORS_ORIGINS` Fly secret) MUST include both
apex / www / api variants of every active brand:

* `https://jpcite.com`, `https://www.jpcite.com`, `https://api.jpcite.com`
* `https://zeimu-kaikei.ai`, `https://www.zeimu-kaikei.ai`, `https://api.zeimu-kaikei.ai`
* (legacy `autonomath.ai` apex+www until that brand is fully retired)

Every browser-side feature 403s if any apex is missing. See
`docs/runbook/cors_setup.md`.

## Application-side migration signal

The legacy hostname stamps three response headers on every request:

```
Deprecation: true
Sunset: Wed, 31 Dec 2026 23:59:59 GMT
Link: <https://api.jpcite.com>; rel="successor-version"
```

Implementation: `src/jpintel_mcp/api/middleware/host_deprecation.py`
(`HostDeprecationMiddleware`). Wired in `api/main.py` near
`SecurityHeadersMiddleware` (both are pure response-header stampers).

Behavioural guarantees:

* Body and status code are untouched. Existing callers on the legacy
  host are bit-for-bit unchanged.
* Canonical-host requests pass through with no extra headers.
* Middleware never raises — all exception paths swallow.

Sunset date is hard-coded as `Wed, 31 Dec 2026 23:59:59 GMT` in
`host_deprecation.py`. This is a **client-facing hint, not a
commitment.** Bump the constant when the operator commits to a real
cutover date.

## SDK / docs guidance

Default examples and SDK base URLs MUST point at `api.jpcite.com`:

* `src/jpintel_mcp/api/main.py` — OpenAPI `servers[0]` is
  `https://api.jpcite.com`.
* `README.md`, `docs/quickstart.md`, MCP config snippets — `curl`
  examples and `BASE_URL` env-var defaults use `api.jpcite.com`.
* `pyproject.toml` `Homepage`, `package.json` `homepage`, etc. — same.
* `server.json`, `dxt/manifest.json`, `smithery.yaml` — same.

The legacy domain is mentioned ONLY in this migration doc and in
release notes describing the transition; it never appears in
quickstart / SDK / dashboard copy.

## Cutover decision rule

Monitor legacy-host traffic share weekly via the existing
`autonomath.query` log channel (already filtered by host upstream of
the middleware via the Fly request log). Cutover criterion:

> Legacy-host share **< 5% of total requests** for **4 consecutive
> weeks**, AND the top-3 legacy-host customers (by ¥3/req billable
> volume) have either migrated or been emailed twice with no response
> within 30 days.

Once the criterion fires, the next escalation step is:

1. **Soft-redirect** legacy host with HTTP 308 to canonical for GET /
   HEAD only (POST bodies cannot be redirected without breaking).
2. After another 4 weeks of <1% traffic share on the soft-redirect,
   **hard-deprecate** by configuring the legacy hostname to return
   410 Gone with a JSON envelope pointing at `api.jpcite.com`.
3. Eventually remove the legacy DNS record + Fly cert.

There is **no fixed timeline.** A customer that prepaid annually for
the legacy domain in 2026-Q4 can still use it through 2027 without
asking. Solo-ops can't deprecate routes faster than customers migrate.

## What this migration is NOT

* It is NOT a hostname-only redirect. Both hostnames serve the SAME
  application code with the SAME database. There is no "old API" still
  running somewhere.
* It is NOT a brand cutover. The `zeimu-kaikei.ai` brand was already
  the public face for AutonoMath; the migration to `jpcite.com` is
  about consolidating onto a single brand surface.
* It is NOT URL-versioned. Both hostnames serve `/v1/*`. There is no
  `/v2/` planned.

## Verification

After the deploy that ships `HostDeprecationMiddleware`:

```bash
# Legacy host — must carry the three headers
curl -sI https://api.zeimu-kaikei.ai/healthz | grep -iE 'deprecation|sunset|link'

# Canonical host — must NOT carry the three headers
curl -sI https://api.jpcite.com/healthz | grep -iE 'deprecation|sunset|link'
# (should print nothing for the legacy markers; Sunset/Deprecation are
# absent — Link headers from other middleware unrelated to migration
# may appear, those are fine.)

# Body identical between the two hosts (sanity)
diff <(curl -s https://api.zeimu-kaikei.ai/healthz) \
     <(curl -s https://api.jpcite.com/healthz)
# (empty diff)
```

## Related files

* `src/jpintel_mcp/api/middleware/host_deprecation.py` — middleware
* `src/jpintel_mcp/api/middleware/__init__.py` — re-export
* `src/jpintel_mcp/api/main.py` — wiring + OpenAPI `servers` entry
* `docs/runbook/cors_setup.md` — CORS allowlist procedure
