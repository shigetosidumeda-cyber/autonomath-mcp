# GitHub Workflows Index

`.github/workflows/` carries **82 workflow files** for jpcite v0.3.4 — CI gates,
deploy + publish, ingest crons, precompute crons, growth-ops crons, backups, and
audit/sync utilities. This README is the SOT one-page index. Existing review-lane
boundary content is preserved at the bottom.

> Convention: every cron honours **CLAUDE.md / `feedback_no_operator_llm_api`** —
> zero LLM SDK imports inside `src/`, `scripts/cron/`, `scripts/etl/`, `tests/`.
> Every "Fly machine" cron uses `flyctl ssh console` with `FLY_API_TOKEN`.

---

## §1. Launch-readiness CI gates (5)

These five workflows are the hard gates that must stay green for production
deploy. PR-blocking on `main`.

| Workflow | Trigger | Job purpose |
|---|---|---|
| `release-readiness-ci.yml` | PR / push main / tag `v*` / dispatch | Runs `scripts/ops/release_readiness.py` (canonical 9/9-check release gate). Fails the run on any non-PASS. |
| `fingerprint-sot-guard.yml` | PR main / dispatch | AST guard preventing duplicate `hashlib.sha256(...)` ACK fingerprint inlining outside the canonical helper. Pairs with `tests/test_fingerprint_sot_guard.py`. |
| `acceptance_criteria_ci.yml` | PR main (paths) / weekly Mon 03:17 UTC / dispatch | DEEP-59 acceptance-criteria sweep. Hermetic via `JPCITE_OFFLINE=1`. Uploads `aggregate_acceptance.json`. |
| `lane-enforcer-ci.yml` | PR main / push main | DEEP-60 dual-CLI lane policy enforcer (Python stdlib + git only). |
| `check-workflow-target-sync.yml` | PR (workflows/tests paths) / dispatch | DEEP-57 PR-side guard — drift between `RUFF_TARGETS` / `PYTEST_TARGETS` env list and git-tracked sources fails the PR check. |

## §2. Test suites (3)

| Workflow | Trigger | Job purpose |
|---|---|---|
| `test.yml` | push `**` / PR `**` | Primary CI: ruff + pytest over `RUFF_TARGETS` / `PYTEST_TARGETS`. Concurrency-cancelled per ref. |
| `e2e.yml` | PR main / nightly 17:00 UTC / dispatch (`target` input) | Playwright Chromium e2e against staging (or prod via dispatch + `--run-production`). |
| `eval.yml` | PR | Three-tier eval harness (A: 5 hand-verified seeds / B: 220 synthetic / C: 60+30 hallucination). Drives stdio MCP binary, NOT Anthropic API. |
| `loadtest.yml` | dispatch only | k6 real-traffic load test against staging. Manual contract — `STAGING_URL` + `LOADTEST_PRO_KEY` inputs required. |
| `codeql.yml` | push / PR / weekly Mon 03:00 UTC | GitHub CodeQL static analysis. |
| `data-integrity.yml` | PR (DB paths) / nightly 19:30 UTC / dispatch | URL integrity scan — fails on synthetic / placeholder / loopback URLs (景表法 4/5 条). |
| `tls-check.yml` | daily 03:00 UTC / dispatch | TLS expiry monitor (Let's Encrypt safety net). |
| `distribution-manifest-check.yml` | push `**` / PR `**` | Per-commit drift check on package manifests (`pyproject.toml` / `server.json` / `dxt/manifest.json` / `smithery.yaml` / `mcp-server.json`). |

## §3. Deploy + publish (8)

| Workflow | Trigger | Job purpose |
|---|---|---|
| `deploy.yml` | `workflow_run: test completed on main` / dispatch | Production Fly.io deploy. Gated on green `test.yml` for the same SHA. |
| `release.yml` | push tag `v*` / dispatch | PyPI sdist+wheel build + trusted publish. Same `RUFF_TARGETS` / `PYTEST_TARGETS` envelope as `test.yml`. |
| `sdk-publish.yml` | push tag `sdk-ts-v*` / dispatch | npm publish of `@autonomath/client` (TS SDK). |
| `sdk-publish-agents.yml` | push tag `agents-v*` / dispatch | npm publish of `@jpcite/agents` (reference Agent SDK starters). OIDC trusted publish. |
| `mcp-registry-publish.yml` | dispatch | Publish `server.json` to `registry.modelcontextprotocol.io` via OIDC. |
| `pages-preview.yml` | push branches `preview/**` / dispatch | Cloudflare Pages preview deploy of `site/`. |
| `pages-regenerate.yml` | daily 19:17 UTC / dispatch / push main | Generates per-program / prefecture / llms / sitemap from production SQLite, deploys to Pages. |
| `openapi.yml` | push main / dispatch | Regenerates `docs/openapi/v1.json` via `scripts/export_openapi.py`. |

## §4. Ingest + precompute + product crons (40+)

### §4a. Bulk ingest (Fly machine via `flyctl ssh`)

| Workflow | Cadence (UTC / JST) | Surface |
|---|---|---|
| `ingest-daily.yml` | 19:15 UTC / 04:15 JST | Tier-1 authorities (Jグランツ / 中小企業庁 / 大型補助金). |
| `ingest-weekly.yml` | Sun 20:20 UTC / Mon 05:20 JST | Tier-2 (MAFF / METI / JFC / noukaweb rehost). |
| `ingest-monthly.yml` | 1st 21:20 UTC / 1st 06:20 JST | Tier-3 (47 都道府県 + 市区町村 + g-reiki, 4-month slot rotation). |
| `ingest-offline-inbox-hourly.yml` | hourly | Drains operator-side `tools/offline/` JSONL inbox into prod SQLite. |
| `ministry-ingest-monthly.yml` | 5th 21:50 UTC / 5th 06:50 JST | MAFF / MIC / MOJ / MHLW into jpintel.db. |
| `nta-bulk-monthly.yml` | 1st 18:00 UTC / 2nd 03:00 JST | 4M-row 国税庁 適格請求書発行事業者 zenken bulk (PDL v1.0). |
| `nta-corpus-incremental-cron.yml` | daily | NTA 裁決 / 質疑応答 / 文書回答 incremental (~100 rows/day cap). |
| `gbiz-ingest-monthly.yml` | 5th 18:00 UTC / 6th 03:00 JST | gBizINFO v2 bulk JSONL ZIP + 5-family delta matrix. |
| `incremental-law-load.yml` | weekly | e-Gov full-text loader, 600 laws/run (saturates ~17 weeks). |
| `egov-pubcomment-daily.yml` | Mon-Fri 00:00 UTC / 09:00 JST | DEEP-45 e-Gov パブコメ 公示 daily ingest. |
| `kokkai-shingikai-weekly.yml` | Sun 21:00 UTC / Mon 06:00 JST | DEEP-39 国会会議録 + 12 council 議事録. |
| `municipality-subsidy-weekly.yml` | Sun 18:00 UTC / Mon 03:00 JST | DEEP-44 自治体 47都道府県 + 20政令市 補助金 page diff. |
| `eligibility-history-daily.yml` | 19:00 UTC / 04:00 JST | Rebuild `am_program_eligibility_history` for tier S/A. |
| `refresh-amendment-diff-history-daily.yml` | 19:30 UTC / 04:30 JST | Predicate-level diff INSERT into `am_amendment_diff` from history. |
| `adoption-program-join-weekly.yml` | Sun 18:15 UTC / Mon 03:15 JST | Backfill `jpi_adoption_records.program_id` (mig 113). |
| `alias-expansion-weekly.yml` | Sat 18:00 UTC / Sun 03:00 JST | Mine `empty_search_log` → `alias_candidates_queue` (operator-review write path). |

### §4b. Source freshness (3)

| Workflow | Cadence | Surface |
|---|---|---|
| `refresh-sources-daily.yml` | 18:05 UTC daily | Tier S/A HEAD→200→GET→SHA256 verify (~1,454 rows). |
| `refresh-sources-weekly.yml` | Sun 18:00 UTC / Mon 03:00 JST | Tier B/C verify (~10,200 rows). |
| `refresh-sources.yml` | 18:22 UTC daily / Sat 18:17 UTC | Tiered legacy URL liveness (S/A/B/C). |

### §4c. Precompute / materialised views (5)

| Workflow | Cadence | Surface |
|---|---|---|
| `precompute-refresh-cron.yml` | nightly | 32 `pc_*` views + L4 cache + Bayesian confidence snapshot. |
| `precompute-actionable-daily.yml` | 18:30 UTC / 03:30 JST | Wave 30-5 `am_actionable_qa_cache` (mig 169). |
| `precompute-data-quality-daily.yml` | 20:05 UTC / 05:05 JST | Single-row `am_data_quality_snapshot` rollup. |
| `precompute-recommended-monthly.yml` | 1st 18:00 UTC / 2nd 03:00 JST | TOP-10 `am_recommended_programs` per houjin. |
| `populate-calendar-monthly.yml` | 5th 18:00 UTC / 6th 03:00 JST | `am_program_calendar_12mo` rolling 12-month mat view. |

### §4d. Customer fan-out + retention (8)

| Workflow | Cadence | Surface |
|---|---|---|
| `saved-searches-cron.yml` | daily | ¥3-metered saved-search digest (Postmark template). |
| `weekly-digest.yml` | weekly | Saved-search Advisor Loop weekly digest (`digest_delivered`). |
| `morning-briefing-cron.yml` | 21:05 UTC / 06:05 JST | Per-customer 5-line ¥3-billed morning briefing. |
| `same-day-push-cron.yml` | every 30 min | Same-day amendment push to consultants (¥3 metered). |
| `sunset-alerts-cron.yml` | every hour :20 | Sunset/amended/disappeared fan-out (¥3 metered, 0-fan-out skip). |
| `dispatch-webhooks-cron.yml` | every 10 min | Customer webhook dispatcher (¥3 metered, HMAC-signed). |
| `amendment-alert-cron.yml` | daily | FREE retention amendment alert (Postmark) — distinct from ¥3 webhooks. |
| `quarterly-reports-cron.yml` | Q1/Q2/Q3/Q4 1st 00:00 UTC | Quarterly PDF batch render per paid api_key. |

### §4e. Billing + ops (5)

| Workflow | Cadence | Surface |
|---|---|---|
| `billing-health-cron.yml` | daily | 4-stage: reconcile → backfill → predictive alert → cost alert. |
| `stripe-backfill-30min.yml` | every 30 min | Backfills `usage_events.stripe_synced_at IS NULL`. |
| `stripe-version-check-weekly.yml` | Mon 00:00 UTC / 09:00 JST | Stripe API sunset signal probe (3 sources). |
| `idempotency-sweep-hourly.yml` | hourly :15 | TTL-evict `am_idempotency_cache` rows (mig 087). |
| `trial-expire-cron.yml` | daily | Revoke expired tier='trial' API keys. |

### §4f. Misc product crons (3)

| Workflow | Cadence | Surface |
|---|---|---|
| `analytics-cron.yml` | 18:00 UTC / 03:00 JST | Cloudflare/PyPI/npm download collectors → JSONL commit. |
| `news-pipeline-cron.yml` | daily | 5-stage: amendment_diff → news posts → RSS → audit-log RSS → program RSS. |
| `kpi-digest-cron.yml` | 06:00 JST daily | Operator KPI digest email + webhook health probe. |

## §5. Growth-ops + organic SEO crons (8)

| Workflow | Cadence | Surface |
|---|---|---|
| `index-now-cron.yml` | 18:30 UTC / 03:30 JST | IndexNow ping (Bing / Yandex / Naver / Yep) on sitemap delta. |
| `competitive-watch.yml` | daily 09:00 UTC | Competitor URL diff → PR + Slack HIGH alert. |
| `brand-signals-weekly.yml` | Mon 21:00 UTC / Tue 06:00 JST | DEEP-41 brand mention dashboard (10 organic sources). |
| `industry-journal-mention-monthly.yml` | 15th 21:00 UTC / 16th 06:00 JST | DEEP-40 業界誌 8紙 mention ingest. |
| `organic-outreach-monthly.yml` | last day 21:00 UTC / 1st 06:00 JST | DEEP-65 organic outreach playbook tracker (32 templates). |
| `evolution-dashboard-weekly.yml` | Tue 03:00 UTC / Tue 12:00 JST | DEEP-42 12-axis evolution dashboard aggregator. |
| `production-gate-dashboard-daily.yml` | 21:00 UTC / 06:00 JST next day | DEEP-58 4-blocker / 8-ACK / 33-spec rollup → static page. |
| `meta-analysis-daily.yml` | daily | Wave 22+23 mat view rollup → markdown health report + Slack. |

## §6. Backup + DR drills (4)

| Workflow | Cadence | Surface |
|---|---|---|
| `nightly-backup.yml` | nightly | Online SQLite backup of jpintel.db → R2 (14-day rolling). Fail-closed on missing R2 secrets. |
| `weekly-backup-autonomath.yml` | weekly | 8.29 GB autonomath.db → R2 (28-day rolling). |
| `restore-drill-monthly.yml` | 14th 18:00 UTC / 15th 03:00 JST | DEEP-62 monthly R2 restore drill (autonomath/jpintel rotation). |
| `health-drill-monthly.yml` | monthly 1st | DR scenario 1-3 dry-run (VM crash / volume / R2). |

## §7. Self-improve + audit (5)

| Workflow | Cadence | Surface |
|---|---|---|
| `self-improve-loop-h-daily.yml` | 18:30 UTC / 03:30 JST | Loop H — Zipf-ranked L4 cache warmer. |
| `self-improve-weekly.yml` | Mon 00:30 UTC / Mon 09:30 JST | 10-pipeline orchestrator (`--no-write` proposal-only pre-launch). |
| `narrative-audit-monthly.yml` | 1st 00:00 UTC / 1st 09:00 JST | §10.10 Hallucination Guard stratified narrative audit (Telegram bot). |
| `narrative-sla-breach-hourly.yml` | every hour | §10.10 SLA breach pusher (Telegram bot). |
| `sunset-alerts-cron.yml` | (see §4d) | (overlap surface) |

## §8. Audit + sync utilities (3)

| Workflow | Trigger | Surface |
|---|---|---|
| `sync-workflow-targets-monthly.yml` | 1st 18:00 UTC / 1st 03:00 JST + dispatch | DEEP-57 cross-repo: rewrites `RUFF_TARGETS` / `PYTEST_TARGETS` and opens PR via `peter-evans/create-pull-request` (`CROSS_REPO_PAT`). |
| `check-workflow-target-sync.yml` | (see §1) | PR-side `--check` mode counterpart. |
| `trust-center-publish.yml` | Sat 19:00 UTC / Sun 04:00 JST + dispatch + workflow_run | Static trust-center / transparency page publish. |
| `rebrand-notify-once.yml` | dispatch only | One-shot `notify_existing_users.py` for AutonoMath → jpcite rebrand bulk send (Postmark). |

---

## §9. Trigger matrix (one-line summary)

| Trigger family | Workflows |
|---|---|
| `pull_request` (PR-blocking) | release-readiness-ci, fingerprint-sot-guard, acceptance-criteria-ci, lane-enforcer-ci, check-workflow-target-sync, test, e2e, eval, codeql, data-integrity, distribution-manifest-check |
| `push: branches` | test, codeql, openapi, distribution-manifest-check, lane-enforcer-ci, release-readiness-ci, pages-regenerate, pages-preview |
| `push: tags` | release (`v*`), sdk-publish (`sdk-ts-v*`), sdk-publish-agents (`agents-v*`), release-readiness-ci (`v*`) |
| `workflow_run` | deploy (gated on `test` green), trust-center-publish |
| `schedule` (cron) | 60+ workflows across §4–§7 (see per-row cadence) |
| `workflow_dispatch` | nearly every workflow (operator manual run); exclusive: loadtest, mcp-registry-publish, rebrand-notify-once |

---

## §10. Review lanes (preserved boundary)

This section is the historical boundary review guide. Many files are
operationally sensitive even when not secret.

| Lane | Examples | Review focus |
|---|---|---|
| `ci-security` | `test.yml`, `codeql.yml`, `e2e.yml`, `loadtest.yml` | deterministic gates and permissions |
| `deploy-publish` | `deploy.yml`, `release.yml`, `pages-*.yml`, `sdk-publish*.yml`, `mcp-registry-publish.yml` | tested SHA, package version, registry drift |
| `prod-db-write` | ingest, precompute, saved-search, webhook, billing, narrative workflows | target DB/table, dry-run, backup, concurrency |
| `prod-read-backup` | backup, health drill, integrity checks | RPO/RTO, fail-open/fail-closed, restore drill |
| `repo-write` | OpenAPI, analytics, generated docs/logs | `contents: write`, generated output ownership |
| `growth-ops` | SEO, IndexNow, competitive watch, outreach-like jobs | public claims, rate limits, source attribution |

### Rules

- Treat any workflow using `flyctl ssh console`, `/data/*.db`, Stripe,
  webhooks, or `contents: write` as a release-risk workflow.
- Prefer explicit `permissions:` blocks and keep write permissions scoped to
  workflows that push, open PRs, or publish packages.
- Production write workflows should document target DB, target tables, dry-run
  behavior, required secrets, concurrency, and failure notification.
- `workflow_dispatch` should not become a bypass for untested deploys.
- Backup workflows should state RPO/RTO, object prefix, retention/rotation
  glob, and fail-open vs fail-closed behavior.

### Known review prompts

- Verify `weekly-backup-autonomath.yml` object prefixes and rotation globs when
  changing backup names.
- Keep OpenAPI and manifest generation workflows paired with drift checks.
- Keep deploy workflows tied to a known green test SHA.
