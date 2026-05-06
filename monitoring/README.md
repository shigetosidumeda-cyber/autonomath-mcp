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

Monitoring is a trust asset when it describes real gates and measured behavior.
It is a planning asset when it is still design-only.
