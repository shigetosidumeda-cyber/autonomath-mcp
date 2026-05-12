# Wave 49 G3 — AX Layer 5 cron 5 workflows (PR state)

## Goal

Wave 49 G3 sub-goal: stand up the 5 AX Layer 5 cron jobs so that
each of the 5 dimensions (K predictive / L session / P composed /
Q time-machine / N anonymized) has a daily-or-monthly green tick
on the schedule axis (24h cycle target). All 5 ETL scripts landed
in Wave 47 Phase 2 (migrations 271–287), but their cron wire-up
was only partial through Wave 48. This PR closes the wire-up
gap with 5 new workflow files.

## Files (5)

| # | Workflow file | Cron (UTC) | Invokes | LOC |
|---|---|---|---|---|
| 1 | `.github/workflows/predictive-events-daily.yml` | `15 2 * * *` | `scripts/etl/build_predictive_watch_v2.py` | 47 |
| 2 | `.github/workflows/session-context-daily.yml` | `30 2 * * *` | `scripts/etl/clean_session_context_expired.py` | 46 |
| 3 | `.github/workflows/composed-tools-invocation-daily.yml` | `45 2 * * *` | `scripts/etl/seed_composed_tools.py` | 47 |
| 4 | `.github/workflows/time-machine-snapshot-monthly.yml` | `0 3 1 * *` | `scripts/etl/build_monthly_snapshot.py --gc` | 47 |
| 5 | `.github/workflows/anonymized-cohort-audit-daily.yml` | `15 3 * * *` | `scripts/etl/aggregate_anonymized_outcomes.py` | 49 |
| | **Total** | | | **236** |

## Cron layout (24h cycle, JST)

- 11:15 JST predictive-events
- 11:30 JST session-context purge
- 11:45 JST composed-tools re-seed
- 12:00 JST (monthly, 1st) time-machine snapshot
- 12:15 JST anonymized cohort aggregate

Sequenced 15min apart inside the Lane A tail window to avoid
collision with Wave 37 freshness-rollup (01:00 UTC) and the
existing Lane A daily crons (00:00 UTC invoice-diff etc.).

## Verify

- YAML valid 5/5 (yaml.safe_load pass)
- All `--dry-run` first, then real run guarded by
  `inputs.dry_run != 'true'` — manual `workflow_dispatch` defaults
  to dry-run for safe first ticks
- `concurrency.group` set per workflow with
  `cancel-in-progress: false` (snapshot integrity)
- `permissions: contents: read` — read-only, no commit/push side
  effect on any workflow (the ETL scripts write to SQLite, not
  to the repo)
- LLM API import 0 in all 5 invoked ETL scripts (per
  `feedback_no_operator_llm_api`)
- No `--no-verify`, no hook skip, no destructive op
- Worktree lane atomic at `/tmp/jpcite-w49-ax-layer5-cron.lane`
- Branch base: `origin/main` @ `fe47fdd49`

## Memory anchors honoured

- `feedback_dual_cli_lane_atomic`: worktree lane mkdir-claim
- `feedback_destruction_free_organization`: no rm/mv, append-only
- `feedback_no_operator_llm_api`: 0 LLM imports in invoked ETL
- `feedback_zero_touch_solo`: cron is unattended, no manual op
- `feedback_dont_extrapolate_principles`: 5 cron only, no scope
  creep into REST/MCP surface changes (REST endpoints unchanged)

## PR

(open after commit + push — PR# populated here on creation)
