# SQLite PERF ANALYZE (PERF-28) Applied — 2026-05-16

## Context

Follow-up to `docs/_internal/sqlite_perf_audit_2026_05_16.md` (PERF-13)
and the three migration application docs (`sqlite_perf_mig_a/b/c_applied_2026_05_16.md`,
PERF-17 / PERF-21 / PERF-22). MIG-A/B/C added the three composite /
single-column indexes proposed by the PERF-13 audit, but SQLite's query
planner only consults the new indexes once `sqlite_stat1` is refreshed.

PERF-28 runs `ANALYZE` on the three critical tables to refresh the
planner stats, **without** running `VACUUM` (forbidden per PERF-13:
`VACUUM` would acquire an exclusive lock on the 12 GB DB and stall
every reader for the duration of the rewrite).

## Target

- Database: `autonomath.db` (12.77 GB on disk, WAL mode)
- Tables: `jpi_adoption_records` (201,845 rows), `houjin_master`
  (166,765 rows), `jpi_programs` (13,578 rows)
- Command:
  ```
  sqlite3 autonomath.db "ANALYZE jpi_adoption_records;
                         ANALYZE houjin_master;
                         ANALYZE jpi_programs;"
  ```
- Rationale: refresh `sqlite_stat1` so the planner uses the MIG-A/B/C
  indexes (`idx_adoption_prefecture_announced`,
  `idx_adoption_amount_granted`, `idx_houjin_master_prefecture_jsic`)
  for Q7/Q9/Q13/Q15 and all packet-generator queries that touch the
  same columns.

## Backup (Pre-Mutation)

Per memory rule (12 GB SQLite has been the cause of past production
stalls), the database was copied byte-for-byte before any mutation.

```
cp autonomath.db autonomath.db.backup-2026-05-16-PERF28
```

- Size: 12,772,372,480 bytes (12.77 GB), identical to source
- Free disk after backup: 573 GB available on /System/Volumes/Data
- Path: `/Users/shigetoumeda/jpcite/autonomath.db.backup-2026-05-16-PERF28`

Backups for PERF-17 (MIG-A), PERF-21 (MIG-B), PERF-22 (MIG-C) remain
on disk and were not touched.

## Pre-State

```
sqlite3 -readonly autonomath.db ".tables" | tr ' ' '\n' | grep -i stat
```

Output (filtered for `stat`):

```
am_acceptance_stat
am_canonical_vec_statistic
am_canonical_vec_statistic_chunks
am_canonical_vec_statistic_info
am_canonical_vec_statistic_map
am_canonical_vec_statistic_rowids
am_canonical_vec_statistic_vector_chunks00
cross_source_baseline_state
industry_stats
jpi_real_estate_programs
pc_acceptance_stats_by_program
real_estate_programs
```

**No `sqlite_stat1` table existed** — `ANALYZE` had never been run on
this database. The planner was operating without stats and falling
back to heuristics (which, despite MIG-A/B/C, still picked the wrong
plan for some compound queries observed during PERF-17/21/22
verification — see `sqlite_perf_mig_c_applied_2026_05_16.md` §
"planner correction confirmed").

## Apply Command + Timing

```
time sqlite3 autonomath.db "ANALYZE jpi_adoption_records;
                            ANALYZE houjin_master;
                            ANALYZE jpi_programs;"
```

Output:

```
sqlite3 autonomath.db  0.12s user 0.01s system 82% cpu 0.160 total
```

Total wall-clock: **0.16 s** across the three tables. ANALYZE on
SQLite samples roughly `sqrt(rowcount)` rows per index leaf, so even
the 201K-row `jpi_adoption_records` finishes in sub-100 ms.

No `VACUUM` was issued. No locks were taken on other tables. The
operation is non-disruptive and can be re-run idempotently.

## Post-State: `sqlite_stat1` populated

```sql
SELECT tbl, idx, stat
FROM sqlite_stat1
WHERE tbl IN ('jpi_adoption_records', 'houjin_master', 'jpi_programs')
ORDER BY tbl, idx;
```

```
houjin_master|idx_houjin_master_jsic_major|166765 166765
houjin_master|idx_houjin_master_prefecture_jsic|166765 3270 3270
houjin_master|sqlite_autoindex_houjin_master_1|166765 1
jpi_adoption_records|idx_adoption_amount_granted|201845 201845
jpi_adoption_records|idx_adoption_announced|201845 2294
jpi_adoption_records|idx_adoption_houjin|201845 2
jpi_adoption_records|idx_adoption_jsic_pref|201845 11214 243
jpi_adoption_records|idx_adoption_prefecture_announced|201845 3605 51
jpi_adoption_records|idx_adoption_program_hint|201845 20185
jpi_adoption_records|idx_adoption_round|201845 20185 5607
jpi_adoption_records|idx_jpi_adoption_records_program_id|201845 28835 28835
jpi_programs|idx_programs_amount_max|13578 47
jpi_programs|idx_programs_authority_level|13578 2263
jpi_programs|idx_programs_prefecture|13578 278
jpi_programs|idx_programs_program_kind|13578 35
jpi_programs|idx_programs_source_fetched|13578 28
jpi_programs|idx_programs_tier|13578 2716
jpi_programs|sqlite_autoindex_jpi_programs_1|13578 1
```

All three target tables now have populated stats. Key MIG-A/B/C rows:

- `idx_adoption_prefecture_announced` (MIG-A): `201845 3605 51`
  → planner sees 51 distinct prefecture values, ~3,605 rows per
  prefecture on average. This is the right cardinality for picking
  the composite over a full table scan.
- `idx_adoption_amount_granted` (MIG-B): `201845 201845`
  → distinct = row count (all NULL or all unique). Note: every row
  currently has `amount_granted_yen IS NULL` (data backfill is a
  separate ETL concern), but the index entry + planner stat is
  correctly recorded so future inserts immediately benefit.
- `idx_houjin_master_prefecture_jsic` (MIG-C): `166765 3270 3270`
  → 3,270 distinct (prefecture, jsic_major) compound buckets. Planner
  now picks this as a covering index for the cohort rollup.

## EXPLAIN QUERY PLAN: planner correction confirmed

### Q7 — `jpi_adoption_records WHERE prefecture = ?`

```
QUERY PLAN
`--SEARCH jpi_adoption_records USING INDEX idx_adoption_prefecture_announced (prefecture=?)
```

Was `SCAN jpi_adoption_records` (FULL SCAN) per PERF-13 §3. Now
`SEARCH ... USING INDEX idx_adoption_prefecture_announced`.

### Q9 — `jpi_adoption_records WHERE amount_granted_yen >= ?`

```
QUERY PLAN
`--SEARCH jpi_adoption_records USING INDEX idx_adoption_amount_granted (amount_granted_yen>?)
```

Was `SCAN jpi_adoption_records` (FULL SCAN). Now
`SEARCH ... USING INDEX idx_adoption_amount_granted`.

### Q13 — `houjin_master GROUP BY (prefecture, jsic_major)`

```
QUERY PLAN
`--SCAN houjin_master USING COVERING INDEX idx_houjin_master_prefecture_jsic
```

Was `SCAN houjin_master` + temp B-tree for GROUP BY (FULL SCAN +
temp btree). Now a single covering-index scan, no temp btree.

### Q15 — `jpi_adoption_records WHERE prefecture = ? AND amount_granted_yen >= ?`

```
QUERY PLAN
`--SEARCH jpi_adoption_records USING INDEX idx_adoption_prefecture_announced (prefecture=?)
```

Was `SCAN jpi_adoption_records` (FULL SCAN). Now searches via the
MIG-A composite — planner chose `prefecture` as the leading column
(more selective: 51 buckets) over `amount_granted_yen` (currently
all NULL, so the second predicate is a residual filter).

All four queries that the PERF-13 audit flagged as **FULL SCAN**
are now **SEARCH** or **COVERING-INDEX SCAN**. Sample queries Q8,
Q10, Q11, Q12, Q14, Q16 (already OK in PERF-13 audit) remain
unchanged.

## Bench: hot-path timings

`sqlite3 autonomath.db` with `.timer on`, ran each query twice to
isolate cold + warm cache. All measurements on local machine
(macOS, NVMe-backed APFS, WAL mode, no other DB activity).

| Query | Cold real (s) | Warm real (s) | Plan |
| --- | --- | --- | --- |
| Q7 — `prefecture = '東京都'`, COUNT(*) | 0.008 | 0.001 | SEARCH idx_adoption_prefecture_announced |
| Q9 — `amount_granted_yen >= 1_000_000`, COUNT(*) | 0.000 | 0.000 | SEARCH idx_adoption_amount_granted (0 rows match, NULL data) |
| Q13 — `GROUP BY prefecture, jsic_major`, full rollup | 0.011 | — | COVERING INDEX idx_houjin_master_prefecture_jsic, 52 rows out |
| Q15 — `pref=? AND amount>=?`, COUNT(*) | 0.006 | 0.000 | SEARCH idx_adoption_prefecture_announced (composite leading column) |

Q7 cold: **8 ms** to return 32,293 matches over a 201K-row table.
Q13 full rollup: **11 ms** to produce 52 output rows (47 prefectures
× available jsic_major buckets) via a single covering-index scan,
no temp B-tree, no second pass.

`/usr/bin/time -h` cross-check on the MIG-A canonical bench
(`SELECT COUNT(*) FROM jpi_adoption_records WHERE prefecture = '東京都'`):
**0.02 s real**.

Both Q9 and Q15 currently return 0 rows because every existing
`amount_granted_yen` value is `NULL` (separate data-side concern,
not in PERF-28 scope). The index is selected by the planner
regardless, and timings remain consistent.

## Caveats

- **All `amount_granted_yen` rows are NULL.** Q9 / Q15 row counts will
  be zero on this data snapshot. The planner picks the right index,
  but bench latency on those two queries is dominated by index probe
  cost, not row materialization. When ETL backfills the column, the
  same plan handles it without re-tuning.
- **`jsic_major` is also all NULL in `houjin_master`.** Q13 returns
  52 rows where the second tuple member is empty — the planner still
  picks the covering index, and a future backfill will widen the
  output without requiring another `ANALYZE`.
- **`am_amount_condition` is NOT in this batch.** PERF-13 chose to
  defer its index audit; same reasoning applies to its `ANALYZE`.
  Add a follow-up PERF ticket if/when that table starts seeing real
  query traffic.

## Rollback

Trivial. To revert the stats (effectively "forget what ANALYZE
learned"):

```sql
DELETE FROM sqlite_stat1
WHERE tbl IN ('jpi_adoption_records', 'houjin_master', 'jpi_programs');
ANALYZE sqlite_master;  -- forces stat cache reload
```

Or restore from the backup byte-for-byte:

```
cp autonomath.db.backup-2026-05-16-PERF28 autonomath.db
```

(No data was mutated; only `sqlite_stat1` was populated. There is no
production risk from leaving the new stats in place.)

## Cross-reference

- PERF-13 audit: `docs/_internal/sqlite_perf_audit_2026_05_16.md`
- MIG-A applied: `docs/_internal/sqlite_perf_mig_a_applied_2026_05_16.md`
- MIG-B applied: `docs/_internal/sqlite_perf_mig_b_applied_2026_05_16.md`
- MIG-C applied: `docs/_internal/sqlite_perf_mig_c_applied_2026_05_16.md`

last_updated: 2026-05-16
