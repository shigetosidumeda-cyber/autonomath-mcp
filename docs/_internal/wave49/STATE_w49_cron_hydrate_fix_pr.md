# STATE — Wave 49 tick#2 / cron hydrate fix PR

Date: 2026-05-12 (Tokyo)
Branch: `feat/jpcite_2026_05_12_wave49_cron_hydrate_fix`
Worktree: `/tmp/jpcite-w49-cron-hydrate-fix`
Lane: `/tmp/jpcite-w49-cron-hydrate-fix.lane` (atomic mkdir)

## Problem (Wave 49 tick#12 finding)

The 5 AX Layer 5 cron workflows added in Wave 49 G3 fail their
`Dry-run sanity probe` step on every scheduled run with:

```
ERROR: DB not found: /home/runner/work/.../autonomath.db
```

and exit 2, tearing the whole workflow down even though the dry-run
path is read-only. The 12 GB ``autonomath.db`` is **not** hydrated on
the GHA runner — `feedback_no_quick_check_on_huge_sqlite` forbids the
boot-time hydrate, so the cron probe trips on the very first line of
``main()``.

Affected workflows (all 5 invoke `--dry-run` first):

| Workflow file                              | ETL script                              | Dim |
| ------------------------------------------ | --------------------------------------- | --- |
| `predictive-events-daily.yml`              | `build_predictive_watch_v2.py`          | T   |
| `session-context-daily.yml`                | `clean_session_context_expired.py`      | L   |
| `composed-tools-invocation-daily.yml`      | `seed_composed_tools.py`                | P   |
| `time-machine-snapshot-monthly.yml`        | `build_monthly_snapshot.py`             | Q   |
| `anonymized-cohort-audit-daily.yml`        | `aggregate_anonymized_outcomes.py`      | N   |

## Fix (script-side, additive, ~5 LOC each)

Wrap the DB existence check so that a `--dry-run` invocation against a
missing DB returns **0** with a placeholder JSON payload, while keeping
the original `exit 2` strict gate for real runs.

Pattern (applied to all 5):

```python
if not args.db.exists():
    if args.dry_run:
        LOG.warning("db not found (dry-run): %s", args.db)
        print(json.dumps({..., "dry_run": True, "db_not_found_dry_run": True, ...}))
        return 0
    LOG.error("db not found: %s", args.db)
    return 2
```

Net diff: **+113 LOC across 5 files** (each script gets a ~20 LOC
early-return block + a 2-line marker in the JSON payload).

## Verify locally (DB-less)

```bash
$ python3.12 scripts/etl/build_predictive_watch_v2.py --dry-run --db /tmp/nonexistent.db
WARNING: DB not found (dry-run): /tmp/nonexistent.db
{"dim": "T", "wave": 47, "dry_run": true, "db_not_found_dry_run": true, ...}
EXIT=0

$ python3.12 scripts/etl/build_predictive_watch_v2.py --db /tmp/nonexistent.db
ERROR: DB not found: /tmp/nonexistent.db
EXIT=2
```

All 5 scripts pass both directions (dry-run = 0 / strict = 2).

## Test

New `tests/test_cron_hydrate_dry_run.py` (~150 LOC) parametrises across
the 5 scripts with 3 assertions:

1. `--dry-run` against missing DB exits 0 + emits JSON with both
   ``dry_run=true`` and ``db_not_found_dry_run=true`` markers.
2. The dry-run path does **not** create the DB file as a side effect.
3. Non-dry-run against missing DB still exits 2 (strict gate preserved).

## Non-goals (memory enforcement)

- No `rm`/`mv` (feedback_destruction_free_organization).
- Strict gate preserved for production (no DB ⇒ exit 2 outside dry-run).
- No ETL business-logic rewrite, no PRAGMA, no quick_check
  (feedback_no_quick_check_on_huge_sqlite).
- Lane atomically claimed via `mkdir /tmp/jpcite-w49-cron-hydrate-fix.lane`
  (feedback_dual_cli_lane_atomic).
- LLM API import: 0 (feedback_no_operator_llm_api).
- Brand: `jpcite` only — no `autonomath`/`zeimu-kaikei` in user-visible
  text (feedback_legacy_brand_marker).

## Files touched

```
scripts/etl/build_predictive_watch_v2.py     | +22
scripts/etl/clean_session_context_expired.py | +25
scripts/etl/seed_composed_tools.py           | +22
scripts/etl/build_monthly_snapshot.py        | +21
scripts/etl/aggregate_anonymized_outcomes.py | +23
tests/test_cron_hydrate_dry_run.py           | +150 (new)
docs/_internal/wave49/STATE_w49_cron_hydrate_fix_pr.md | new
```
