---
name: Signal — Sentry error batch
about: A new error class has appeared N times in Sentry. Convert from Sentry alert email or weekly digest.
title: "[bug] sentry error class: "
labels: ["bug", "triage"]
---

## Signal type

New Sentry error class

## Evidence

```
sentry_issue_id:       # e.g. AUTONOMATH-123
error_class:           # e.g. sqlite3.OperationalError, KeyError, ValidationError
first_seen (UTC):
count (since first seen):
affected_users:        # Sentry "users affected" count
sample_request_id:     # x-request-id from the Sentry event detail
```

## Stack trace (top 5 frames)

```
# Paste from Sentry — remove any API keys or PII before pasting
```

## Affected endpoint / code path

- [ ] `/v1/programs/search`
- [ ] `/v1/programs/{id}`
- [ ] Billing webhook handler (`src/jpintel_mcp/billing/`)
- [ ] MCP server (`src/jpintel_mcp/mcp/server.py`)
- [ ] Email / subscriber flow
- [ ] Data ingest / migration
- [ ] Other: ___

## Paying customer affected?

- [ ] Yes — escalate to PC0/PC1
- [ ] No (anonymous tier or internal path only) — PC1/PC2

## Priority

- [ ] PC0 — billing or auth broken for a paying key
- [ ] PC1 — > 20 unique Sentry events OR paying customer affected
- [ ] PC2 — < 20 events, anonymous tier only

## Fix plan

<!-- One sentence describing the likely fix. -->

## Definition of done

- [ ] Sentry issue resolved / muted (not just silenced)
- [ ] `pytest` passes including the failing path
- [ ] `ruff check src/` passes
- [ ] If PC0/PC1: root cause + prevention documented in `docs/_internal/incident_runbook.md`
