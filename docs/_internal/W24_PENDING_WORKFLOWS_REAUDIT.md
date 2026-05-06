# W24 Pending Workflows Re-audit

**2026-05-05** — 12 untracked `.github/workflows/*.yml` carried from W21-9. Non-destructive: no delete, no commit. All use `flyctl ssh`, zero LLM imports (`feedback_no_operator_llm_api` verified).

## A. Safe to commit now (0)
None — all 12 are scheduled cron.

## B. Commit at launch+24h (4)

| File | Cron UTC | Burn | Reason |
|---|---|---|---|
| `eligibility-history-daily` | `0 19 * * *` | 1 ssh ~16s | D1 ETL, idempotent, feeds D2. |
| `refresh-amendment-diff-history-daily` | `40 19 * * *` | 1 ssh ~30s | D2 diff, depends on D1. |
| `precompute-data-quality-daily` | `5 20 * * *` | 1 ssh ~5s | Single-row UPSERT, prevents 60s grace blow-up. |
| `meta-analysis-daily` | `0 21 * * *` | 1 ssh ~30s read-only | Internal mat-view rollup. |

Secrets: all `FLY_API_TOKEN`; meta also opt `SLACK_WEBHOOK_OPS`/`SENTRY_DSN`.

## C. Commit at launch+1week (4)

| File | Cron UTC | Burn | Reason |
|---|---|---|---|
| `idempotency-sweep-hourly` | `15 * * * *` | 24 ssh/day <1s | Lazy-evict covers correctness; can lag. |
| `narrative-sla-breach-hourly` | `0 * * * *` | 24 ssh/day | Telegram pusher (TG_BOT_TOKEN/TG_CHAT_ID); internal-only. |
| `ingest-offline-inbox-hourly` | `25 * * * *` | 24 ssh/day ~10s | Operator inbox drain, no customer impact. |
| `populate-calendar-monthly` | `0 18 5 * *` | 1 ssh/month ~5-10min, 67k row write | Heavy on 8.29 GB DB; smoke first. |

## D. Never commit / dedupe candidate (4)

| File | Reason |
|---|---|
| `refresh-sources-daily` | **DUP** of existing `refresh-sources.yml` daily branch (`22 18`). Pick one, not both. |
| `refresh-sources-weekly` | **DUP** of `refresh-sources.yml` weekly Saturday branch (`17 18 * * 6`). Pick one. |
| `narrative-audit-monthly` | Needs 1+ month of `am_narrative_*` corpus + TG bot proven first. |
| `precompute-recommended-monthly` | Same-day collision w/ `nta-bulk-monthly`; tool runs live without precompute. |

## Counts
B=4 / C=4 / D=4. No file action taken.
