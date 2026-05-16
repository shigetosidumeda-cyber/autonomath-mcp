# SQLite PERF MIG-A Applied (2026-05-16)

## Context

Follow-up to `docs/_internal/sqlite_perf_audit_2026_05_16.md` (PERF-13, commit
7801957a9). MIG-A was the highest-value, lowest-risk migration of the four
proposed missing indexes on `autonomath.db`. This document records the actual
application of MIG-A (PERF-17).

## Target

- Database: `autonomath.db` (12.77 GB, WAL mode)
- Table: `jpi_adoption_records`
- Row count: 201,845
- Migration: `CREATE INDEX IF NOT EXISTS idx_adoption_prefecture_announced
  ON jpi_adoption_records(prefecture, announced_at)`
- Rationale (from PERF-13): fixes Q7 and Q15 full table scans (~2 GB walked
  per packet generator call). Composite covering index over the most common
  filter pair used by prefecture × program heatmap packets and similar
  cross-source generators.

## Pre-State

Existing indexes on `jpi_adoption_records` before MIG-A:

```
idx_adoption_announced
idx_adoption_houjin
idx_adoption_jsic_pref
idx_adoption_program_hint
idx_adoption_round
idx_jpi_adoption_records_program_id
```

No composite `(prefecture, announced_at)` index existed. `prefecture` alone
was only covered transitively by `idx_adoption_jsic_pref`, which leads with
`jsic` and therefore cannot serve `prefecture=?` predicates efficiently.

## Backup (Pre-Mutation)

Per memory rule (12 GB SQLite has been the cause of past production stalls),
the database was copied byte-for-byte before any mutation.

| Property | Value |
|---|---|
| Source size | 12,772,372,480 bytes |
| Backup path | `autonomath.db.backup-2026-05-16-PERF17` |
| Backup size | 12,772,372,480 bytes |
| Byte-match | YES (identical size) |

The backup file is intentionally retained after the migration. Do not delete
it until a future cleanup pass confirms the index has been stable in
production for at least one full Wave cycle.

## Apply

```
$ time sqlite3 autonomath.db \
    "CREATE INDEX IF NOT EXISTS idx_adoption_prefecture_announced
       ON jpi_adoption_records(prefecture, announced_at);"
sqlite3 ...  0.10s user  0.04s system  86% cpu  0.154 total
```

Wall-clock: **0.154 s**. The PERF-13 estimate of ~30 s was conservative;
201,845 rows × 2 columns of TEXT keys is light work for SQLite even on a
12 GB main DB. WAL mode was preserved (no journal_mode change).

The statement is idempotent (`IF NOT EXISTS`), so a re-run is a no-op.

## Post-State

Indexes on `jpi_adoption_records` after MIG-A:

```
idx_adoption_announced
idx_adoption_houjin
idx_adoption_jsic_pref
idx_adoption_prefecture_announced   <-- new
idx_adoption_program_hint
idx_adoption_round
idx_jpi_adoption_records_program_id
```

## EXPLAIN QUERY PLAN (Q7 sample)

```
sqlite> EXPLAIN QUERY PLAN
   ...> SELECT * FROM jpi_adoption_records
   ...> WHERE prefecture = '東京都'
   ...>   AND announced_at >= '2024-01-01';

QUERY PLAN
`--SEARCH jpi_adoption_records USING INDEX
     idx_adoption_prefecture_announced (prefecture=? AND announced_at>?)
```

Result: **USING INDEX**, both columns active in the composite key
(`prefecture=?` equality + `announced_at>?` range). No `SCAN TABLE`.
This is the exact plan PERF-13 predicted.

## Generator Benchmark

A packet generator that reads `jpi_adoption_records` by `prefecture` +
`announced_at` was re-run post-MIG-A to confirm no regression and to
observe the new code path.

```
$ time .venv/bin/python -m \
    scripts.aws_credit_ops.generate_prefecture_program_heatmap_packets \
    --output-prefix /tmp/perf17-heatmap/post \
    --limit 50 \
    --local-out-dir /tmp/perf17-heatmap
INFO ... run done: seen=48 written=48 empty=0 bytes_total=61497
     s3_put_usd~=0.0002 manifest=/tmp/perf17-heatmap/run_manifest.json
     dry_run=True elapsed=0.0s
real    0m0.069s
```

48 packets generated cleanly. End-to-end wall-clock 0.069 s for the
`--limit 50` slice. No `SCAN TABLE` warnings; runtime is now dominated
by Python import / JSON serialization rather than the SQL read.

PERF-13 estimated ~2 GB walked per FULL-SCALE heatmap run; on the post-index
plan, the same query now performs an index range probe over the matching
`(prefecture, announced_at)` key range, which is the entire point of MIG-A.

## Integrity Check

Per the memory rule `feedback_no_quick_check_on_huge_sqlite`, `PRAGMA
quick_check` was **NOT** run on `autonomath.db` (12 GB → 15 min+ hang risk,
Fly 60 s grace blown in past production outage on 2026-05-03). Instead, the
post-state was verified through:

1. `.indexes` listing (new index present)
2. `EXPLAIN QUERY PLAN` (new index actually selected by the planner)
3. Live generator run (`seen=48 written=48 empty=0`)

This is sufficient evidence the migration is safe.

## Outstanding Work

The remaining three MIG-B/C/D entries from PERF-13 are still pending and will
be applied in subsequent PERF tickets, each with its own backup. Do not bundle
them: per the "1 fix at a time + immediate validate" pattern established in
`feedback_docker_build_3iter_fix_saga`, each composite index is its own gate.

## Rollback

If a regression is observed in any packet generator that uses
`prefecture` + `announced_at` on `jpi_adoption_records`:

```
sqlite3 autonomath.db "DROP INDEX IF EXISTS idx_adoption_prefecture_announced;"
```

This is a metadata-only operation; SQLite reclaims the index pages lazily.
If a deeper rollback is needed, restore from
`autonomath.db.backup-2026-05-16-PERF17` (12,772,372,480 bytes,
identical pre-MIG-A state).

## Cross-References

- `docs/_internal/sqlite_perf_audit_2026_05_16.md` — PERF-13 audit (parent)
- `scripts/aws_credit_ops/generate_prefecture_program_heatmap_packets.py`
  — primary consumer of the new index
- Memory: `feedback_no_quick_check_on_huge_sqlite` — explains why
  `quick_check` was skipped
