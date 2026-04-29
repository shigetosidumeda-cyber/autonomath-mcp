# Uptime / Metrics Endpoint Design

> **Status**: design only. The implementation lives in `src/` which is
> off-limits for this design pass — the operator will execute the code
> change separately.
>
> **Owner**: 梅田茂利 / info@bookyou.net
> **Last reviewed**: 2026-04-29

## Problem

External uptime monitors (UptimeRobot, BetterUptime, Pingdom, or even just a
cron-curl from a second host) need a single HTTP endpoint that returns:

- A 200 if everything is fine
- A non-2xx if anything is degraded
- A small JSON body listing every metric the alert rules and dashboard
  reference

Today we have two pieces but no single source:

1. `GET /healthz` — Fly liveness probe. Returns 200 with `{"ok": true}` plus
   a DB ping. Too thin to power external monitoring; it doesn't surface
   webhook health, backup freshness, or quota errors.
2. `GET /v1/am/health/deep` — the rich check (10 sub-checks; see
   `src/jpintel_mcp/api/_health_deep.py`). Already returns a JSON document
   with `status`, `checks`, etc. Used by the operator dashboard and the
   "deep_health_am" MCP tool.

## Recommendation

**Expand `/v1/am/health/deep` rather than add a 3rd endpoint.** Adding a
new path would fragment the surface and force every external monitor to
poll two endpoints. The deep-health endpoint already has the right shape —
we just add five more `_check_*` functions and register them in the
`CHECKS` tuple.

## Five new sub-checks to add

Each check follows the existing contract in `_health_deep.py`:

```python
def _check_<name>() -> dict[str, Any]:
    """one-line docstring"""
    try:
        # query / probe
        ...
        if <bad>:
            return _check("warn" or "fail", "<details>", <value>)
        return _check("ok", "<details>", <value>)
    except Exception as e:
        return _check("fail", f"{type(e).__name__}: {e}", None)
```

### 5.1 `webhook_recent_5xx_count`

```python
def _check_webhook_recent_5xx_count() -> dict[str, Any]:
    """Count Stripe/Postmark webhook 5xx in the last hour from structlog
    archive. Should be 0; >5 = degraded."""
```

- **Source**: `analytics/webhook_log.jsonl` (already written by the
  webhook handlers; see `scripts/cron/webhook_health.py`).
- **Threshold**: 0 → ok, 1-5 → warn, >5 → fail.
- **Why**: backs the `webhook_handler_exception_rate` Sentry rule with a
  pull-based heartbeat that an external monitor can reach without Sentry.

### 5.2 `stripe_unsynced_usage_events`

```python
def _check_stripe_unsynced_usage_events() -> dict[str, Any]:
    """Count usage_events rows pending Stripe sync. Threshold 100 per
    sentry_alert_rules.yml::stripe_usage_events_unsynced."""
```

- **Source**: `SELECT COUNT(*) FROM usage_events WHERE stripe_synced_at IS NULL`
  on `jpintel.db`.
- **Threshold**: 0-99 → ok, 100-499 → warn, ≥500 → fail.
- **Why**: gives the operator a curl-able number that mirrors the Sentry
  metric, useful for ad-hoc verification.

### 5.3 `backup_recency`

```python
def _check_backup_recency() -> dict[str, Any]:
    """Return age of newest entry in analytics/backups.jsonl per DB.
    jpintel target ≤ 90 min; autonomath ≤ 26 hr."""
```

- **Source**: `analytics/backups.jsonl` (read newest line per `db_name`).
- **Threshold**: jpintel ≤90min ok / 90-180min warn / >180min fail;
  autonomath ≤26hr ok / 26-30hr warn / >30hr fail.
- **Why**: the `backup_integrity_failure` Sentry rule pages on missing
  cron run; this gives a continuous gauge useable by external probes.

### 5.4 `mrr_jpy`

```python
def _check_mrr_jpy() -> dict[str, Any]:
    """Read most recent MRR snapshot from analytics/billing_snapshot.jsonl.
    No threshold (this is a reporting metric, not a health one) — always
    returns ok unless the file is missing."""
```

- **Source**: a small JSONL file written by the same daily cron that emits
  the Sentry `billing.mrr_jpy` metric (see dashboard widget #1).
- **Threshold**: none (returns "ok" if file readable, "warn" if missing,
  "fail" if malformed).
- **Why**: lets the operator hit the endpoint and see live MRR without
  logging into Stripe Dashboard. Public visibility consideration: the
  endpoint requires `AnonIpLimitDep`, so anonymous callers are rate-limited
  but not blocked. For solo ops, this is fine — MRR being externally
  visible isn't a competitive concern at our scale.

  **Privacy note**: if MRR is sensitive to publish (e.g., investor
  optics), gate this check behind a header `X-Internal: <token>` instead
  of including it unconditionally. Default to off; flip on after weighing.

### 5.5 `anon_quota_error_rate`

```python
def _check_anon_quota_error_rate() -> dict[str, Any]:
    """Count errors in the anon-quota path in the last hour. Backs the
    Sentry rule anon_quota_lookup_error."""
```

- **Source**: `analytics/anon_quota_errors.jsonl` (need to add a structlog
  sink for this — currently exceptions just go to Sentry, not file).
- **Threshold**: 0-1 → ok, 2-9 → warn, ≥10 → fail.
- **Why**: closes the loop on the Sentry alert with a pull-style probe.

## Aggregate response shape (post-expansion)

After adding the five checks above, `GET /v1/am/health/deep` returns:

```json
{
  "status": "ok | degraded | unhealthy",
  "version": "v0.3.1",
  "timestamp_utc": "...",
  "evaluated_at_jst": "...",
  "checks": {
    "db_jpintel_reachable":     {"status": "ok", "details": "...", "value": 10790},
    "db_autonomath_reachable":  {"status": "ok", "details": "...", "value": 503930},
    "am_entities_freshness":    {"status": "ok", "details": "...", "value": 7},
    "license_coverage":         {"status": "ok", "details": "...", "value": 0.0083},
    "fact_source_id_coverage":  {"status": "ok", "details": "...", "value": 0.85},
    "entity_id_map_coverage":   {"status": "ok", "details": "...", "value": 0.461},
    "annotation_volume":        {"status": "ok", "details": "...", "value": 16474},
    "validation_rules_loaded":  {"status": "ok", "details": "...", "value": 6},
    "static_files_present":     {"status": "ok", "details": "...", "value": 8},
    "wal_mode":                 {"status": "ok", "details": "...", "value": "wal"},
    "webhook_recent_5xx_count": {"status": "ok", "details": "...", "value": 0},
    "stripe_unsynced_usage_events": {"status": "ok", "details": "...", "value": 12},
    "backup_recency":           {"status": "ok", "details": "...", "value": {"jpintel_min": 47, "autonomath_hr": 13}},
    "mrr_jpy":                  {"status": "ok", "details": "MRR snapshot from 2h ago", "value": 12340},
    "anon_quota_error_rate":    {"status": "ok", "details": "...", "value": 0}
  }
}
```

Aggregation rule (already coded): any `fail` → top-level
`unhealthy` (HTTP 500 or 503); any `warn` → `degraded` (HTTP 200,
status field flagged); all `ok` → `ok` (HTTP 200).

## External monitor configuration

Once the endpoint expansion ships, configure UptimeRobot (or equivalent)
with:

| Setting | Value |
|--|--|
| Monitor type | HTTP(s) keyword |
| URL | `https://api.zeimu-kaikei.ai/v1/am/health/deep` |
| Interval | 5 min |
| Keyword to match | `"status": "ok"` |
| Alert recipients | `info@bookyou.net` |
| Failure threshold | 2 consecutive checks (10 min) before alerting |

This deliberately fails the monitor on `degraded` not just `unhealthy` —
warns are still customer-visible degradation. The 2-check threshold avoids
single-flap pages.

## What this does NOT cover

- **Sentry quota exhaustion** — if Sentry stops accepting events, the
  alert rules silently die and this endpoint doesn't notice. Mitigation:
  weekly review of "Sentry → Stats → Quota Usage". A Sentry-side spike
  protection setting (Settings → Subscription → Spike Protection) caps
  the bill but doesn't notify us.
- **Cloudflare Pages outage** — the static site is on CF Pages; if it's
  down, this API endpoint is fine and will report green. CF status page
  monitoring is separate. Workaround: a second UptimeRobot monitor on
  `https://zeimu-kaikei.ai/` (the Pages root).
- **Stripe API outage** — Stripe's own incidents would surface as 5xx in
  webhook handlers. We catch those via the rule, not this endpoint.
  Stripe has its own status page; subscribe to it via email at
  `https://status.stripe.com/`.

## Estimated implementation effort

- 5 new sub-checks: ~2 hours code + ~1 hour test.
- New cron sink for `anon_quota_errors.jsonl`: ~30 min if we already
  emit structlog (which we do).
- New cron file `analytics/billing_snapshot.jsonl` writer: shared with
  the MRR Sentry metric work (~30 min).
- Total: **3-4 hours** to fully wire all five checks. Each check works
  standalone, so this can be incrementally shipped one at a time.

The only launch-blocker among the five is `backup_recency` — without it,
external monitors can't catch the case where the backup cron silently
stops running. Implement that one first; the others are nice-to-have.
