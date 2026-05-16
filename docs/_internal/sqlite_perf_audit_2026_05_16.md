# SQLite Performance Audit: `autonomath.db` (12 GB) — 2026-05-16

PERF-13 (companion to PERF-10 perf SOT). Read-only index audit of the unified
primary DB at repo root. **No DB mutation** — recommendations are migration
proposals, never auto-applied.

- DB path: `/Users/shigetoumeda/jpcite/autonomath.db`
- Physical size: 12.77 GB on disk (page_count 3,118,255 × page_size 4096; freelist 71,006 pages ≈ 277 MB reclaimable)
- Journal mode: `wal` (already optimal for concurrent read + ETL writer)
- Cache: 2000 pages default (~8 MB). PERF-10 follow-up: consider per-connection `PRAGMA cache_size=-262144` (256 MB) for packet generator processes.
- Method: open via `sqlite3 autonomath.db` (read-only intent, no mutating statement issued), run `.indexes`, `.schema`, and `EXPLAIN QUERY PLAN` on representative packet-generator queries lifted from `scripts/aws_credit_ops/generate_*_packets.py`.

> Note on column drift: the audit checklist named `houjin_bangou` / `jsic_major` / `fiscal_year` / `prefecture` axes. On `jpi_adoption_records` the JSIC axis is stored as `industry_jsic_medium` (jsic_major is derived at query time via `SUBSTR(industry_jsic_medium, 1, 1)`), and `fiscal_year` is derived from `SUBSTR(announced_at, 1, 4)` — there is no `fiscal_year` column. On `houjin_master` (unified, post-V4 absorption) the jsic axis is materialised as `jsic_major` / `jsic_middle` / `jsic_minor`.

## 1. Tables audited

| Table | Rows | Used by (packet generators) |
| --- | ---: | --- |
| `jpi_adoption_records` | 201,845 | `generate_houjin_360_packets.py`, `generate_acceptance_probability_packets.py`, `generate_subsidy_timeline_packets.py`, `generate_program_lineage_packets.py`, `generate_enforcement_heatmap_packets.py`, `generate_regulatory_radar_packets.py`, `generate_invoice_houjin_check_packets.py`, `generate_vendor_dd_packets.py`, `generate_sample_packet_showcase.py` |
| `jpi_houjin_master` | 166,765 | (delta mirror) — primary path is `houjin_master` post V4 merge |
| `houjin_master` (unified) | ≈166K | `generate_houjin_360_packets.py` (`SQL_BATCH_MASTER` IN-list) |
| `jpi_programs` | 13,578 | `generate_program_lineage_packets.py`, multiple cross-source generators |

## 2. Existing indexes

### `jpi_adoption_records` (6 indexes)

| Index | Columns | Notes |
| --- | --- | --- |
| `idx_adoption_houjin` | `(houjin_bangou)` | Hot path for houjin_360 IN-list batch |
| `idx_adoption_program_hint` | `(program_id_hint)` | Pre-resolution hint |
| `idx_adoption_jsic_pref` | `(industry_jsic_medium, prefecture)` | Cohort prefix-only |
| `idx_adoption_announced` | `(announced_at)` | Time-range scan, **covering** for fiscal_year aggregations |
| `idx_adoption_round` | `(program_id_hint, round_number)` | Round-level dedup |
| `idx_jpi_adoption_records_program_id` | `(program_id, program_id_match_method)` | Post-resolution lineage |

### `jpi_houjin_master` (4 explicit + 1 autoindex)

| Index | Columns | Notes |
| --- | --- | --- |
| `sqlite_autoindex_jpi_houjin_master_1` | `(houjin_bangou)` PK | |
| `idx_houjin_name` | `(normalized_name)` | |
| `idx_houjin_prefecture` | `(prefecture, municipality)` | |
| `idx_houjin_ctype` | `(corporation_type)` | |
| `idx_houjin_active` | `(close_date) WHERE close_date IS NULL` | Partial — active-corp filter |

### `houjin_master` (unified, post V4)

| Index | Columns | Notes |
| --- | --- | --- |
| `sqlite_autoindex_houjin_master_1` | `(houjin_bangou)` PK | Hot path for `SQL_BATCH_MASTER` |
| `idx_houjin_master_jsic_major` | `(jsic_major)` | |

### `jpi_programs` (6 indexes + autoindex)

| Index | Columns | Notes |
| --- | --- | --- |
| `sqlite_autoindex_jpi_programs_1` | `(unified_id)` PK | |
| `idx_programs_tier` | `(tier)` | |
| `idx_programs_prefecture` | `(prefecture)` | |
| `idx_programs_authority_level` | `(authority_level)` | |
| `idx_programs_program_kind` | `(program_kind)` | |
| `idx_programs_amount_max` | `(amount_max_man_yen)` | |
| `idx_programs_source_fetched` | `(source_fetched_at)` | |

## 3. EXPLAIN QUERY PLAN — sampled

Each Q lifted from a real packet generator. Lines that hit `SCAN <table>` (no USING INDEX) are full-table scans.

| ID | Query (paraphrased) | Plan | Status |
| --- | --- | --- | --- |
| Q1 | `jpi_adoption_records` `WHERE houjin_bangou IN (...)` GROUP BY | `SEARCH ... USING INDEX idx_adoption_houjin` | OK |
| **Q2** | `jpi_adoption_records` full cohort aggregator (no WHERE on indexed column) — `WHERE announced_at IS NOT NULL AND length(announced_at) >= 4` | `SCAN jpi_adoption_records` | **FULL SCAN** |
| Q3 | `jpi_adoption_records` `WHERE announced_at >= ? AND announced_at < ?` | `SEARCH ... USING INDEX idx_adoption_announced` | OK |
| Q4 | `jpi_houjin_master` `WHERE prefecture=? AND municipality=?` | `SEARCH ... USING INDEX idx_houjin_prefecture` | OK |
| Q5 | `jpi_programs` `WHERE prefecture=? AND tier IN (...)` | `SEARCH ... USING INDEX idx_programs_prefecture` | OK |
| Q6 | `jpi_programs` `WHERE program_kind=? AND amount_max_man_yen >= ?` | `SEARCH ... USING INDEX idx_programs_program_kind` | OK |
| **Q7** | `jpi_adoption_records` `WHERE prefecture=?` (alone) | `SCAN jpi_adoption_records` | **FULL SCAN** |
| Q8 | `jpi_adoption_records` `WHERE industry_jsic_medium=?` | `SEARCH ... USING INDEX idx_adoption_jsic_pref` | OK (prefix) |
| **Q9** | `jpi_adoption_records` `WHERE amount_granted_yen >= ?` | `SCAN jpi_adoption_records` | **FULL SCAN** |
| Q10 | `jpi_adoption_records` `WHERE program_id=? ORDER BY announced_at DESC` | `SEARCH USING idx_jpi_adoption_records_program_id` + `USE TEMP B-TREE FOR ORDER BY` | OK; ORDER BY uses temp btree |
| Q11 | `jpi_houjin_master` `WHERE corporation_type=?` | `SEARCH ... USING idx_houjin_ctype` | OK |
| Q12 | `houjin_master` `WHERE houjin_bangou IN (...)` | `SEARCH ... USING sqlite_autoindex_houjin_master_1` | OK |
| **Q13** | `houjin_master` GROUP BY `prefecture, jsic_major` | `SCAN houjin_master` + temp btree | **FULL SCAN** |
| Q14 | `jpi_adoption_records` fiscal_year rollup via substr | `SCAN ... USING COVERING INDEX idx_adoption_announced` | OK (covering scan is fine) |
| **Q15** | `jpi_adoption_records` `WHERE prefecture=? AND amount_granted_yen >= ?` | `SCAN jpi_adoption_records` | **FULL SCAN** |
| Q16 | `jpi_houjin_master` `WHERE close_date IS NULL` | `SEARCH ... USING COVERING INDEX idx_houjin_active` | OK (partial) |

## 4. Missing index proposals (read-only audit — DO NOT auto-create)

Each entry is a migration proposal scoped to one table and one PR. All proposals are additive (`CREATE INDEX IF NOT EXISTS`) and reversible.

### MIG-A — `jpi_adoption_records (prefecture, announced_at)`

- **Evidence**: Q7 (full scan on `prefecture=?`) and Q15 (full scan on `prefecture=? AND amount_granted_yen >= ?`). 201,845 rows, ~2 GB of leaf pages walked per call.
- **Why this composite**: `prefecture` is selective (47 prefectures + UNKNOWN), and most callers also constrain or aggregate by `announced_at`. Composite gives both a single-column `prefecture` lookup and a covering range scan for time-window cohorts.
- **Proposal**:
  ```sql
  -- target_db: autonomath
  CREATE INDEX IF NOT EXISTS idx_adoption_pref_announced
      ON jpi_adoption_records(prefecture, announced_at);
  ```
- **Cost**: ~12-18 MB index (8 bytes/row × 201K + overhead). One-time CREATE ≈ 30-60s on a 12 GB DB.
- **Risk**: low (additive, idempotent). Verify no regression on `idx_adoption_jsic_pref` (kept as-is — covers `industry_jsic_medium` alone).

### MIG-B — `jpi_adoption_records (amount_granted_yen)`

- **Evidence**: Q9 (full scan on `amount_granted_yen >= ?`). Used by `generate_vendor_dd_packets.py` + outcome assertion thresholds.
- **Proposal**:
  ```sql
  -- target_db: autonomath
  CREATE INDEX IF NOT EXISTS idx_adoption_amount_granted
      ON jpi_adoption_records(amount_granted_yen);
  ```
- **Cost**: ~8 MB. Risk: low.

### MIG-C — `houjin_master (prefecture, jsic_major)`

- **Evidence**: Q13 (full scan + temp btree for GROUP BY). The `houjin_360` packet generator and cohort aggregators repeatedly rollup by `(prefecture, jsic_major)` over 166K rows.
- **Proposal**:
  ```sql
  -- target_db: autonomath
  CREATE INDEX IF NOT EXISTS idx_houjin_master_pref_jsic
      ON houjin_master(prefecture, jsic_major);
  ```
- **Cost**: ~10 MB. Risk: low. Note: `idx_houjin_master_jsic_major` already exists; this composite extends rather than replaces it.

### MIG-D (deferred — DO NOT propose yet)

`fiscal_year` is a derived column (SUBSTR over `announced_at`). The existing `idx_adoption_announced` already covers the rollup via covering-index scan (Q14). A dedicated functional/expression index on `substr(announced_at,1,4)` is **not** justified at this row count — defer until a profile shows >50ms latency contribution.

## 5. Migration plan (proposed — operator decision required)

- Each MIG-A/B/C is a **separate 1-table migration file** under `scripts/migrations/`, header `-- target_db: autonomath`, idempotent `CREATE INDEX IF NOT EXISTS`, no rollback companion required (drop-index is trivial if needed: `DROP INDEX IF EXISTS …`).
- Apply path: `entrypoint.sh` §4 auto-discovers any new `scripts/migrations/*.sql` with `-- target_db: autonomath` and runs idempotently per boot. No `release_command` change.
- Sequence: MIG-A first (largest QPS impact: 9 packet generators touch `jpi_adoption_records` × prefecture / time), then MIG-C (houjin rollup), then MIG-B (amount filter).
- After each merge, re-run the 16 EXPLAIN probes above and confirm previously-SCAN plans flip to SEARCH. Add a check to PERF-10 SOT.

## 6. What was NOT changed

- **Zero DB mutation**: no `CREATE INDEX`, no `ANALYZE`, no `VACUUM`, no `PRAGMA optimize` run during this audit.
- WAL mode is already on (PRAGMA `journal_mode=wal`); no change proposed.
- 71,006 freelist pages (~277 MB) exist but `VACUUM` is **not** proposed in this audit — it would rewrite the 12 GB file and lock the prod DB. Track in a separate PERF item if storage reclamation becomes a concern.

## 7. References

- Audit script (read-only): direct `sqlite3 autonomath.db` session (no mutating SQL issued).
- Source generators surveyed: `scripts/aws_credit_ops/generate_houjin_360_packets.py:258-293`, `scripts/aws_credit_ops/generate_acceptance_probability_packets.py:260-306`, `scripts/aws_credit_ops/generate_subsidy_timeline_packets.py:200-260`.
- Companion docs: `docs/_internal/api_perf_profile_2026_05_16.md` (PERF-7), PERF-10 perf SOT doc.

last_updated: 2026-05-16
