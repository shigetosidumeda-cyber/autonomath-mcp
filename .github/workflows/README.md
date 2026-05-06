# GitHub Workflows Boundary

This directory contains CI, deploy, cron, registry, publishing, backup, and
production maintenance workflows. Many files are operationally sensitive even
when they are not secret.

## Review Lanes

| Lane | Examples | Review focus |
|---|---|---|
| `ci-security` | `test.yml`, `codeql.yml`, `e2e.yml`, `loadtest.yml` | deterministic gates and permissions |
| `deploy-publish` | `deploy.yml`, `release.yml`, `pages-*.yml`, `sdk-publish*.yml`, `mcp-registry-publish.yml` | tested SHA, package version, registry drift |
| `prod-db-write` | ingest, precompute, saved search, webhook, billing, narrative workflows | target DB/table, dry-run, backup, concurrency |
| `prod-read-backup` | backup, health drill, integrity checks | RPO/RTO, fail-open/fail-closed, restore drill |
| `repo-write` | OpenAPI, analytics, generated docs/logs | `contents: write`, generated output ownership |
| `growth-ops` | SEO, IndexNow, competitive watch, outreach-like jobs | public claims, rate limits, source attribution |

## Rules

- Treat any workflow using `flyctl ssh console`, `/data/*.db`, Stripe,
  webhooks, or `contents: write` as a release-risk workflow.
- Prefer explicit `permissions:` blocks and keep write permissions scoped to
  workflows that push, open PRs, or publish packages.
- Production write workflows should document target DB, target tables, dry-run
  behavior, required secrets, concurrency, and failure notification.
- `workflow_dispatch` should not become a bypass for untested deploys.
- Backup workflows should state RPO/RTO, object prefix, retention/rotation
  glob, and fail-open vs fail-closed behavior.

## Known Review Prompts

- Verify `weekly-backup-autonomath.yml` object prefixes and rotation globs when
  changing backup names.
- Keep OpenAPI and manifest generation workflows paired with drift checks.
- Keep deploy workflows tied to a known green test SHA.
