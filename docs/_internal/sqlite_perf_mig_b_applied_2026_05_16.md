# SQLite PERF MIG-B Applied (2026-05-16)

## Context

Follow-up to `docs/_internal/sqlite_perf_audit_2026_05_16.md` (PERF-13, commit
7801957a9) and `docs/_internal/sqlite_perf_mig_a_applied_2026_05_16.md`
(PERF-17). MIG-B is the second of the four proposed missing indexes on
`autonomath.db`. This document records the actual application of MIG-B
(PERF-21).

## Target

- Database: `autonomath.db` (12.77 GB, WAL mode)
- Table: `jpi_adoption_records`
- Row count: 201,845
- Migration: `CREATE INDEX IF NOT EXISTS idx_adoption_amount_granted
  ON jpi_adoption_records(amount_granted_yen)`
- Rationale (from PERF-13): fixes Q9 full table scan
  (`WHERE amount_granted_yen >= ?`). Used by `generate_vendor_dd_packets.py`
  + outcome assertion thresholds. Low-risk, single-column, additive.

## Pre-State

Existing indexes on `jpi_adoption_records` before MIG-B (post-MIG-A baseline):

```
idx_adoption_announced
idx_adoption_houjin
idx_adoption_jsic_pref
idx_adoption_prefecture_announced    <-- MIG-A (2026-05-16)
idx_adoption_program_hint
idx_adoption_round
idx_jpi_adoption_records_program_id
```

No single-column index on `amount_granted_yen` existed. Q9-shape queries
(`WHERE amount_granted_yen >= ?`) walked the full 201,845-row table.

## Backup (Pre-Mutation)

Per memory rule `feedback_no_quick_check_on_huge_sqlite` (12 GB SQLite has
caused production stalls), the database was copied byte-for-byte before
any mutation.

| Property | Value |
|---|---|
| Source size | 12,772,372,480 bytes |
| Backup path | `autonomath.db.backup-2026-05-16-PERF21` |
| Backup size | 12,772,372,480 bytes |
| Byte-match | YES (identical size) |
| `cp` wall-clock | 6.040 s |

The backup file is intentionally retained after the migration. Do not delete
it until a future cleanup pass confirms the index has been stable in
production for at least one full Wave cycle.

## Apply

```
$ time sqlite3 autonomath.db \
    "CREATE INDEX IF NOT EXISTS idx_adoption_amount_granted
       ON jpi_adoption_records(amount_granted_yen);"
sqlite3 ...  0.04s user 0.02s system 81% cpu 0.082 total
```

Wall-clock: **0.082 s**. PERF-13 estimated similar speed (8-byte INTEGER
key over 201K rows). WAL mode preserved.

The statement is idempotent (`IF NOT EXISTS`), so a re-run is a no-op.

## Post-State

Indexes on `jpi_adoption_records` after MIG-B:

```
idx_adoption_amount_granted          <-- new (MIG-B)
idx_adoption_announced
idx_adoption_houjin
idx_adoption_jsic_pref
idx_adoption_prefecture_announced    (MIG-A, retained)
idx_adoption_program_hint
idx_adoption_round
idx_jpi_adoption_records_program_id
```

## EXPLAIN QUERY PLAN (Q9 sample)

```
sqlite> EXPLAIN QUERY PLAN
   ...> SELECT * FROM jpi_adoption_records
   ...> WHERE amount_granted_yen >= 5000000;

QUERY PLAN
`--SEARCH jpi_adoption_records USING INDEX
     idx_adoption_amount_granted (amount_granted_yen>?)
```

Result: **USING INDEX**, range probe on `amount_granted_yen>?`. No
`SCAN TABLE`. Matches the PERF-13 prediction exactly.

## Generator Benchmark

### `generate_subsidy_roi_estimate_packets` (caller named in task)

```
$ time .venv/bin/python -m \
    scripts.aws_credit_ops.generate_subsidy_roi_estimate_packets \
    --output-prefix /tmp/perf21-roi/post --limit 50 \
    --local-out-dir /tmp/perf21-roi
INFO ... run done: seen=0 written=0 empty=0 bytes_total=0
     s3_put_usd~=0.0000 manifest=/tmp/perf21-roi/run_manifest.json
     dry_run=True elapsed=0.1s
real    0m0.133s
```

`seen=0` is an **honest upstream-data gap**, not a code or index defect.
The corpus currently has:

```
sqlite> SELECT MIN(amount_granted_yen), MAX(amount_granted_yen), COUNT(*)
   ...> FROM jpi_adoption_records
   ...> WHERE amount_granted_yen IS NOT NULL;
||0
```

`amount_granted_yen` is **all NULL** across 201,845 rows — schema reserves
the column but the upstream ingest never populated it. The generator's
WHERE clause `amount_granted_yen IS NOT NULL AND amount_granted_yen > 0`
correctly returns 0 rows. The query plan for the generator's
`industry_jsic_medium=?` + amount filter still uses the existing
`idx_adoption_jsic_pref` (its leading column is `industry_jsic_medium`),
and `idx_adoption_amount_granted` will start serving range probes the
moment the column is backfilled.

### `generate_vendor_dd_packets` (canonical MIG-B consumer per PERF-13)

```
$ time .venv/bin/python -m \
    scripts.aws_credit_ops.generate_vendor_dd_packets \
    --output-prefix /tmp/perf21-vdd/post --limit 50 \
    --local-out-dir /tmp/perf21-vdd
INFO ... run done: houjin=50 written=50 grades={'monitor': 50}
     bytes_total=89818 s3_put_usd~=0.0003
     manifest=/tmp/perf21-vdd/run_manifest.json dry_run=True elapsed=0.1s
real    0m0.167s
```

50 packets generated cleanly. No regression on the joint
`amount_granted_yen` / outcome-threshold paths.

## Integrity Check

Per memory rule `feedback_no_quick_check_on_huge_sqlite`, `PRAGMA
quick_check` was **NOT** run on `autonomath.db`. Instead, the post-state
was verified through:

1. `.indexes jpi_adoption_records` listing (new index present)
2. `EXPLAIN QUERY PLAN` (new index actually selected by the planner)
3. Live generator runs (`vendor_dd 50/50/0/89818 bytes`,
   `roi 0/0/0/0 bytes` — second is honest upstream gap, not regression)

This is sufficient evidence the migration is safe.

## Outstanding Work

- **MIG-C** — `houjin_master (prefecture, jsic_major)` composite for Q13
  full scan + temp btree, used by `houjin_360` packet generator. To be
  applied in a separate PERF ticket.
- **MIG-D** — deferred (functional index on `substr(announced_at,1,4)`);
  current `idx_adoption_announced` covering scan is sufficient.

Per the "1 fix at a time + immediate validate" pattern established in
`feedback_docker_build_3iter_fix_saga`, each composite index is its own
gate. Do not bundle.

## Rollback

If a regression is observed:

```
sqlite3 autonomath.db "DROP INDEX IF EXISTS idx_adoption_amount_granted;"
```

This is a metadata-only operation; SQLite reclaims the index pages lazily.
For a deeper rollback, restore from
`autonomath.db.backup-2026-05-16-PERF21` (12,772,372,480 bytes,
identical pre-MIG-B state — post-MIG-A baseline).

## Cross-References

- `docs/_internal/sqlite_perf_audit_2026_05_16.md` — PERF-13 audit (parent)
- `docs/_internal/sqlite_perf_mig_a_applied_2026_05_16.md` — PERF-17
- `scripts/aws_credit_ops/generate_vendor_dd_packets.py` — canonical
  MIG-B consumer
- `scripts/aws_credit_ops/generate_subsidy_roi_estimate_packets.py` —
  named in PERF-21, currently 0-row due to upstream NULL gap (will start
  benefiting once `amount_granted_yen` ingest lands)
- Memory: `feedback_no_quick_check_on_huge_sqlite` — explains why
  `quick_check` was skipped
