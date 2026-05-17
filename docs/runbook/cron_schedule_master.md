---
title: Cron Schedule Master Plan (Wave 37 SOT)
updated: 2026-05-16
operator_only: true
category: monitoring
---

# Cron Schedule Master Plan (Wave 37 SOT)

> **Status**: Authoritative single-source-of-truth for every scheduled GitHub
> Actions workflow that mutates the `autonomath.db` (9.7 GB) and/or
> `jpintel.db` (~352 MB) SQLite files.
> Last verified: 2026-05-12 (Wave 37 — 6-axis cumulative cron + freshness
> dashboard merge).
> Owners: solo ops — every schedule change MUST update this table in the
> same PR.

The table below is the **canonical** schedule. Any workflow file whose
`on.schedule.cron` value drifts from this table is considered a regression
and the `freshness-rollup-daily` cron will flag it via SLA breach.

## 1. Why this exists

Wave 31 — Wave 36 landed 19 axis-cohort cron workflows on top of the
pre-existing ~110 workflow ledger. Each axis was scheduled independently
and several drifted into the same UTC slot, producing:

- `autonomath.db` (9.7 GB) write contention: two crons holding a write
  lock on the same SQLite file at 18:45 UTC starved each other.
- `jpintel.db` (~352 MB) write contention: 23:00 UTC ran two daily ingest
  crons against `programs` + `tax_rulesets` at once.
- Fly machine queue pressure: 03:00–04:00 JST window saw four heavy crons
  spin a Fly machine simultaneously.

Wave 37 rebalances the schedule into four disjoint windows (ETL ingest,
precompute, monitoring, weekend reserved) so that no two cron jobs share
the same UTC minute on the same db, and so the daily freshness rollup at
10:00 JST sees a quiet system before reading the audit tables.

## 2. Lane definitions

| Lane | JST window | UTC window | Purpose | DB write |
|---|---|---|---|---|
| **A — ETL ingest** | 03:00–05:00 | 18:00–20:00 | external pulls, large writes, fresh corpus | `autonomath.db`, `jpintel.db` |
| **B — Precompute** | 05:00–07:00 | 20:00–22:00 | derived tables (cohort, risk, supplier chain) | `autonomath.db` |
| **C — Monitoring** | 07:00–09:00 | 22:00–00:00 | KPI digest, freshness, refund alerts, status probe | read-mostly |
| **D — Weekly / Monthly** | weekend nights | varies | weekly / monthly rollups, sweeps | varies |

## 3. Canonical schedule (Wave 37)

### Daily — Lane A (ETL ingest, 18:00–20:00 UTC)

| Workflow | UTC | JST | Avg duration | DB write |
|---|---|---|---|---|
| `knowledge-graph-vec-embed` | 00 17 * * * | 02:00 | ~12 min | autonomath |
| `portfolio-optimize-daily` | 30 17 * * * | 02:30 | ~10 min | autonomath |
| `houjin-risk-score-daily` | 00 18 * * * | 03:00 | ~8 min | autonomath |
| `edinet-daily` | 30 19 * * * | 04:30 | ~14 min | jpintel + autonomath |
| `adoption-rss-daily` | 00 20 * * * | 05:00 | ~10 min | jpintel (adoption_records) |

### Daily — Lane B (Precompute, 20:00–22:00 UTC)

| Workflow | UTC | JST | Avg duration | DB write |
|---|---|---|---|---|
| `axis2-precompute-daily` | 45 20 * * * | 05:45 | ~22 min | autonomath (cohort_5d, risk_4d, supplier_chain) |
| `ax-metrics-daily` | 15 21 * * * | 06:15 | ~6 min | autonomath (am_metrics) |
| `egov-amendment-daily` | 00 21 * * * | 06:00 | ~11 min | jpintel (laws) |
| `enforcement-press-daily` | 00 22 * * * | 07:00 | ~9 min | jpintel (enforcement_cases) |

### Daily — Lane C (Monitoring, 22:00–00:00 UTC)

| Workflow | UTC | JST | Avg duration | DB write |
|---|---|---|---|---|
| `budget-subsidy-chain-daily` | 00 23 * * * | 08:00 | ~8 min | autonomath read |
| `jpo-patents-daily` | 30 23 * * * | 08:30 | ~13 min | jpintel (patents) |
| `invoice-diff-daily` | 00 00 * * * | 09:00 | ~5 min | jpintel (invoice_registrants) |
| `freshness-rollup-daily` | 00 01 * * * | 10:00 | ~3 min | analytics/ snapshot |

### Weekly — Lane D (weekend nights)

| Workflow | UTC | JST | Avg duration |
|---|---|---|---|
| `municipality-subsidy-weekly` | 00 18 * * 0 | Sun 03:00 | ~24 min |
| `axis2def-promote-weekly` | 00 18 * * 4 | Thu 03:00 | ~32 min |
| `alliance-opportunity-weekly` | 00 20 * * 0 | Sun 05:00 | ~8 min |
| `multilingual-weekly` | 00 04 * * 0 | Sun 13:00 | ~38 min |
| `extended-corpus-weekly` | 00 02 * * 2 | Tue 11:00 | ~42 min |

### Monthly — Lane D

| Workflow | UTC | JST | Avg duration |
|---|---|---|---|
| `axis6-output-monthly` | 00 21 1 * * | Day1 06:00 | ~50 min |
| `subsidy-30yr-forecast-monthly` | 00 19 4 * * | Day4 04:00 | ~22 min |
| `industry-journal-mention-monthly` | 00 06 7 * * | Day7 15:00 | ~14 min |
| `nta-bulk-monthly` | 00 18 1 * * | Day1 03:00 | ~3 h |

## 4. Collisions resolved (Wave 37 rebalance)

| # | Old slot | Workflows in collision | New |
|---|---|---|---|
| 1 | 45 18 UTC daily | `axis2-precompute-daily` + `ax-metrics-daily` | precompute → 45 20, metrics → 15 21 |
| 2 | 00 23 UTC daily | `budget-subsidy-chain-daily` + `jpo-patents-daily` | budget → 00 23, jpo → 30 23 |

Each resolution preserves the original cron's intent: precompute still
runs before metrics (which reads from cohort_5d), and budget-subsidy-chain
still runs before jpo-patents (no data dependency in either direction,
just spread to avoid simultaneous Fly machine load).

## 5. SLA targets (read by `detect_freshness_sla_breach.py`)

| Source | Max staleness | Cron | Notes |
|---|---|---|---|
| 採択 RSS | 24 h | `adoption-rss-daily` | Mirasapo / J-Grants / prefecture feeds |
| 法令 (e-Gov) | 24 h | `egov-amendment-daily` | e-Gov amendments |
| 行政処分 | 24 h | `enforcement-press-daily` | press release polling |
| 市町村補助金 | 7 d | `municipality-subsidy-weekly` | 47 都道府県 fan-out |
| 特許 (JPO) | 24 h | `jpo-patents-daily` | JPO公開資料 |
| EDINET 開示 | 24 h | `edinet-daily` | XBRL / PDF |
| 適格事業者差分 | 24 h | `invoice-diff-daily` | NTA delta-only |
| 法人リスク score | 24 h | `houjin-risk-score-daily` | autonomath am_metrics |
| Cohort 5d / risk 4d | 24 h | `axis2-precompute-daily` | derived |
| AX metrics | 24 h | `ax-metrics-daily` | aggregate snapshot |
| 多言語 fill | 7 d | `multilingual-weekly` | en / ko / zh |
| 拡張 corpus | 7 d | `extended-corpus-weekly` | kokkai / shingikai / brand |
| 6 軸 monthly PDF | 31 d | `axis6-output-monthly` | report fan-out |

A breach triggers a Telegram alert via the bot configured by
`TG_BOT_TOKEN` (graceful no-op when secret missing).

## 6. How to add a new cron

1. **Pick the lane** based on what the cron writes (see §2).
2. **Pick the slot** — open this doc, find the lane's table, choose a slot
   that is at least 15 minutes from any other entry in the same lane.
3. **Add the workflow** under `.github/workflows/<name>.yml` with that
   cron expression.
4. **Update §3** in this doc with the row.
5. **Add SLA row** to §5 if the cron is user-visible.
6. **Run** `python scripts/cron/rollup_freshness_daily.py --dry-run` to
   confirm the rollup picks up the new cron.

## 7. Verification

```bash
# 1. List every cron schedule that currently differs from this doc.
python scripts/cron/rollup_freshness_daily.py --verify-schedule

# 2. Trigger the rollup once (writes analytics/freshness_rollup_YYYY-MM-DD.json).
python scripts/cron/rollup_freshness_daily.py

# 3. Inspect the SLA breach detector.
python scripts/cron/detect_freshness_sla_breach.py --dry-run
```

## 8. Why no LLM calls

Every cron in this table is pure SQLite + `httpx` + Python stdlib. The
production gate at `tests/test_no_llm_in_production.py` enforces zero LLM
imports under `scripts/cron/`. Operator-side LLM utilities live in
`tools/offline/` and never run from cron.

## 9. Honest gap

The freshness rollup snapshot includes a `last_run_at` field that is read
via `gh run list --workflow=<name> --limit 1`. This requires the GitHub
CLI to be installed on the runner and `GH_TOKEN` (read-only on Actions)
to be in scope. On local dev machines without `gh` configured the rollup
still runs but the `last_run_at` field is filled with `null` and flagged
`gh_unavailable` so SLA breach detection does not false-trigger.
