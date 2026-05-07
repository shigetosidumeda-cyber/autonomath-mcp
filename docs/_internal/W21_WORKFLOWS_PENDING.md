# W21 Workflows: commit selection + pending list

**Date**: 2026-05-05
**Audit context**: 22 workflow changes (8 modified, 14 untracked) sat in local
working tree post Wave 1-16. Selectively committing safe / launch-blocking
items; deferring high-frequency cron until launch + 1 quiet observation
window so we can catch runaway burn or breakage on Fly machines.

Repo is **public** on GitHub (`shigetosidumeda-cyber/autonomath-mcp`), so
GHA minutes are unmetered. The deferral is about **operational risk** on the
Fly target machines (`autonomath-api`), not GHA cost.

## Committed in this audit (10 files)

### Modified (8) — W14-12 audit follow-ups

All 8 modifications are **schedule offset fixes** to break a 19:30 UTC
contention cluster identified in the W14-12 audit, plus one backup-script
swap. They reduce burn (no new schedules, just `+5/+10/+15 min` shifts on
already-active workflows) and align `weekly-backup-autonomath.yml` with the
new `scripts/cron/backup_autonomath.py` (proper `autonomath-` prefix vs the
hard-coded `jpintel-` prefix in legacy `scripts/backup.py`).

| File | Change |
|---|---|
| `eval.yml` | cron `30 19 * * *` → `45 19 * * *` (+15 min off the 19:30 cluster) |
| `index-now-cron.yml` | INDEXNOW_HOST/KEY rebrand: `zeimu-kaikei.ai` → `jpcite.com` |
| `ingest-daily.yml` | cron `0 19 * * *` → `15 19 * * *` (+15 min off eligibility-history) |
| `nta-bulk-monthly.yml` | cron `0 18 1 * *` → `10 18 1 * *` (+10 min off precompute-recommended) |
| `refresh-sources.yml` | daily branch `17 18` → `22 18` (+5 min off nightly-backup) |
| `self-improve-loop-h-daily.yml` | cron `30 18` → `35 18` (+5 min off index-now) |
| `sunset-alerts-cron.yml` | hourly `15 *` → `20 *` (+5 min off idempotency-sweep) |
| `weekly-backup-autonomath.yml` | swap `scripts/backup.py` → `scripts/cron/backup_autonomath.py` (correct file prefix) |

### Untracked (2) — workflow_dispatch only / launch-blocking

| File | Trigger | Why commit |
|---|---|---|
| `rebrand-notify-once.yml` | `workflow_dispatch` only, `dry_run=true` default | One-shot Postmark blast for the AutonoMath → jpcite rename. Safe: no schedule. Dry-run default means a misfire just logs. |
| `stripe-version-check-weekly.yml` | weekly Mon `0 0 * * 1` | Catches Stripe API version drift that would silently corrupt ¥3/billable unit billing. Runs `scripts/cron/stripe_version_check.py` via flyctl ssh — secrets live on Fly. Weekly cadence = trivial burn. |
| `stripe-backfill-30min.yml` | every 30 min `5,35 * * * *` | **Launch-blocking**: closes the gap between Stripe meter posts and billing reconciliation. ¥3/billable unit metered model needs this for invoice accuracy. Runs via flyctl ssh — load lands on `autonomath-api` Fly machine. Watch hourly during launch +24h. |

## Deferred to post-launch (12 files)

Reason for each: untested in production + adds cron load to Fly machines
that we want quiet during the launch +24h soak. None blocks a public deploy
— the routes / scripts they invoke are precompute / housekeeping layers that
gracefully degrade when stale by 1-7 days.

### Hourly (3) — highest burn risk

| File | Trigger | Hold reason |
|---|---|---|
| `idempotency-sweep-hourly.yml` | hourly `15 * * * *` | Sweeps `idempotency_cache` table (mig 087). Cache sweep can wait — entries expire on next access regardless. 24 runs/day on Fly machine = noisy; smoke-test manually first. |
| `narrative-sla-breach-hourly.yml` | hourly `0 * * * *` + `push:` | `push:` trigger fires on every commit to main — that's a noise multiplier we don't want during launch-week velocity. SLA breach reporting is internal-only; no customer impact for 1-week delay. |
| `ingest-offline-inbox-hourly.yml` | hourly `25 * * * *` | Pulls operator-curated offline inbox into corpus. No customer impact if the inbox sits 24-72h. Manual `workflow_dispatch` available. |

### Daily (4)

| File | Trigger | Hold reason |
|---|---|---|
| `eligibility-history-daily.yml` | daily `0 19 * * *` | Snapshot history table — useful for `track_amendment_lineage_am` audit trail but tool degrades to "no history yet" not error. Wait for first launch-week ingest to land. |
| `precompute-data-quality-daily.yml` | daily `5 20 * * *` | Computes data-quality scores for the 11,684-row programs corpus. Existing tier scoring (S/A/B/C) already covers 99% of customer-facing UX; this is for ops dashboards. |
| `refresh-amendment-diff-history-daily.yml` | daily `40 19 * * *` | Opens a GH issue automatically on failure — adds noise during launch triage. `am_amendment_diff` table is at 0 rows; failure mode is loud and well-understood, just not pre-launch. |
| `refresh-sources-daily.yml` | daily `5 18 * * *` | **Overlaps** with already-live `refresh-sources.yml` (which has its own daily/weekly/monthly tier branches at `22 18` / `17 18 * * 6` / `17 18 1 * *`). Committing both would double-fire the daily tier-S/A scan. Pick one post-launch. |

### Weekly / monthly (5)

| File | Trigger | Hold reason |
|---|---|---|
| `refresh-sources-weekly.yml` | weekly Sun `0 18 * * 0` | Same overlap reason as `refresh-sources-daily.yml` — the existing `refresh-sources.yml` already has a weekly Saturday branch. Pick one path. |
| `narrative-audit-monthly.yml` | monthly day-1 `0 0 1 * *` | Internal narrative audit; first run can wait until at least 1 month of post-launch corpus exists to audit against. |
| `populate-calendar-monthly.yml` | monthly day-5 `0 18 5 * *` | Populates `program_post_award_calendar` (mig 098). Calendar tools degrade to "no entries yet" not error. |
| `precompute-recommended-monthly.yml` | monthly day-1 `0 18 1 * *` | Same day as `nta-bulk-monthly` (which we already offset by +10 min). Precompute job can wait — `recommend_programs_for_houjin` runs live without it (just slower). |

## Re-enable plan

After 24h post-launch quiet window:

1. Pick one of `refresh-sources-daily.yml` / `refresh-sources-weekly.yml` and
   **delete** `refresh-sources.yml` (or vice versa) to avoid the double-fire.
2. Smoke-test each hourly via `gh workflow run <file>` once with `dry_run` if
   the workflow exposes one, watch the Fly machine CPU for 1 cycle.
3. Commit in pairs (related script + workflow) so a rollback is single-`git
   revert`.
4. Watch `metrics.cron_runs_24h` for 48h after each enable; abort if Fly
   machine load > 70% sustained.

## Excluded from this list

- `release.yml` (modified May 5 11:47, was already added in commit `6f77df0`
  Wave 19 push) — diff is the npm `@jpcite/agents` publish step which is
  already on remote.
