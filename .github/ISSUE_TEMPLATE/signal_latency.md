---
name: Signal — Latency regression
about: P95 response time exceeds baseline. Convert from weekly digest or Grafana alert.
title: "[perf] P95 latency regression: "
labels: ["perf", "triage"]
---

## Signal type

P95 latency regression

## Evidence from digest

<!-- Paste the DuckDB query output from weekly_digest.py showing P95 values. -->

```
endpoint:
p95_ms (this week):
p95_ms (prior 4-week avg):
sample size (requests):
date range:
```

## Baseline reference

Baseline from `scripts/bench_api.py` run at: <!-- date -->

```
p50_ms:
p95_ms:
p99_ms:
```

## Affected endpoint

- [ ] `/v1/programs/search`
- [ ] `/v1/programs/{id}`
- [ ] `/v1/calendar/deadlines`
- [ ] `/v1/laws/search`
- [ ] Other: ___

## Likely root cause

- [ ] FTS5 query plan degraded (missing index on a new filter column)
- [ ] `_row_to_program()` serializing large JSON fields without cache
- [ ] DB file grown past WAL checkpoint threshold
- [ ] Fly.io machine undersized / memory pressure
- [ ] Cold start on first request after suspension
- [ ] Other (describe):

## Priority

- [ ] PC1 — P95 > 3000 ms (user-facing degradation)
- [ ] PC2 — P95 > 1500 ms (within spec but trending bad)

## Fix plan

<!-- e.g. "Add EXPLAIN QUERY PLAN, add covering index on (tier, prefecture, excluded)" -->

## Definition of done

- [ ] `scripts/bench_api.py` shows P95 ≤ 1000 ms on canonical queries
- [ ] `pytest tests/` passes
- [ ] No regression on cold-start latency
