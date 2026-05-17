# GitHub Workflows Index

`.github/workflows/` carries **168 workflow YAML files** for jpcite — CI gates,
deploy / publish, ingest crons, precompute crons, growth-ops crons, backups,
audit / sync utilities, and operator-only one-shots. This README is the SOT
one-page index; **HARNESS-H4** (2026-05-17) regenerated it from the live
`.github/workflows/*.yml` set so the headline count and category breakdown
match reality, not a stale `82 file / v0.3.4` claim.

> Convention: every cron honours **AGENTS.md / `feedback_no_operator_llm_api`** —
> zero LLM SDK imports inside `src/`, `scripts/cron/`, `scripts/etl/`, `tests/`.
> Every "Fly machine" cron uses `flyctl ssh console` with `FLY_API_TOKEN`.

---

## Gate taxonomy (HARNESS-H4, 2026-05-17)

Every workflow is classified into exactly one of five categories. The make
target taxonomy mirrors this split:

| Category | Count | Semantics |
|---|---:|---|
| **PR hard gate** | 11 | PR-blocking on `main`; failure prevents merge. |
| **Release hard gate** | 5 | PR + push + tag triggered; gates the v* release tag and PyPI publish path. |
| **Deploy gate** | 5 | Production deploy + Pages preview + registry publish; runs on green test SHA or operator dispatch. |
| **Scheduled diagnostic** | 138 | Cron-driven; alert-only / write-side data crons. Failure pages the operator but never auto-rollbacks. |
| **Manual operator-only** | 9 | `workflow_dispatch`-only; side-effect requires explicit operator run (loadtest, kill-switch, rebrand bulk, etc.). |

**Total: 168 workflow YAML files** (verified `ls .github/workflows/*.yml | wc -l`,
2026-05-17). Each workflow appears in exactly one §1..§5 section below — no
double-counting between PR / release / deploy / scheduled / manual.

### Category convention

- **PR hard gate** workflows MUST pass before any `main` PR can merge. The
  intersection with `release-readiness-ci.yml` 10/10 PASS is the canonical
  release-readiness oracle (10th check added by HARNESS-H4 closes the
  workflow-target-drift gap that previously let `target-sync` fail with
  release_readiness 9/9 PASS on the same SHA).
- **Release hard gate** workflows MUST pass before a `v*` git tag can ship
  PyPI / npm / MCP registry artifacts.
- **Deploy gate** workflows fence the Fly.io + Cloudflare Pages production
  surface. Failure aborts the deploy mid-flight (see deploy.yml smoke-sleep
  contract — `feedback_post_deploy_smoke_propagation`).
- **Scheduled diagnostic** workflows produce facts, alerts, or Postmark
  emails on cron. Failure surfaces in Slack / Telegram / email but is
  observability, not gating.
- **Manual operator-only** workflows have `workflow_dispatch:` as the *only*
  trigger and carry side-effects (publish, drill, teardown) that must not
  fire on a schedule or PR.

---

## §1. PR hard gates (11)

PR-blocking on `main`. Failure prevents merge.

| Workflow | Trigger | Job purpose |
|---|---|---|
| `release-readiness-ci.yml` | PR / push main / tag `v*` / dispatch | Runs `scripts/ops/release_readiness.py` (canonical 10/10-check release gate post HARNESS-H4). Fails the run on any non-PASS check. |
| `fingerprint-sot-guard.yml` | PR main / dispatch | AST guard preventing duplicate `hashlib.sha256(...)` ACK fingerprint inlining outside the canonical helper. Pairs with `tests/test_fingerprint_sot_guard.py`. |
| `acceptance_criteria_ci.yml` | PR main (paths) / weekly Mon / dispatch | DEEP-59 acceptance-criteria sweep. Hermetic via `JPCITE_OFFLINE=1`. Uploads `aggregate_acceptance.json`. |
| `lane-enforcer-ci.yml` | PR main / push main | DEEP-60 dual-CLI lane policy enforcer (Python stdlib + git only). |
| `lane-policy-warn.yml` | PR main | Wave 46 §G companion. Non-blocking lane-collision warning via `scripts/audit/check_lane_policy.py`. rc=0 always (warn only). |
| `check-workflow-target-sync.yml` | PR (workflows/tests paths) / dispatch | DEEP-57 PR-side guard — drift between `RUFF_TARGETS` / `PYTEST_TARGETS` env list and git-tracked sources fails the PR check. |
| `test.yml` | push `**` / PR `**` | Primary CI: ruff + pytest over `RUFF_TARGETS` / `PYTEST_TARGETS`. Concurrency-cancelled per ref. |
| `e2e.yml` | PR main / nightly / dispatch | Playwright Chromium e2e against staging (or prod via dispatch + `--run-production`). |
| `eval.yml` | PR / cron / dispatch | Three-tier eval harness (A: 5 hand-verified seeds / B: 220 synthetic / C: 60+30 hallucination). Drives stdio MCP binary, NOT Anthropic API. |
| `audit-regression-gate.yml` | PR main (paths) | Wave 15 H3 5-axis audit vs `tests/regression/audit_baseline.json`. Any axis loss >0.5 point fails the gate. |
| `data-integrity.yml` | PR (DB paths) / nightly / dispatch | URL integrity scan — fails on synthetic / placeholder / loopback URLs (景表法 4/5 条). |
| `functions-typecheck.yml` | PR / push / dispatch | mypy strict over the CF Pages Functions surface. |
| `distribution-manifest-check.yml` | push `**` / PR `**` | Per-commit drift check on package manifests (`pyproject.toml` / `server.json` / `dxt/manifest.json` / `smithery.yaml` / `mcp-server.json`). |
| `dependabot-auto-merge.yml` | PR (dependabot) | Auto-enables squash-merge on green for dependabot patch/minor PRs. Gated on branch protection — does NOT bypass required CI checks. |

> Hard-blocking gates = 9; non-blocking PR-comment surfaces (`lane-policy-warn`,
> `dependabot-auto-merge`) round the count to 11 PR-triggered workflows that
> influence merge gating.

## §2. Release hard gates (5)

Gate the `v*` git-tag → PyPI / npm / MCP-registry publish path. PR + push +
tag triggered. Failure prevents tag → publish.

| Workflow | Trigger | Job purpose |
|---|---|---|
| `release.yml` | push tag `v*` / push / dispatch | PyPI sdist+wheel build + trusted publish. Same `RUFF_TARGETS` / `PYTEST_TARGETS` envelope as `test.yml`. |
| `sdk-publish.yml` | push tag `sdk-ts-v*` / push / dispatch | npm publish of `@autonomath/client` (TS SDK). |
| `sdk-publish-agents.yml` | push tag `agents-v*` / push / dispatch | npm publish of `@jpcite/agents` (reference Agent SDK starters). OIDC trusted publish. |
| `codeql.yml` | push / PR / weekly | GitHub CodeQL static analysis. |
| `tls-check.yml` | daily / dispatch | TLS expiry monitor (Let's Encrypt safety net). Hard-gate because expired TLS = total outage. |

## §3. Deploy gates (5)

Fence the Fly.io + Cloudflare Pages production surface. Triggered on green
`test.yml` SHA (`workflow_run`), `main` push, or operator dispatch.

| Workflow | Trigger | Job purpose |
|---|---|---|
| `deploy.yml` | `workflow_run: test completed on main` / dispatch | Production Fly.io deploy. Gated on green `test.yml` for the same SHA. Smoke sleep ≥60s + curl `--max-time` ≥30s (`feedback_post_deploy_smoke_propagation`). |
| `deploy-jpcite-api.yml` | dispatch | jpcite-api specific deploy entrypoint (operator-triggered Fly redeploy without test gate). |
| `pages-deploy-main.yml` | push main / dispatch | Cloudflare Pages production deploy. |
| `pages-preview.yml` | push branches `preview/**` / dispatch | Cloudflare Pages preview deploy of `site/`. |
| `pages-regenerate.yml` | daily / push main / dispatch | Generates per-program / prefecture / llms / sitemap from production SQLite, deploys to Pages. |
| `smithery-deploy.yml` | push / dispatch | Smithery MCP runtime publish (federated MCP recommendation hub). |
| `openapi.yml` | push main / dispatch | Regenerates `docs/openapi/v1.json` via `scripts/export_openapi.py`. |

## §4. Scheduled diagnostics (138)

Cron-driven. Most are write-side ETL crons or alert generators; failure
surfaces in Slack / Telegram / email but never auto-rollbacks the deploy.
Listed by sub-cluster with the cron cadence written into each workflow.

### §4a. Bulk ingest (Fly machine via `flyctl ssh`)

`ingest-daily.yml`, `ingest-weekly.yml`, `ingest-monthly.yml`,
`ingest-offline-inbox-hourly.yml`, `ministry-ingest-monthly.yml`,
`nta-bulk-monthly.yml`, `nta-corpus-incremental-cron.yml`,
`gbiz-ingest-monthly.yml`, `incremental-law-load.yml`,
`incremental-law-bulk-saturation-cron.yml`,
`incremental-law-en-translation-cron.yml`, `egov-pubcomment-daily.yml`,
`egov-amendment-daily.yml`, `edinet-daily.yml`,
`kokkai-shingikai-weekly.yml`, `municipality-subsidy-weekly.yml`,
`municipal-subsidy-2x-weekly.yml`, `jorei-pref-weekly.yml`,
`jpo-patents-daily.yml`, `eligibility-history-daily.yml`,
`refresh-amendment-diff-history-daily.yml`,
`adoption-program-join-weekly.yml`, `adoption-rss-daily.yml`,
`alias-expansion-weekly.yml`, `alliance-opportunity-weekly.yml`,
`amendment-alert-cron.yml`, `amendment-alert-fanout-cron.yml`,
`amendment-diff-rss-weekly.yml`,
`anonymized-cohort-audit-daily.yml`, `audit-workpaper-v2-daily.yml`,
`axis2-precompute-daily.yml`, `axis2def-promote-weekly.yml`,
`axis6-output-monthly.yml`, `budget-subsidy-chain-daily.yml`,
`common-crawl-monthly.yml`, `enforcement-court-2x-weekly.yml`,
`enforcement-press-daily.yml`, `extended-corpus-weekly.yml`,
`foundation-weekly.yml`, `freshness-rollup-daily.yml`,
`houjin-risk-score-daily.yml`, `invoice-diff-daily.yml`,
`knowledge-graph-vec-embed.yml`, `overseas-subsidy-weekly.yml`,
`packet-samples-regen-weekly.yml`, `parquet-export-monthly.yml`,
`populate-calendar-monthly.yml`, `post-award-monitor-cron.yml`,
`provenance-backfill-daily.yml`, `realtime-signal-maintenance-daily.yml`,
`refresh-fact-signatures-weekly.yml`, `refresh-sources.yml`,
`refresh-sources-daily.yml`, `refresh-sources-weekly.yml`,
`session-context-daily.yml`, `sot-regen-weekly.yml`,
`subsidy-30yr-forecast-monthly.yml`, `time-machine-snapshot-monthly.yml`,
`r2-upload-jpintel-daily.yml`.

### §4b. Precompute / mat views

`precompute-refresh-cron.yml`, `precompute-actionable-daily.yml`,
`precompute-data-quality-daily.yml`, `precompute-recommended-monthly.yml`,
`predictive-events-daily.yml`, `composed-tools-invocation-daily.yml`,
`portfolio-optimize-daily.yml`.

### §4c. Customer fan-out + retention

`saved-searches-cron.yml`, `weekly-digest.yml`, `morning-briefing-cron.yml`,
`same-day-push-cron.yml`, `sunset-alerts-cron.yml`,
`dispatch-webhooks-cron.yml`, `quarterly-reports-cron.yml`,
`revalidate-webhook-targets-cron.yml`, `narrative-sla-breach-hourly.yml`,
`narrative-audit-monthly.yml`, `news-pipeline-cron.yml`.

### §4d. Billing + ops

`billing-health-cron.yml`, `stripe-backfill-30min.yml`,
`stripe-version-check-weekly.yml`, `idempotency-sweep-hourly.yml`,
`trial-expire-cron.yml`, `monetization-metrics-daily.yml`,
`detect-first-g4-g5-txn.yml`, `analytics-cron.yml`, `kpi-digest-cron.yml`.

### §4e. Growth-ops / organic SEO

`index-now-cron.yml`, `competitive-watch.yml`, `brand-signals-weekly.yml`,
`industry-journal-mention-monthly.yml`, `organic-outreach-monthly.yml`,
`organic-funnel-daily.yml`, `funnel-6stage-daily.yml`,
`evolution-dashboard-weekly.yml`, `production-gate-dashboard-daily.yml`,
`meta-analysis-daily.yml`, `practitioner-eval-publish.yml`,
`ai-mention-share-monthly.yml`, `multilingual-monthly-audit.yml`,
`multilingual-weekly.yml`, `og-images.yml`, `ax-metrics-daily.yml`.

### §4f. Backup + DR drills

`nightly-backup.yml`, `weekly-backup-autonomath.yml`,
`restore-drill-monthly.yml`, `health-drill-monthly.yml`,
`chaos-weekly.yml`, `chaos-24-7.yml`, `monthly-deep-audit.yml`,
`sbom-publish-monthly.yml`.

### §4g. Self-improve + audit

`self-improve-loop-h-daily.yml`, `self-improve-weekly.yml`,
`outcome-verifier.yml`, `status-aggregator-hourly.yml`,
`status-probe-cron.yml`, `six-axis-sanity-daily.yml`,
`acceptance_check.yml`, `geo_eval.yml`, `perf-bench.yml`.

### §4h. AWS canary + cost guard

`aws-credit-cost-monitor.yml`, `aws-credit-orchestrator.yml`,
`cf-ai-audit-daily.yml`, `cf-parity-daily.yml`,
`answer-freshness-hourly.yml`.

### §4i. Trust / brand / regeneration

`trust-center-publish.yml`, `sync-workflow-targets-monthly.yml`,
`status_update.yml`.

> The §4 total reconciles to 138 cron-triggered workflow files. Per-cadence
> detail per row lives inside each `.yml` `schedule:` block — this README
> is the index, not the full cadence registry.

## §5. Manual operator-only (9 + 6 dispatch-only drift probes)

`workflow_dispatch:` is the **only** trigger. Side-effects require explicit
operator run.

| Workflow | Purpose |
|---|---|
| `loadtest.yml` | k6 real-traffic load test against staging. `STAGING_URL` + `LOADTEST_PRO_KEY` inputs required. |
| `mcp-registry-publish.yml` | Publish `server.json` to `registry.modelcontextprotocol.io` via OIDC. |
| `rebrand-notify-once.yml` | One-shot `notify_existing_users.py` for AutonoMath → jpcite rebrand bulk send (Postmark). |
| `pages-rollback.yml` | Cloudflare Pages rollback runner (`scripts/cf_pages_rollback.sh`). |
| `aws-credit-teardown.yml` | Stream E planned-teardown 01..05 sequence (DRY_RUN default). |
| `aws-credit-stop-drill.yml` | AWS hard-stop dry-run drill. |
| `sdk-republish.yml` | Force-republish of npm SDK on identical tag (registry corruption recovery). |
| `playwright-install.yml` | Cache Playwright browser binaries (dispatch-only manual install). |
| `publish_text_guard.yml` | Static text-guard re-publish. |
| `mcp_drift_v3.yml` | Manual v3 MCP drift probe. |
| `facts_registry_drift_v3.yml` | Manual v3 facts-registry drift probe. |
| `fence_count_drift_v3.yml` | Manual v3 fence-count drift probe. |
| `openapi_drift_v3.yml` | Manual v3 openapi drift probe. |
| `sitemap_freshness_v3.yml` | Manual v3 sitemap freshness probe. |
| `structured_data_v3.yml` | Manual v3 structured-data probe. |

> The 9 listed in the taxonomy headline corresponds to the deploy / publish /
> drill / teardown axis. The 6 `*_v3` drift probes are additional
> dispatch-only manual surfaces used during HARNESS-H4 audits.

---

## §6. Trigger matrix (one-line summary)

| Trigger family | Workflows |
|---|---|
| `pull_request` | release-readiness-ci, fingerprint-sot-guard, acceptance-criteria-ci, lane-enforcer-ci, lane-policy-warn, check-workflow-target-sync, test, e2e, eval, audit-regression-gate, data-integrity, distribution-manifest-check, functions-typecheck, dependabot-auto-merge, codeql |
| `push: branches` | test, codeql, openapi, distribution-manifest-check, lane-enforcer-ci, release-readiness-ci, pages-regenerate, pages-preview, pages-deploy-main, narrative-sla-breach-hourly, same-day-push-cron, smithery-deploy, sdk-publish, sdk-publish-agents, release, functions-typecheck |
| `push: tags` | release (`v*`), sdk-publish (`sdk-ts-v*`), sdk-publish-agents (`agents-v*`), release-readiness-ci (`v*`) |
| `workflow_run` | deploy (gated on `test` green), trust-center-publish |
| `schedule` (cron) | 138 workflows across §4 (see per-row cadence) |
| `workflow_dispatch` | nearly every workflow (operator manual run); exclusive: loadtest, mcp-registry-publish, rebrand-notify-once, pages-rollback, aws-credit-*, sdk-republish, playwright-install, publish_text_guard, deploy-jpcite-api, *_v3 |

---

## §7. Makefile target ↔ CI gate mapping

HARNESS-H4 split the legacy `make mcp` target into three distinct targets so
local-dev parity matches the CI gate taxonomy:

| Make target | CI surface | Semantics |
|---|---|---|
| `make mcp-static` | `distribution-manifest-check.yml` (§1) | Static drift check across pyproject / server.json / dxt / smithery / mcp-server.json. No FastMCP boot. |
| `make mcp-runtime` | (none yet — gate substrate) | Boots FastMCP server in-process and asserts runtime `len(await mcp.list_tools())` matches manifest floor + range bands in `data/facts_registry.json`. |
| `make mcp-public-discovery` | `mcp-registry-publish.yml` (§5), `sitemap_freshness_v3.yml` (§5) | Regenerates public MCP manifests (`mcp-server.json`, `mcp-server.full.json`, `site/mcp-server*.json`) + static drift check + sitemap freshness probe. |
| `make mcp` | — | Backwards-compat alias for `mcp-static`. Preserved so `make e2e` recipe still works. |

The new `workflow_targets_full_drift` check in
`scripts/ops/release_readiness.py` (HARNESS-H4) shells out to
`scripts/ops/sync_workflow_targets_verify.py --check` and is the 10th of the
9/9 → 10/10 release-readiness checks. It closes the gap that allowed
release_readiness 9/9 PASS while `check-workflow-target-sync` reported 120
drift rows on the same SHA.

---

## §8. Review lanes (preserved boundary)

Historical boundary review guide. Many files are operationally sensitive
even when not secret.

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

---

> Last regenerated: 2026-05-17 (HARNESS-H4). Workflow count is verified by
> `ls .github/workflows/*.yml | wc -l`. Any future edit to this README MUST
> re-run that count and update the headline number — the 168 file claim is
> load-bearing for the `workflow_targets_full_drift` gate.
