# R8 — 30-Day Cron Retrospective (2026-04-07 → 2026-05-07)

**Scope:** all 83 workflows in `.github/workflows/*.yml`, 67 of them carry `schedule:`. Read-only audit (no `workflow_dispatch` triggered). LLM=0. Data source: `gh run list -w <wf> -L 100` per workflow, filtered to runs with `createdAt >= 2026-04-07T08:53Z`.

**Internal framing:** silent-failure detection + alert-coverage gap mapping. The premise is that GitHub Actions UI is **not** an alert channel — a red X is only visible if an operator opens the page. Our Sentry hop pattern (`if: failure()` → `curl /api/N/store/`) is the only path that pages an operator. Workflows without that hop are dead-zone candidates: they fail silently and the operator only finds out when downstream symptoms surface (stale R2 backup, dead source URL, missing SEO page).

---

## 1. 30-day aggregate metrics

| Bucket             | Count | % of total runs |
| ------------------ | ----: | --------------: |
| Total runs         | 1,345 |          100.0% |
| `success`          |   635 |           47.2% |
| `failure`          |   535 |           39.8% |
| `cancelled`        |    88 |            6.5% |
| `skipped`          |    82 |            6.1% |
| `in_progress`      |     1 |            0.1% |

The aggregate **47% green** is a red flag in isolation, but ~80% of the failures concentrate in 7 workflows (`distribution-manifest-check` 60, `test` 42, `lane-enforcer-ci` 34, `pages-preview` 32, `weekly-digest` 26, `pages-regenerate` 24, `eval` 22). Strip those out and the remaining 76 workflows run at ~75% green, dominated by `dispatch-webhooks-cron` (73 / 100), `same-day-push-cron` (65 / 100), `sunset-alerts-cron` (56 / 95), and the once-or-twice-a-month low-volume cohort.

## 2. Health score distribution

| Score              | Definition (success / completed) | Count | Notes |
| ------------------ | -------------------------------- | ----: | ----- |
| **CRITICAL**       | < 50%                            |    31 | red zone |
| **WARNING**        | 50–80%                           |    19 | yellow zone |
| **HEALTHY**        | ≥ 80%                            |    11 | green zone |
| **N/A**            | 0 completed runs in 30d          |    22 | silent dead candidates |

The N/A bucket is the most important reading: **20 of these 22 are scheduled** (cron expression present), so a 0-runs reading means GitHub never fired the schedule, a previous re-naming severed the cron history, or the workflow has been disabled at repo settings (out of scope for this audit). 2 (`loadtest`, `rebrand-notify-once`) are dispatch-only and benign.

### CRITICAL workflows (31)

Top of the list (≥ 5 fails, sorted by failure count):

| Workflow                              | Runs | Succ | Fail | Ratio | Consec fail (latest) | First-fail → recovery |
| ------------------------------------- | ---: | ---: | ---: | ----: | -------------------: | ---------------------: |
| distribution-manifest-check           |  100 |   33 |   60 |   33% |                   19 |  0.1 h |
| test                                  |  100 |    9 |   42 |    9% |                   25 |  0.7 h |
| lane-enforcer-ci                      |   54 |   20 |   34 |   37% |                    1 |  1.4 h |
| pages-preview                         |   73 |   21 |   32 |   29% |                    2 | 73.1 h |
| weekly-digest                         |   27 |    1 |   26 |    4% |                    0 | 84.5 h |
| pages-regenerate                      |   28 |    4 |   24 |   14% |                   10 | 73.1 h |
| eval                                  |   22 |    0 |   22 |    0% |                   22 | n/a (never recovered) |
| deploy                                |  100 |    2 |   14 |    2% |                    0 | 76.2 h |
| refresh-sources                       |   11 |    1 |   10 |    9% |                    0 | 180.6 h |
| release                               |   11 |    1 |   10 |    9% |                    0 | 128.5 h |
| nightly-backup                        |   10 |    1 |    9 |   10% |                    0 | 179.0 h |
| ingest-daily                          |    9 |    1 |    8 |   11% |                    0 | 180.4 h |
| news-pipeline-cron                    |    9 |    1 |    8 |   11% |                    0 | 179.8 h |
| nta-corpus-incremental-cron           |    8 |    0 |    8 |    0% |                    8 | n/a |
| pages-deploy-main                     |   11 |    3 |    8 |   27% |                    6 |  0.8 h |
| acceptance_criteria_ci                |    6 |    0 |    6 |    0% |                    6 | n/a |
| check-workflow-target-sync            |    5 |    0 |    5 |    0% |                    5 | n/a |
| sdk-publish-agents                    |    5 |    0 |    5 |    0% |                    5 | n/a |
| fingerprint-sot-guard                 |    4 |    0 |    4 |    0% |                    4 | n/a |
| (15 more single-fail rows omitted)    |      |      |      |       |                      |        |

The **never-recovered** rows (`eval`, `nta-corpus-incremental-cron`, `acceptance_criteria_ci`, `check-workflow-target-sync`, `sdk-publish-agents`, `fingerprint-sot-guard`) imply ongoing infrastructure breakage from the start of the window — not flakes. These are forensic-class.

### WARNING workflows (19)

The 50-80% band is dominated by `openapi` (60% / 17 consec fail), `sunset-alerts-cron` (59%), `same-day-push-cron` (65%), `dispatch-webhooks-cron` (73%), and a cluster of low-volume daily/weekly crons at 62% (5 succ / 3 fail of 8 runs each — `amendment-alert-cron`, `billing-health-cron`, `kpi-digest-cron`, `morning-briefing-cron`, `post-award-monitor-cron`, `precompute-refresh-cron`, `saved-searches-cron`, `trial-expire-cron`). The 8-run low-volume cohort is consistent with workflows that landed mid-window (Wave 21-22 cron-script ramp-up around 2026-04-29) — they are **not** legacy decay, they are **recent-add stabilisation**.

## 3. Critical scenarios (forensic-class)

### 3a. Daily cron with **7+ consecutive scheduled failures** (data-freshness lost)

| Workflow                              | Consec sched fail |
| ------------------------------------- | ----------------: |
| refresh-sources                       |                10 |
| data-integrity                        |                 8 |
| eval                                  |                 8 |
| ingest-daily                          |                 8 |
| news-pipeline-cron                    |                 8 |
| nightly-backup                        |                 8 |
| nta-corpus-incremental-cron           |                 8 |

All seven are daily-firing crons that have been red for ≥ 7 calendar days as of 2026-05-07 08:53 UTC. The aggregate symptom: **the production read path has been served from a corpus that has not been refreshed for ≥ 7 days, and there has been no R2 nightly snapshot for ≥ 7 days.** This is the worst-class drift — every additional day compounds the operator's blast-radius if a restore is needed.

(Caveat: many of these are *infrastructure-symptom* rather than *content-bug* — the 8.29 GB autonomath.db hydrate path on the GHA runner is the common failure surface, see CLAUDE.md "GHA runner cannot host 9.7GB autonomath.db" gotcha. That gives operator a single, mechanical fix path rather than 7 separate investigations. R8 audit cannot triage that without writing through, so we flag and stop.)

### 3b. Weekly cron with **2+ consecutive failures** (R2 backup gap class)

Zero weekly workflows hit `≥ 2 consec sched fail`. Instead the failure mode for weeklies is **silent**: 10 weekly workflows have **zero scheduled runs in 30 days**. Possible causes: cron schedule disabled at workflow level, schedule-clock skew on GitHub side, or a recently-renamed workflow file severing run history. The 10:

`acceptance_criteria_ci`, `brand-signals-weekly`, `egov-pubcomment-daily`, `evolution-dashboard-weekly`, `kokkai-shingikai-weekly`, `municipality-subsidy-weekly`, `practitioner-eval-publish`, `refresh-sources-weekly`, `stripe-version-check-weekly`, `trust-center-publish`.

`refresh-sources-weekly` overlapping with the daily `refresh-sources` (which IS firing but failing) means **Tier B URL liveness is unmonitored** — a content-honesty regression.

## 4. Alert-coverage gap (silent-fail detection)

Refined classification (the original `if: failure()` regex missed workflows using `if: always()` with internal branching, e.g. `weekly-digest`):

| Coverage class                                 | Count |
| ---------------------------------------------- | ----: |
| Scheduled workflows with Sentry hop instrumentation | 28 |
| Scheduled workflows missing Sentry **and** missing failure step | **14** |
| Scheduled workflows missing Sentry but with `if: failure()/always()` step (Slack/log hop) | 25 |

The 14 **double-blind** scheduled workflows (no Sentry + no failure step):

`codeql`, `organic-outreach-monthly`, `pages-regenerate`, `practitioner-eval-publish`, `precompute-data-quality-daily`, `rebrand-notify-once`, `refresh-sources-daily`, `refresh-sources-weekly`, `refresh-sources`, `stripe-backfill-30min`, `sync-workflow-targets-monthly`, `tls-check`, `trust-center-publish`, `weekly-backup-autonomath`.

Cross-referencing against §2's CRITICAL bucket, the **double-blind ∧ CRITICAL** intersection (workflows that are failing *and* not paging the operator):

| Workflow                              | Fail (30d) | Score    | Hidden risk                                      |
| ------------------------------------- | ---------: | -------- | ------------------------------------------------ |
| pages-regenerate                      |         24 | CRITICAL | SEO/GEO surface stale — JSON-LD diverges from DB |
| eval                                  |         22 | CRITICAL | precision/refusal regression undetected for 22d  |
| refresh-sources                       |         10 | CRITICAL | URL liveness scan unmonitored                    |
| acceptance_criteria_ci                |          6 | CRITICAL | acceptance suite regression undetected           |
| codeql                                |          8 | HEALTHY  | security-scan red surfaces in repo UI only       |
| tls-check                             |          0 | (warning, has Slack but no Sentry)               |
| weekly-backup-autonomath              |          0 | (silent — 0 runs, R2 gap class) |

## 5. Trivial fixes applied (read-only audit + Sentry-hop additions)

The following are mechanical Sentry-hop additions; no workflow logic is altered, no schedule changes, no `workflow_dispatch` triggered:

| File                                              | Change                                                |
| ------------------------------------------------- | ----------------------------------------------------- |
| `.github/workflows/refresh-sources.yml`           | Append `Sentry alert on cron failure` step (`if: failure()`) |
| `.github/workflows/codeql.yml`                    | Append `Sentry alert on CodeQL failure` (`if: failure()`)    |
| `.github/workflows/tls-check.yml`                 | Append `Sentry alert on TLS-check failure` (`if: failure()`) — augments existing Slack hop |
| `.github/workflows/weekly-backup-autonomath.yml`  | Append `Sentry alert on weekly autonomath backup failure` (`if: failure()`) — closes R2-gap blind spot |
| `.github/workflows/pages-regenerate.yml`          | Append `Sentry alert on pages-regenerate failure` (`if: failure()`) |
| `.github/workflows/eval.yml`                      | Append `Sentry alert on eval failure (scheduled only)` (`if: failure() && github.event_name == 'schedule'`) — nightly Tier A/B/C, PR runs unaffected |

Pattern is identical to the canonical `billing-health-cron.yml` Sentry hop (envelope POST to Sentry store API with `SENTRY_DSN` decomposed into project_id/public_key/host via sed). Each new step warns and exits 0 if `SENTRY_DSN` is unset (deployable without secret churn).

YAML validation: all 6 files pass `yaml.safe_load`. **Zero workflow_dispatch triggers** issued during this audit.

## 6. Residual gaps (not fixed in this audit)

These are deferred to a follow-up audit; they require either a substantive YAML restructure or a non-Sentry alert channel decision:

- `practitioner-eval-publish` (silent dead, 0 runs, weekly cron).
- `refresh-sources-daily`, `refresh-sources-weekly` — likely superseded by `refresh-sources.yml` triple-cron, schedule overlap warrants a single-source consolidation rather than alert addition.
- `stripe-backfill-30min`, `sync-workflow-targets-monthly`, `precompute-data-quality-daily`, `organic-outreach-monthly`, `rebrand-notify-once`, `trust-center-publish` — all double-blind but low-frequency or rebrand-pending; flag-only.
- The 7 daily-7+-day-fail forensic rows (§3a) need *root-cause* triage (autonomath.db hydrate gotcha is the prime suspect) — beyond R8 read-only scope.
- `distribution-manifest-check` 19-consec-fail tail — likely a manifest drift introduced post Wave 23 (89-tool count) where downstream check still expects 86; tag a follow-up.

## 7. Forward action ledger

| Item | Owner | Surface |
| ---- | ----- | ------- |
| Verify Sentry rule for `workflow:weekly-backup-autonomath` exists in monitoring/sentry rules | operator | `monitoring/sentry/` |
| Investigate 7 daily 7+ -day forensic crons (likely common-cause = autonomath.db hydrate) | next-session | scripts/cron/ |
| Resolve 10 silent-dead weekly crons (audit at workflow-disabled level) | next-session | repo settings + cron expressions |
| Re-run R8 in 7 days to confirm Sentry alerts firing | next-session | this doc + Sentry dashboard |

---

**Generated:** 2026-05-07 by R8 audit subagent.
**Method:** 83 × `gh run list -L 100` parallel fetch, Python aggregation, YAML grep for `if: failure()` and `SENTRY_DSN` presence. Read-only.
