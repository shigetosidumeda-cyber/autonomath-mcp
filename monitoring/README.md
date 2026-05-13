# Monitoring Boundary

`monitoring/` contains SLO targets, alert designs, dashboard definitions, and
operational metrics notes.

## Rules

- Config-like files may be versioned when they define intended production
  monitoring.
- Design-only files must not be described as already applied.
- Contractual SLA language belongs in public legal/commercial docs, not here.
- Production-write workflows and alert delivery paths need dry-run, secret
  behavior, and ownership documented before activation.

## Current Asset Types

- `sla_targets.yaml`: machine-readable target definitions
- `sla_targets.md`: human SLO explanation
- `sentry_alert_rules.yml`: alert rule design
- `sentry_dashboard.json`: dashboard design
- `seo_metrics.md`: organic discovery monitoring notes
- `uptime_metrics_endpoint.md`: design notes for uptime metrics

## Deploy Gate Contract

Production monitoring is not considered live unless both observability gates are
green:

- **Sentry gate**: `SENTRY_DSN` is present on the Fly app, `JPINTEL_ENV=prod`,
  `/v1/am/health/deep` reports `sentry_active=true`, and
  `docs/runbook/sentry_setup.md` Step 0 smoke emits a test event. The YAML in
  `monitoring/sentry_alert_rules.yml` remains the diffable source of truth, but
  it is not evidence that Sentry is active by itself.
- **Status probe gate**: `scripts/ops/status_probe.py` writes
  `site/status/status.json`; `scripts/cron/aggregate_status_alerts_hourly.py`
  reads it, maps any component with `status=down` to `critical`, writes
  `site/status/status_alerts_w41.json`, and increments `critical_count` for the
  SLA breach monitor. The probe job may exit 0 for cron stability; the alert
  gate is the sidecar severity, not the workflow exit code.

Monitoring is a trust asset when it describes real gates and measured behavior.
It is a planning asset when it is still design-only.
