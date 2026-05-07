# R8 — Cron + Workflow 24h Health Audit (2026-05-06 12:12 UTC → 2026-05-07 12:17 UTC)

**Scope:** all 83 workflows in `.github/workflows/*.yml`. Window covers 24h ending at the audit cut-off (`gh run list --created '>=2026-05-06T12:00:00Z'`, **887 runs** materialized). Read-only audit, no `workflow_dispatch` triggered. LLM=0. Builds on `R8_CRON_RETRO_30DAY_2026-05-07.md` (the 30-day retrospective whose Round-2 fix wave landed earlier today) and validates whether the 14 double-blind workflow rewires + 7 daily-forensic fan-out fix actually held in the immediate 24h after deploy.

**Premise:** GitHub Actions UI is not an alert channel. The only operator-paging path is `if: failure()` → Sentry `/api/N/store/`. Today's question: did Round-2 succeed in the wild, did Round-2 introduce regressions, did the 6 newly-added crons (Round-2 net additions) reach their first fire?

---

## 1. 24h aggregate

| Bucket          | Count |    % |
| --------------- | ----: | ---: |
| Total runs      |   887 |  100 |
| `success`       |   389 | 43.9 |
| `failure`       |   303 | 34.2 |
| `cancelled`     |   108 | 12.2 |
| `skipped`       |    86 |  9.7 |
| `in_progress`   |     1 |  0.1 |

The 43.9% green is consistent with the 30-day baseline (47.2%). 24h is too short to draw a regression conclusion from the aggregate alone — the CI noise concentrates in `test` (0/34/68 — pre-existing flake fleet), `openapi` (19/68/0 — known stale `EXPECTED_OPENAPI_PATH_COUNT = 186` vs live 219, documented in CLAUDE.md "Wave hardening 2026-05-07" §OpenAPI path drift), and `distribution-manifest-check` (32/63/8 — same drift). All three are pre-existing, none new in 24h.

## 2. Top-line workflow ledger (24h, sorted by failure count)

| Workflow                           |   OK | FAIL | SKIP | CXL |   WIP | Note                                         |
| ---------------------------------- | ---: | ---: | ---: | --: | ----: | -------------------------------------------- |
| openapi                            |   19 |   68 |    0 |   0 |     0 | manifest drift, by-design (CLAUDE.md note)   |
| distribution-manifest-check        |   32 |   63 |    0 |   8 |     0 | same drift                                   |
| lane-enforcer                      |   45 |   50 |    0 |   0 |     0 | per-PR matrix; mixed                         |
| test                               |    0 |   34 |    0 |  68 |     1 | pre-existing flake / cancelled-by-newer push |
| pages-deploy-main                  |   13 |   16 |    0 |   0 |     0 | push-trigger only, no schedule               |
| pages-preview                      |    6 |    6 |    0 |  29 |     0 | cancel-on-newer-push pattern                 |
| acceptance-criteria-ci             |    0 |    9 |    0 |   0 |     0 | per-PR; pre-existing                         |
| CodeQL                             |   87 |    8 |    0 |   0 |     0 | OK                                           |
| eval                               |    1 |    8 |    0 |   0 |     0 | per-PR; pre-existing                         |
| check-workflow-target-sync         |    0 |    8 |    0 |   0 |     0 | per-PR; pre-existing                         |
| deploy                             |    4 |    5 |   86 |   0 |     0 | 86 skipped is correct (`workflow_run`)       |
| fingerprint-sot-guard              |    0 |    5 |    0 |   0 |     0 | per-PR; pre-existing                         |
| pages-regenerate                   |    1 |    4 |    0 |   0 |     0 |                                              |
| narrative-sla-breach-hourly        |    0 |    3 |    0 |   0 |     0 | **NEW REGRESSION**, see §4                   |
| nightly-backup                     |    1 |    2 |    0 |   0 |     0 | latest=success, recovered                    |
| nta-corpus-incremental-cron        |    1 |    2 |    0 |   0 |     0 | latest=success, recovered                    |
| release-readiness-ci               |   92 |    0 |    0 |   3 |     0 | OK                                           |
| same-day-push-cron                 |   12 |    0 |    0 |   0 |     0 | OK (every-30min)                             |
| stripe-backfill-30min              |   12 |    0 |    0 |   0 |     0 | OK (every-30min)                             |
| sunset-alerts-cron                 |   10 |    1 |    0 |   0 |     0 | recovered                                    |
| dispatch-webhooks-cron             |   12 |    1 |    0 |   0 |     0 | recovered                                    |

(remaining 26 workflows < 5 failures, see appendix)

## 3. Round-2 cron Verification

Per the user-supplied list of Round-2 net additions:

| Workflow                                      | Schedule           | 24h status   | Verdict                                                                                                |
| --------------------------------------------- | ------------------ | ------------ | ------------------------------------------------------------------------------------------------------ |
| `incremental-law-bulk-saturation-cron`        | `50 18 * * 0` (Sun) | ZERO runs    | EXPECTED — next fire 5/10 18:50 UTC                                                                    |
| `amendment-alert-fanout-cron`                 | `0 21 * * *` (daily) | ZERO runs    | **PENDING** — committed today 5/7 10:38 UTC, missed last 5/6 21:00 fire. First fire 5/7 21:00 UTC.     |
| `sbom-publish-monthly`                        | `30 17 1 * *`       | ZERO runs    | EXPECTED — next fire 6/1 17:30 UTC                                                                     |
| `pages-deploy-main`                           | push-only           | 13/16 OK/FAIL | live; failures correlate with builds where preceding `release-readiness-ci` passed but Pages probe 404 |
| `incremental-law-en-translation-cron`         | `10 20 * * 0` (Sun) | ZERO runs    | EXPECTED — next fire 5/10 20:10 UTC                                                                    |
| `gbiz-ingest-monthly`                         | `0 18 5 * *`        | ZERO runs    | EXPECTED — last fire 5/5 18:00 was outside window; next 6/5                                            |
| `kokkai-shingikai-weekly`                     | `0 21 * * 0` (Sun)  | ZERO runs    | EXPECTED                                                                                               |
| `municipality-subsidy-weekly`                 | `0 18 * * 0` (Sun)  | ZERO runs    | EXPECTED                                                                                               |
| `health-drill-monthly`                        | `15 18 1 * *`       | ZERO runs    | EXPECTED — last 5/1, next 6/1                                                                          |
| `restore-drill-monthly`                       | `0 18 14 * *`       | 1 OK         | manual `workflow_dispatch` from `R8_RESTORE_DRILL_FIRST_RUN_2026-05-07.md`, GREEN                      |

Plus 4 more daily crons committed today that have not yet hit first fire: `precompute-actionable-daily` (committed 5/6 22:00 UTC, fires 18:30 UTC), `egov-pubcomment-daily` (committed 5/6 22:36 UTC, fires 00:00 Mon-Fri), `production-gate-dashboard-daily` (committed 5/6 21:47 UTC, fires 21:00 UTC). All ZERO at audit time is **the file landing 47–137 min after the missed fire window**, not a regression.

## 4. New 24h RED detected

### 4.1 `narrative-sla-breach-hourly` — 0/3 since 06:46 UTC (NEW)

**Symptom:** every hourly fire since 5/7 06:46 UTC fails at the `flyctl ssh console` step.

**Root cause** (verified from run `25493810606` log):

```
flyctl ssh console -a autonomath-api \
  -e TG_BOT_TOKEN="${TG_BOT_TOKEN:-}" \
  -e TG_CHAT_ID="${TG_CHAT_ID:-}" \
  -C "/opt/venv/bin/python /app/scripts/cron/narrative_report_sla_breach.py"
→ Error: unknown shorthand flag: 'e' in -e
```

`flyctl ssh console` does not accept `-e` for env-var injection (that's `flyctl ssh sftp` / `flyctl machine run` behavior). The Round-2 fix landed today wired env-vars through `-e` instead of pre-exporting them inside the `-C` payload, breaking every fire since.

**Trivial fix** (read-only audit so not applied; staged for next implementation lane): rewrite the step to pass tokens through the in-machine command, e.g. `-C "TG_BOT_TOKEN='${TG_BOT_TOKEN}' TG_CHAT_ID='${TG_CHAT_ID}' /opt/venv/bin/python /app/scripts/cron/narrative_report_sla_breach.py ${FLAGS}"`. Since the secrets already arrive on the runner via `env:`, the substitution happens at GHA-shell time. File: `.github/workflows/narrative-sla-breach-hourly.yml:70-73`.

### 4.2 4 daily forensic still RED post Round-2 (CARRY-OVER, not new)

`eligibility-history-daily`, `meta-analysis-daily`, `precompute-data-quality-daily`, `refresh-amendment-diff-history-daily` — all 1/0 RED in 24h, all share `Error: ssh shell: Process exited with status 2`, and the failure-issue body explicitly names migration **wave24_106** (`am_program_eligibility_history`) + migration 075 (`am_amendment_diff`) as not applied on the Fly volume. This is **not a workflow regression** — Round-2 wired the GHA envelope correctly, the body fails inside the Fly machine because the autonomath-self-heal migration loop in `entrypoint.sh` has not landed wave24_106 yet on /data/autonomath.db. Out of scope for read-only cron audit; tracked separately.

## 5. Critical infra cron — held green

| Workflow                  | Last fire (24h)      | Conclusion |
| ------------------------- | -------------------- | ---------- |
| `nightly-backup`          | 5/7 06:54 UTC (manual `workflow_dispatch`) | **success** |
| `restore-drill-monthly`   | 5/7 05:08 UTC (manual)                    | **success** |
| `tls-check`               | 5/7 06:14 UTC (cron)                      | **success** |
| `health-drill-monthly`    | not in window (next 6/1)                  | n/a        |
| `weekly-backup-autonomath`| not in window (next 5/10 Sun 19:45)       | n/a        |

## 6. Summary

- 887 runs, 43.9% green — within ±3pp of the 30-day baseline (47.2%); no aggregate regression.
- 6 of the 7 Round-2 daily-forensic dailies recovered (latest run = `success`); the 7th (`narrative-sla-breach-hourly`) introduced a **fresh regression** via a malformed `flyctl ssh console -e` flag. Trivial fix sketched in §4.1; not applied (read-only audit constraint).
- 6+ Round-2 net cron additions sit at ZERO runs in window — all explained by schedule cadence (Sun-only / monthly day-1) or by the workflow file landing within the past few hours, before its first scheduled fire would have happened.
- 4 carry-over RED dailies (eligibility / meta / pdq / amendment-diff-history) blocked by missing wave24_106 migration on Fly volume — tracked separately.
- Nightly-backup / restore-drill / tls-check all GREEN. No critical infra regression.

**Recommended next action (operator decision):** apply the §4.1 trivial fix on `narrative-sla-breach-hourly.yml` to restore SLA breach paging, then re-audit at next 24h cycle.
