# Migration Boundary

`scripts/migrations/` is SQL migration history. Do not reorganize it by moving
or renaming existing files unless there is a deliberate migration-runner plan.

## Rules

- Applied migrations are immutable. Add a new migration instead of editing an
  old one.
- `*_rollback.sql` files are paired by exact filename stem.
- `wave24_*` files are a legacy release lane. Do not mix their ordinal meaning
  with the numeric `NNN_*` lane without an explicit release-order table.
- The migration runner applies files by lexical filename order and skips
  rollback files. Review runner behavior before assuming numeric order.
- `-- target_db:` is the DB-boundary marker. Unmarked files need review before
  production use.
- `-- boot_time: manual` marks a manual-only migration.
- `autonomath_boot_manifest.txt` is the default boot-time allowlist for
  `entrypoint.sh`. Keep it empty unless a deploy packet explicitly approves an
  autonomath migration for boot-time self-heal. Do not rely on all-file
  discovery in production.

## Read-Only Inventory

Generate the latest migration report with:

```bash
uv run python scripts/ops/migration_inventory.py
```

The report highlights:

- family counts (`numeric`, `wave24`, `other`)
- duplicate forward numeric prefixes
- rollback pairs and orphan rollbacks
- target DB counts
- manual and draft files
- dangerous SQL markers such as `DROP`, `DELETE`, and `TRUNCATE`

This report is a review aid. It does not apply, edit, stage, delete, or move
migration files.
