# Health Monitoring Runbook

Operator-only — do not link from public docs. Excluded from mkdocs build via
`exclude_docs: _internal/`.

## Overview

AutonoMath provides `/v1/am/health/deep` for production uptime monitoring.
This endpoint bypasses anonymous IP rate limit (`AnonIpLimitDep`) so monitor
pings don't burn the 50/month/IP quota. The route is mounted on
`health_router` in `src/jpintel_mcp/api/autonomath.py` (line 75), included by
`api/main.py:714` without the `AnonIpLimitDep` dependency that protects
all other `/v1/am/*` paths.

## Endpoint specification

```
GET https://api.autonomath.ai/v1/am/health/deep
```

Returns 200 with `DeepHealthResponse` (`api/_response_models.py:515`):

- `overall.status`: `"healthy"` / `"degraded"` / `"unhealthy"`
- `checks`: `{ jpintel_db, autonomath_db, wal_mode, migrations, precompute_cache, ... }` (10-check aggregate, see `api/_health_deep.py`)
- `timestamp`: ISO 8601

The same logic is exposed via the `deep_health_am` MCP tool
(`mcp/autonomath_tools/health_tool.py`) for clients that prefer MCP.

## Recommended monitoring tools

### Cloudflare Health Check (recommended)

- Cloudflare dashboard → **Health Checks** → **Create**
- Type: HTTPS
- Method: GET
- URL: `https://api.autonomath.ai/v1/am/health/deep`
- Interval: 60 sec
- Expected codes: `200`
- Response Body Match: `healthy` (substring)
- Notification: **Cloudflare Notifications** → email to `info@bookyou.net`

Free on any Cloudflare plan that already fronts `autonomath.ai`. Multi-region
probing included by default.

### UptimeRobot (alternative)

- Add monitor → **HTTP(s)**
- URL: `https://api.autonomath.ai/v1/am/health/deep`
- Interval: 5 min (Free plan limit)
- Keyword: `healthy`
- Notification: email to `info@bookyou.net`

Use when Cloudflare Health Checks are unavailable (e.g. plan downgrade).

### Pingdom (premium)

- 1 min interval
- Multi-region probes
- Use only if SLA reporting demands sub-minute resolution

## Alert criteria

| status | action | escalation |
|---|---|---|
| healthy | none | — |
| degraded | email | 30 min |
| unhealthy | email + `flyctl status -a autonomath-api` | 5 min |

`degraded` typically means one non-critical check failed (e.g. precompute
cache stale). `unhealthy` means a core dependency is down (jpintel.db,
autonomath.db, or migrations mismatch).

## Manual probe

```bash
curl -sS https://api.autonomath.ai/v1/am/health/deep | jq
```

Expected: `overall.status = "healthy"`, every entry under `checks` reports
`"ok"`. If a check is `"degraded"` or `"unhealthy"`, follow up with
`flyctl logs -a autonomath-api` and the failure-mode table below.

## Quota implications

| path | quota |
|---|---|
| `/healthz` (Fly internal) | not counted (Fly auto health check) |
| `/v1/am/health/deep` | bypasses `AnonIpLimitDep` (health_router) |
| every other `/v1/am/*` | 50/month/IP cap |

Monitors must hit **only** `/v1/am/health/deep`. Probing `/v1/programs` or
similar from a fixed monitor IP will exhaust the anonymous quota and trigger
429 for any real client behind the same egress.

## Failure modes

### `database disk image is malformed`

- `entrypoint.sh` runs `PRAGMA integrity_check` and auto-removes a corrupt
  copy of `jpintel.db` / `autonomath.db` on boot.
- During recovery `/v1/am/*` returns 503 (graceful degradation); core
  `/v1/programs` still serves from jpintel.db when only autonomath.db is
  affected.
- Restore: pull latest backup from R2 → place under `/data` → `flyctl machines restart -a autonomath-api`. See `dr_backup_runbook.md`.

### `autonomath.db` missing on boot

- `entrypoint.sh` downloads from `AUTONOMATH_DB_URL` (R2 presigned) when
  the env var is set.
- If unset: `/v1/am/*` returns 503; `/v1/programs` and other jpintel-only
  paths continue to serve normally.

### Fly machine crash

- Auto-restart (Fly nrt region, `fly.toml` policy).
- 10-restart cap reached: `flyctl machine destroy <id>` then `fly deploy`.

## See also

- `docs/_internal/dr_backup_runbook.md` — R2 backup pull + restore (M5)
- `docs/observability.md` — metrics dashboards, log routing (C2, internal)
- `docs/disaster_recovery.md` — public-facing DR posture (A7)
