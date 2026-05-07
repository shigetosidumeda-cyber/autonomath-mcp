# R8 — Cloudflare Cache `DYNAMIC` Fix (JSON Manifests)

**Date**: 2026-05-07
**Audit lane**: R8_LOAD_TEST_AUDIT (post-housekeeping perf cluster)
**Severity**: P1 — single-origin offload risk, HN/X spike OOM scenario
**Resolution**: edge-cacheable headers shipped via `site/_headers`, atomic commit

---

## 1. Problem

Live probe (2026-05-07 ~18:00 JST):

```
$ curl -sI https://jpcite.com/server.json | grep -iE "cache-control|cf-cache-status"
cache-control: public, max-age=3600
cf-cache-status: DYNAMIC

$ curl -sI https://jpcite.com/mcp-server.json | grep -iE "cache-control|cf-cache-status"
cache-control: public, max-age=3600
cf-cache-status: DYNAMIC

$ curl -sI https://jpcite.com/docs/openapi/v1.json | grep -iE "cache-control|cf-cache-status"
cache-control: public, max-age=3600
cf-cache-status: DYNAMIC

$ curl -sI https://jpcite.com/openapi.agent.json | grep -iE "cache-control|cf-cache-status"
cache-control: public, max-age=0, must-revalidate
cf-cache-status: DYNAMIC
```

All four manifests returned `cf-cache-status: DYNAMIC` despite the `_headers`
file declaring `Cache-Control: public, max-age=3600`. **Every** request was
forwarded to the Fly Tokyo origin — single-machine bottleneck under HN/X
spike load.

### Root cause

Cloudflare Pages' default cache list keys off file extension. The default
cacheable set covers HTML/CSS/JS/images/fonts but **does not include
`application/json`** unless one of:

- `s-maxage=N` is in `Cache-Control` (CF treats this as edge directive), or
- `CDN-Cache-Control` is set explicitly (CF-specific override), or
- the origin explicitly opts in via Page Rules / Cache Rules.

The previous `_headers` only had `max-age=3600` (browser-side directive).
With no edge-side hint, Pages defaulted to `DYNAMIC` (origin-pass-through).

`/openapi.agent.json` had **no rule at all** in `_headers` and fell through
to whatever default the surrounding `/*` block emitted (`max-age=0,
must-revalidate`) — even worse than the other three.

---

## 2. Fix (additive, no destructive overwrite)

`site/_headers` diff (excerpt — full diff in commit):

```
- /server.json
-   Content-Type: application/json; charset=utf-8
-   Cache-Control: public, max-age=3600
-   Access-Control-Allow-Origin: *
+ /server.json
+   Content-Type: application/json; charset=utf-8
+   Cache-Control: public, max-age=300, s-maxage=600
+   CDN-Cache-Control: public, max-age=600
+   Access-Control-Allow-Origin: *
```

Identical pattern applied to:

- `/openapi/*.json`
- `/v1/openapi*.json`
- `/docs/openapi/*.json`
- `/openapi.agent.json` (NEW rule — was missing)
- `/server.json`
- `/mcp-server.json`
- `/.well-known/mcp.json`
- `/bench/*.json`

Plus a header comment block above the rules documenting:

- 2026-05-07 R8 audit detection
- why CF Pages does not cache JSON by default
- why `s-maxage` + `CDN-Cache-Control` flip DYNAMIC → MISS → HIT
- the verify command (`curl -sI ... | grep cf-cache-status`)

### TTL choice rationale

- `max-age=300` (5 min) — short enough that genuine version bumps reach
  client-side MCP-discovery / agent-config readers within 5 min. JSON
  manifests change rarely (manifest-bump CLI cadence ≈ weekly), so 5 min
  browser TTL is a non-issue for freshness.
- `s-maxage=600` (10 min) — edge holds the response twice as long as
  browsers, giving the edge a chance to absorb burst traffic on top of
  natural client-side reuse. 10 min is the same TTL as `/index.html` and
  `/playground.html` (existing `_headers` policy), so we are not
  introducing a new class of staleness; we are just pulling JSON in line.
- `CDN-Cache-Control: public, max-age=600` — CF-specific belt-and-braces
  in case any future Page Rule overrides `Cache-Control` interpretation.
  CF documents this header as taking precedence over `Cache-Control` for
  edge decisions, so it survives any future global Cache Rule churn.

---

## 3. Live verify (post-deploy)

Pages auto-deploy is triggered by `pages-deploy-main.yml` on `main` push.
Expected post-deploy behavior:

```
# First request after deploy — edge has no entry yet
$ curl -sI https://jpcite.com/server.json | grep cf-cache-status
cf-cache-status: MISS

# Second request from same POP — served from edge
$ curl -sI https://jpcite.com/server.json | grep cf-cache-status
cf-cache-status: HIT
```

Watch list (run all four within 30s of deploy completion):

- `https://jpcite.com/server.json`
- `https://jpcite.com/mcp-server.json`
- `https://jpcite.com/docs/openapi/v1.json`
- `https://jpcite.com/openapi.agent.json`

If any stays at `DYNAMIC`, the most likely cause is a Cloudflare zone-level
Cache Rule overriding `_headers`. Inspect via dashboard
(Caching → Cache Rules) before reverting; do not weaken `_headers`
to force a DYNAMIC bypass.

### 2026-05-07 verify status: BLOCKED ON OPERATOR

Run `25487203368` (this commit `771f5507`) and the two prior runs all failed
at the `Publish to Cloudflare Pages` step with:

```
Cloudflare API returned non-200: 401
{"success":false,"errors":[{"code":10000,"message":"Authentication error"}]}
```

Live verify still shows `cf-cache-status: DYNAMIC` because **CF Pages has
not deployed any commit since 2026-05-07 ~07:00 JST** — the
`CLOUDFLARE_API_TOKEN` GitHub secret used by `pages-deploy-main.yml`
is revoked, expired, or scope-stripped.

**Operator action required** (out of scope of this commit):

1. Cloudflare dashboard → My Profile → API Tokens → create token with:
   - `Account.Cloudflare Pages: Edit` on jpcite project
   - `User.User Details: Read`
2. GH repo settings → Secrets → update `CLOUDFLARE_API_TOKEN`.
3. `gh workflow run pages-deploy-main.yml` to re-trigger deploy.
4. Re-run the verify curl loop above; expect `MISS → HIT` flip.

The `_headers` change in this commit is correct; it cannot be live-verified
until the auth blocker is cleared. This is consistent with the prior 2
commits (`5154e380`, `748232a9`) which also pushed valid changes that
have not deployed.

---

## 4. Origin-offload math

Pre-fix (DYNAMIC, 100% origin):

- 4 manifests × MCP-discovery crawler frequency
  (~1 req/min/agent under nominal load, 10-100×/min on HN spike)
- single Fly Tokyo machine, no autoscale on JSON paths
- HN front-page burst ≈ 5-30k unique visitors / 6h → ~1-5k MCP/agent fans
  → 4-20k extra origin reqs/h on JSON manifests alone

Post-fix (HIT after warmup, ≥95% edge-serve under steady state):

- s-maxage=600 + CDN-Cache-Control=600 → 10-min edge TTL
- per-POP cache: each Cloudflare POP independently caches; warm-up cost
  ≈ 1 req per POP per 10 min (CF runs ≈300 POPs, but only Tokyo + a
  handful of regions see measurable fan-out for jpcite traffic)
- realistic fan-out budget: ~30 POPs × 6 fills/h × 4 manifests ≈
  720 origin reqs/h, vs. pre-fix 4-20k/h

= **5-30× reduction in origin JSON manifest traffic** under spike.

---

## 5. Commit + push

```
perf(cf): cache rules for json manifests (DYNAMIC → HIT, single-origin offload)
```

Files staged:

- `site/_headers` (additive Edit, 32 insertions / 7 deletions per
  `git diff --stat`; no destructive overwrite)
- `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_CF_CACHE_FIX_2026-05-07.md`
  (this doc, force-added per audit-trail policy)

Push: `git push origin main` → `pages-deploy-main.yml` auto-trigger →
CF Pages builds + invalidates.

Pre-commit hook respected (no `--no-verify`).

---

## 6. Constraints satisfied

- LLM 0 (no API call, pure config edit)
- destructive 上書き 禁止 — Edit is additive (existing rules
  reformatted in-place with new directives appended; no rule
  removed or path renamed)
- pre-commit hook honored
- atomic commit (`_headers` + R8 doc only — no other dirty-tree files
  pulled in)

---

## 7. Follow-ups (deferred, non-blocking)

- Sentry/Plausible JSON event endpoints are on `*.plausible.io` /
  `*.sentry.io` — not in scope of `_headers`.
- `/v1/*` JSON responses (FastAPI) are origin-only; CF cannot cache
  POST/auth-bearing paths anyway. No change needed.
- Consider promoting `/sitemap*.xml` and `/rss.xml` from `max-age=3600`
  to `s-maxage=3600` as a separate audit lane — same DYNAMIC class
  but lower spike risk (crawler cadence is naturally throttled).
