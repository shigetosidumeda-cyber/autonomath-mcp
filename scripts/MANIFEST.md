# Scripts Manifest

This file defines where new scripts should go. It is a navigation contract, not
a complete inventory of every legacy script.

## Placement Rules

| Location | Use for | Do not use for |
|---|---|---|
| `scripts/cron/` | scheduled jobs run by GitHub Actions, Fly, or operator cron | one-off migrations, exploratory crawlers |
| `scripts/ops/` | release checks, preflight, deployment safety, inventories, manual operator commands | source-specific ingest implementations |
| `scripts/ingest/` | source-specific crawlers/parsers/loaders for public data | recurring scheduler wrappers |
| `scripts/etl/` | batch transforms and backfills that may be rerun by an operator | production boot-time DB schema changes |
| `scripts/migrations/` | SQL migration history only | generated reports, one-off data repair notes |
| `scripts/lib/` | shared helpers for scripts | CLI entrypoints |
| `scripts/_archive/` | executed one-shots retained for reference | active jobs |
| `scripts/registry_submissions/` | registry submission collateral | runtime manifests |
| `scripts/seeds/` | small seed builders or seed metadata | large data dumps |
| `scripts/sync/` | external sync helpers | cron wrappers |

## New Script Checklist

Every new script should make these clear in its module docstring or adjacent
runbook.

- owner area: API, billing, ingest, site, deploy, SDK, operator
- mode: cron, manual, one-shot, generator, preflight, backfill
- safe to rerun: yes/no/conditional
- expected inputs and outputs
- database target, if any
- network access requirements
- corresponding test or explicit no-test reason

## Commit Lanes

Avoid mixing unrelated script changes. Prefer these lanes.

1. Cron/scheduler changes plus matching workflow/test.
2. Ingest source parser changes plus fixture/sample tests.
3. Ops/preflight changes plus command-level tests.
4. Site/OpenAPI/llms generator changes plus regenerated output.
5. Migration changes plus schema guard/pre-deploy verification.
6. One-shot archive changes with execution notes.

## Repo Organization Reports

These scripts are safe, read-only inventory tools. They write markdown reports
under `docs/_internal/` and do not stage, move, delete, or rewrite source files.

- `scripts/ops/repo_hygiene_inventory.py` — top-level size/status inventory
- `scripts/ops/repo_dirty_lane_report.py` — dirty-tree review lanes
- `scripts/ops/repo_value_asset_report.py` — productizable value assets
- `scripts/ops/mcp_manifest_deep_diff.py` — DXT vs registry MCP tool drift
- `scripts/ops/migration_inventory.py` — migration family, rollback, and danger markers

## Current Known Ambiguities

These are not deletion instructions. They are review prompts for future cleanup.

- Backup/restore scripts exist in several places. Keep DB target and runtime
  environment explicit.
- Some root-level `scripts/*.py` are historical one-shots and may eventually
  move to `scripts/_archive/` after reference checks.
- Site generators are spread across root `scripts/` and should eventually have
  a clearer `scripts/site/` or documented generator list.
- Cron workflows should map to tests or a documented no-test reason.
