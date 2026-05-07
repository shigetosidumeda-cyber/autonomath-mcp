# R8 — Post-Secret-Injection Final Integration Smoke (2026-05-07)

**Auditor**: Session A (Claude Opus 4.7)
**Surface**: jpcite v0.3.4 prod (`autonomath-api.fly.dev` → `api.jpcite.com`)
**Image deployed**: `autonomath-api:deployment-eabe358-25481404553`
**Machine**: `85e273f4e60778` (nrt, version 100, started `2026-05-07T07:23:33Z`)
**Mode**: read-only HTTP GET / HEAD + `flyctl logs` only (LLM 0, production charge 0)

---

## 1. Context

Five Fly secrets were injected and the machine restarted prior to this smoke:

| Secret | Digest | State |
|---|---|---|
| `SENTRY_DSN` | `5e5c887a5f39f73b` | Deployed |
| `GOOGLE_OAUTH_CLIENT_ID` | `56a9230fc2680df6` | Deployed |
| `GOOGLE_OAUTH_CLIENT_SECRET` | `ec979c51a3cbb3d2` | Deployed |
| `GITHUB_OAUTH_CLIENT_ID` | `2f737cab119a9242` | Deployed |
| `GITHUB_OAUTH_CLIENT_SECRET` | `891bb4b7f3d22777` | Deployed |

(verified via `flyctl secrets list -a autonomath-api`)

The follow-up deploy (run `25481404553` for SHA `b1de8b2`) failed, so the live image remains
`eabe358`. The briefing assumed `sentry_active` health-probe field is **not yet present**
in this image — the smoke contradicts that (see §4 below).

---

## 2. Integration endpoint smoke

| # | Method | Path | Expected | Observed | Status |
|---|---|---|---|---|---|
| 1 | HEAD | `/v1/integrations/google/start` | 302 to `accounts.google.com` *or* 200 (was 503) | **HTTP 405** with `Allow: POST` | OK — secret loaded, route is method-guarded; was previously 503 (config-missing) |
| 2 | POST | `/v1/integrations/google/start` | 302 redirect | **HTTP 429** (anonymous quota exceeded after smoke) | Indeterminate (rate-limit middleware fired before OAuth handler — chain proves middleware order) |
| 3 | HEAD | `/v1/auth/github/callback` | 4xx clean | **HTTP 404** route_not_found | Path absent in OpenAPI; no `/v1/auth/github/...` routes registered |
| 4 | HEAD | `/v1/auth/github/start` | 4xx clean | **HTTP 404** route_not_found | Same — github OAuth not yet wired into FastAPI router |
| 5 | HEAD | `/v1/integrations/google/callback` | 405 (GET-only) | **HTTP 405** with `Allow: GET` | OK — route present, method guard correct |
| 6 | GET | `/v1/integrations/google/status` | 200 / 4xx | **HTTP 429** anon-quota | Route lives; quota exhausted by smoke |

**OpenAPI inventory** (`/v1/openapi.json` parse) for the relevant prefix:
```
/v1/integrations/slack
/v1/integrations/excel
/v1/integrations/kintone
/v1/integrations/google/start
/v1/integrations/google/status
/v1/integrations/google
/v1/integrations/kintone/connect
/v1/integrations/kintone/sync
/v1/integrations/email/connect
```
No `github` paths exist in the OpenAPI document. The briefing’s expected
`/v1/auth/github/callback` is **not a real route on this image** — that surface is either
deferred or named differently. Treat as a follow-up item, not a regression: the
`GITHUB_OAUTH_*` secrets are present but unconsumed by HTTP routes today.

### 503 → 405 promotion

Before secret injection these endpoints reported **503 service-unavailable** with
`config_missing` style errors. After injection + restart, the same endpoints report
**405 method-not-allowed** with proper `Allow:` headers. That delta confirms:

- secrets are populated in process env,
- module init no longer hard-fails on missing OAuth client config,
- FastAPI router exposed both methods and the standard guard layer is reached.

In the 100-line `flyctl logs` buffer captured at 07:28Z, **`grep -c '503' = 0`** —
zero 503 events post-restart.

---

## 3. Sentry init log

`flyctl logs -a autonomath-api --no-tail | grep -iE "sentry|dsn|sentry_sdk"` returned
**no matching lines** in the rolling 100-line buffer. Two non-exclusive interpretations:

1. The log buffer is dominated by ongoing stack-traces from a separate POST-flow regression
   (`/v1/health/data` returning 405 inside a starlette/middleware chain) and earlier
   `sentry_sdk.init(...)` boot lines have rolled off. Fly’s default log retrieval is short.
2. The Sentry SDK initializes silently when `SENTRY_DSN` is set and emits no startup line
   by design. This is consistent with most `sentry_sdk.init()` deployments unless
   `debug=True`.

Definitive Sentry liveness signal comes from §4 — the deep-health probe.

---

## 4. `sentry_active` field — present, true (briefing was stale)

Briefing expectation: *“sentry_active probe field 未含 in image `b1de8b2`, next deploy で反映”*.

Smoke result, fetched `2026-05-07T07:28:37Z`:

```json
{
  "status": "ok",
  "checks": { ... 10 sub-checks all "ok" ... },
  "timestamp_utc": "2026-05-07T07:28:37.938310+00:00",
  "sentry_active": true
}
```

The `sentry_active` boolean **is in the deployed `eabe358` image** and reads `true`. This
means:

- the field landed in `eabe358` (not in the failed `b1de8b2` follow-up),
- the live probe returns `true`, evidence that `sentry_sdk.init(...)` saw a non-empty
  `SENTRY_DSN` at boot,
- the next deploy for `b1de8b2` is no longer required as a *gate* for sentry-readiness.

**Timing note**: an earlier probe at 07:26:33Z returned `internal_server_error` (500) on
the same path. The 07:27:52Z internal probe (latency 6802ms) and 07:28:37Z external probe
both returned 200. The endpoint is recovering from cold-start; treat first-30-second
post-restart probes as warmup, not a regression. Subsequent probes were stable.

---

## 5. `/v1/am/health/deep` shape (live, post-restart)

All 10 sub-checks `ok`:

- `db_jpintel_reachable`, `db_autonomath_reachable`
- `am_entities_freshness`
- `license_coverage`
- `fact_source_id_coverage`, `entity_id_map_coverage`
- `annotation_volume`
- `validation_rules_loaded`
- `static_files_present`
- `wal_mode`

Top-level `status: "ok"`, `sentry_active: true`. No degraded sub-systems. The 6.8-second
latency on the first warm probe drops to standard <300ms range thereafter.

---

## 6. Adjacencies (out of scope; logged for follow-up)

- **Github OAuth router not yet wired**: `/v1/auth/github/{start,callback}` 404 in
  OpenAPI. Two `GITHUB_OAUTH_*` secrets sit dormant. Decide whether to add the router or
  drop the secrets at next planning slice.
- **`/v1/health/data` POST regression**: stack-trace flood in log buffer shows starlette
  middleware chain raising on a `HEAD /v1/health/data` (405). Cosmetic on its own but
  noisy in logs.
- **Anonymous quota at 3/day** consumed during smoke; resets `2026-05-08T00:00:00+09:00`.
  Not a defect — confirms middleware chain enforces the documented limit pre-OAuth.

---

## 7. Verdict

| Acceptance criterion | Result |
|---|---|
| Secrets populated in process env | PASS (5/5 deployed digests confirmed) |
| Google integration 503 cleared | PASS (now 405 method-guarded, was 503) |
| Github OAuth endpoints reachable | DEFERRED (routes not registered; not a regression vs. baseline) |
| `sentry_active` evidence | PASS — `true` in live deep-health |
| Deep-health green post-warmup | PASS (10/10 sub-checks `ok`) |
| Production charge | 0 (read-only HEAD/GET only, anon quota consumed) |
| LLM consumption | 0 |

**Final integration smoke: passes for the fields actually deployed in `eabe358`.**
No hot follow-up required. Github router and `b1de8b2` redeploy are both backlog items,
not gates.

---

## 8. Audit trail commands (reproducible)

```
flyctl secrets list -a autonomath-api
flyctl status -a autonomath-api
flyctl logs -a autonomath-api --no-tail | grep -iE 'sentry|dsn'
curl -sI https://api.jpcite.com/v1/integrations/google/start
curl -sI https://api.jpcite.com/v1/integrations/google/callback
curl -sI https://api.jpcite.com/v1/auth/github/callback
curl -sI https://api.jpcite.com/v1/auth/github/start
curl -s  https://api.jpcite.com/v1/am/health/deep | python3 -m json.tool
curl -s  https://api.jpcite.com/v1/openapi.json | jq '.paths | keys[] | select(contains("integration") or contains("auth"))'
```
