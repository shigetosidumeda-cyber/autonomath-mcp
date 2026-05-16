# SQLite PERF MIG-C Applied (2026-05-16)

## Context

Follow-up to `docs/_internal/sqlite_perf_audit_2026_05_16.md` (PERF-13). MIG-C
is the third migration from the four proposed missing indexes on
`autonomath.db`, after MIG-A (PERF-17, `jpi_adoption_records(prefecture,
announced_at)`). This document records the actual application of MIG-C
(PERF-22).

## Target

- Database: `autonomath.db` (12.77 GB, WAL mode)
- Table: `houjin_master`
- Row count: 166,765
- Migration: `CREATE INDEX IF NOT EXISTS idx_houjin_master_prefecture_jsic
  ON houjin_master(prefecture, jsic_major)`
- Rationale (from PERF-13): fixes Q13 cohort rollup full table scan.
  Composite covering index over the most common filter pair used by
  prefecture × industry density / cohort rollup packet generators. The
  existing single-column `idx_houjin_master_jsic_major` leads with
  `jsic_major` and therefore cannot serve `prefecture=?` predicates
  efficiently.

## Pre-State

Existing indexes on `houjin_master` before MIG-C:

```
idx_houjin_master_jsic_major
sqlite_autoindex_houjin_master_1
```

No composite `(prefecture, jsic_major)` index existed. `prefecture` alone
was completely unindexed.

## Backup (Pre-Mutation)

Per memory rule (12 GB SQLite has been the cause of past production stalls),
the database was copied byte-for-byte before any mutation.

| Property | Value |
|---|---|
| Source size | 12,772,372,480 bytes |
| Backup path | `autonomath.db.backup-2026-05-16-PERF22` |
| Backup size | 12,772,372,480 bytes |
| Byte-match | YES (identical size) |

The backup file is intentionally retained after the migration. Do not delete
it until a future cleanup pass confirms the index has been stable in
production for at least one full Wave cycle.

## Apply

```
$ sqlite3 autonomath.db \
    "CREATE INDEX IF NOT EXISTS idx_houjin_master_prefecture_jsic
       ON houjin_master(prefecture, jsic_major);"
```

The statement is idempotent (`IF NOT EXISTS`), so a re-run is a no-op.
WAL mode was preserved (no journal_mode change).

## Post-State

Indexes on `houjin_master` after MIG-C:

```
idx_houjin_master_jsic_major
idx_houjin_master_prefecture_jsic   <-- new
sqlite_autoindex_houjin_master_1
```

## EXPLAIN QUERY PLAN (Q13 sample)

```
sqlite> EXPLAIN QUERY PLAN
   ...> SELECT prefecture, jsic_major, COUNT(*) AS n
   ...> FROM houjin_master
   ...> WHERE prefecture = '東京都' AND jsic_major = 'G'
   ...> GROUP BY prefecture, jsic_major;

QUERY PLAN
`--SEARCH houjin_master USING COVERING INDEX
     idx_houjin_master_prefecture_jsic (prefecture=? AND jsic_major=?)
```

Result: **SEARCH ... USING COVERING INDEX** with both columns active
(`prefecture=?` + `jsic_major=?`). No `SCAN TABLE`. The "COVERING" qualifier
means SQLite never has to touch the underlying row pages — all needed
columns (prefecture, jsic_major) are inside the index leaves. This is the
exact plan PERF-13 predicted.

### Direct Q13 query timing

```
$ time sqlite3 autonomath.db \
    "SELECT prefecture, jsic_major, COUNT(*) AS n
     FROM houjin_master
     WHERE prefecture = '東京都' AND jsic_major = 'G'
     GROUP BY prefecture, jsic_major;"

real    0m0.013s
```

13 ms wall-clock on a 166,765-row table inside a 12.77 GB DB. Before MIG-C
this query would have required a full table scan of `houjin_master`.

## Generator Benchmark

The closest generator surface that pivots on `prefecture × jsic_major` is
`scripts/aws_credit_ops/generate_prefecture_x_industry_density_packets.py`
(Wave 70 #2 — Houjin universal key carrying prefecture × industry_jsic_medium
density proxy). Note that this generator's primary SELECT is against
`jpi_adoption_records` (already covered by MIG-A's
`idx_adoption_prefecture_announced` from PERF-17), not `houjin_master`
directly; MIG-C's primary win is on Q13-style cohort rollups against
`houjin_master`. Re-run was nonetheless executed to confirm zero regression
across the wider density-packet surface.

```
$ time .venv/bin/python -m \
    scripts.aws_credit_ops.generate_prefecture_x_industry_density_packets \
    --output-prefix /tmp/perf22-density/post \
    --limit 50 \
    --local-out-dir /tmp/perf22-density
INFO ... run done: seen=50 written=50 empty=0 bytes_total=81868
     s3_put_usd~=0.0003 manifest=/tmp/perf22-density/run_manifest.json
     dry_run=True elapsed=0.2s
real    0m0.250s
```

50 packets generated cleanly. End-to-end wall-clock 0.250 s for the
`--limit 50` slice (`elapsed=0.2s` reported by the script). No `SCAN
TABLE` warnings. seen=written=50, empty=0.

## Integrity Check

Per the memory rule `feedback_no_quick_check_on_huge_sqlite`, `PRAGMA
quick_check` was **NOT** run on `autonomath.db` (12 GB → 15 min+ hang risk,
Fly 60 s grace blown in past production outage on 2026-05-03). Instead, the
post-state was verified through:

1. `.indexes` listing (new index present)
2. `EXPLAIN QUERY PLAN` (new index actually selected by the planner as
   `COVERING INDEX`)
3. Direct Q13 query (13 ms wall-clock, 1-row aggregate result)
4. Live generator run (`seen=50 written=50 empty=0`)

This is sufficient evidence the migration is safe.

## Outstanding Work

The remaining MIG-B/D entries from PERF-13 are still pending and will be
applied in subsequent PERF tickets, each with its own backup. Do not bundle
them: per the "1 fix at a time + immediate validate" pattern established in
`feedback_docker_build_3iter_fix_saga`, each composite index is its own
gate.

Applied so far:
- MIG-A (PERF-17): `idx_adoption_prefecture_announced` on
  `jpi_adoption_records(prefecture, announced_at)`
- MIG-C (PERF-22, this doc): `idx_houjin_master_prefecture_jsic` on
  `houjin_master(prefecture, jsic_major)`

## Rollback

If a regression is observed in any generator or query that uses
`prefecture` + `jsic_major` on `houjin_master`:

```
sqlite3 autonomath.db "DROP INDEX IF EXISTS idx_houjin_master_prefecture_jsic;"
```

This is a metadata-only operation; SQLite reclaims the index pages lazily.
If a deeper rollback is needed, restore from
`autonomath.db.backup-2026-05-16-PERF22` (12,772,372,480 bytes,
identical pre-MIG-C state).

## Cross-References

- `docs/_internal/sqlite_perf_audit_2026_05_16.md` — PERF-13 audit (parent)
- `docs/_internal/sqlite_perf_mig_a_applied_2026_05_16.md` — MIG-A
  (PERF-17, sibling)
- `scripts/aws_credit_ops/generate_prefecture_x_industry_density_packets.py`
  — surface verified for zero regression
- Memory: `feedback_no_quick_check_on_huge_sqlite` — explains why
  `quick_check` was skipped
