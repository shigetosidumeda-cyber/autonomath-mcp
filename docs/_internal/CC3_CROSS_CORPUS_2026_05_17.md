# CC3 — Cross-Corpus Alignment + Entity Resolution

**Lane**: solo
**Date**: 2026-05-17
**DB**: `autonomath.db` (16 GB, post-PERF cascade)
**Author trailer**: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

---

## Goal

CC3 lifts the `am_entities` corpus from 14 isolated `record_kind` silos
to a **canonical-id-bridged graph** while preserving every existing row.
Three concrete outcomes:

1. **Entity duplicate detection** — bucket every `corporate_entity`,
   `adoption`, and `case_study` row by normalized houjin_bangou; assign
   a single anchor canonical_id per bucket (soft-merge, no row deletion).
2. **`am_compat_matrix` heuristic → sourced upgrade** — re-classify
   `inferred_only=1` pairs that have independent corroborating evidence
   in `am_relation` and `am_entity_facts`.
3. **4-way cross-corpus join** — expose
   `v_corp_program_judgment_law` so downstream MCP tools can resolve
   `houjin_bangou → adoption → program → law_article` in one read.

## Constraints honoured

- **No LLM API**. Pure SQL + rule-based Python. Phase 2's three upgrade
  rules (R1/R2/R3) are deterministic SQL existence checks.
- **No physical row destruction.** `entity_id_canonical` is an additive
  TEXT column; all existing canonical_ids continue to serve as primary
  keys. The soft-merge contract is "anchor + members", not "drop dupes".
- **No `PRAGMA quick_check` on the 16 GB DB.** The ETL uses ordinary
  index-backed scans and bounded UPDATE batches (2,000 rows / batch).
- **mypy strict 0 / ruff 0** in `scripts/etl/cc3_entity_canonical_assignment_2026_05_17.py`.
- **Idempotent**. Re-runs of the ETL flip zero new rows once steady-state
  is reached, and the migration is wrapped in `CREATE INDEX IF NOT EXISTS`
  / `DROP VIEW IF EXISTS` so re-applies are safe under
  `entrypoint.sh §4` (which already auto-heals "duplicate column" via
  `INSERT OR IGNORE INTO schema_migrations(...)` — see entrypoint
  lines 250-310).

## Migration

**File**: `scripts/migrations/wave24_208_am_entity_canonical_id.sql`
**Rollback**: `scripts/migrations/wave24_208_am_entity_canonical_id_rollback.sql`

DDL:

| object | kind | purpose |
|---|---|---|
| `am_entities.entity_id_canonical` | column | soft-merge anchor (TEXT NULLABLE) |
| `idx_am_entities_canonical_axis` | index | single-axis lookup |
| `idx_am_entities_kind_canonical` | index | record_kind + anchor compound |
| `idx_am_entity_facts_houjin_bangou` | partial index | houjin_bangou-only bucket |
| `idx_am_relation_type_source` | index | relation 4-way join driver |
| `idx_am_relation_type_target` | index | relation 4-way join target |
| `idx_am_law_article_law_canonical` | index | law → article hop |
| `idx_am_compat_matrix_inferred` | index | heuristic→sourced scan |
| `v_corp_program_judgment_law` | view | 4-way cross-corpus join |

Ordering note: `ALTER TABLE am_entities ADD COLUMN entity_id_canonical TEXT`
is placed LAST. `sqlite3 -bail` halts the script on the first error, so on
re-apply ("duplicate column"), the indexes / view still get created on a
fresh first-run boot, and subsequent boots take the entrypoint self-heal
path (`grep -qi "duplicate column"` → `INSERT OR IGNORE INTO schema_migrations`).

## ETL

**File**: `scripts/etl/cc3_entity_canonical_assignment_2026_05_17.py`

Two phases:

### Phase 1 — canonical-id assignment

```
collect_duplicate_groups(conn)   # bucket by TRIM(houjin_bangou)
write_canonical_anchors(...)     # UPDATE am_entities SET entity_id_canonical = anchor
assign_singletons(conn)          # UPDATE ... SET = canonical_id WHERE NULL
```

- Anchor selection: deterministic ASCII-min of group members.
- Group scope: `record_kind IN ('corporate_entity','adoption','case_study')`.
- All other kinds become self-anchors.
- Batch size: 2,000 (UPDATE).

### Phase 2 — heuristic → sourced upgrade

```
collect_heuristic_compat_rows(conn)    # WHERE inferred_only=1
upgrade_heuristic_to_sourced(db, n=8)  # multiprocessing.Pool over verify rules
```

Three deterministic SQL rules, evaluated per pair:

- **R1**: a direct `am_relation` edge between `(a,b)` or `(b,a)` with
  `relation_type ∈ {compatible, incompatible, prerequisite}`.
- **R2**: `a` and `b` both have `references_law` relations to the same law.
- **R3**: `a` and `b` both have `part_of` relations to the same parent.

Any rule firing → flip `inferred_only` 1 → 0.

## Results (2026-05-17 run)

| metric | value |
|---|---|
| duplicate groups (size ≥ 2, cross-corpus) | **166,952** |
| canonical anchor assignments written | **367,282** |
| singletons backfilled (`entity_id_canonical = canonical_id`) | **136,711** |
| total `am_entities` with anchor populated | **503,993 / 503,993** (100%) |
| `am_compat_matrix` heuristic→sourced upgrades | **495** |
| post-run `inferred_only=0` rows | **4,318** (from 3,823 baseline) |
| post-run `inferred_only=1` rows | **39,648** |
| `v_corp_program_judgment_law` shape | 14 columns, P1 materialized |
| ETL elapsed (8 workers, 16GB DB) | **27.24 s** |

Cross-corpus reach: 200,330 rows in `am_entities` now share an anchor
with at least one other row — those are the "bridge" rows the 4-way
join walks.

## v_corp_program_judgment_law — JOIN paths

Five conceptual paths; the view body materializes **P1** with LEFT
JOINs so downstream tools can filter by `NOT NULL` to walk P2..P5.

- **P1** (materialized): `corp[hb] → adoption[hb] → adoption→program[related] → program→law[references_law] → law_article`
- **P2** (canonical-axis variant): replace the `houjin_bangou` join
  with `entity_id_canonical = entity_id_canonical`. Equivalent for
  cross-corpus groups but trivially faster — recommended for hot
  query patterns.
- **P3** (judgment hop): `corp[hb] → case_study[hb] → case_study→judgment[related] → judgment→law via am_citation_network`
- **P4** (authority hop): `corp[canonical] → program[implemented_by/has_authority] → law (authority_canonical)`
- **P5** (enforcement hop): `corp[canonical] → enforcement[part_of] → law_article`

For the next layer (CC4 or beyond), P3 should become its own view
once `am_case_law` is populated beyond the current 50 rows.

## Tests

**File**: `tests/test_entity_resolution_2026_05_17.py` (20 tests).

Coverage:

1. column / view / index existence (5 tests).
2. canonical-id assignment correctness — fill rate, anchor membership,
   monotone ASCII order, cross-corpus clustering (5 tests).
3. compat_matrix sanity — sourced ≥ 100, enum valid, no self-loops (3 tests).
4. 4-way view shape — non-empty, projection contract, normalized
   houjin_bangou, corp/adopt houjin match (4 tests).
5. ETL module-level smoke — phase 1/2 function presence, dry-run is
   non-mutating (3 tests).

## Operational notes

- The migration was applied live with `sqlite3 -cmd "PRAGMA busy_timeout=30000"`
  against the running database (one concurrent reader: `ingest_egov_law_translation.py`).
- `schema_migrations` row recorded with checksum
  `5adddb040341c969bab982924d0707ac35c80c16eaa9e988a44ce64adca08d8d`.
- 4-way view full-table COUNT(*) is expensive (multi-billion theoretical
  cardinality). Use `LIMIT` or filter by `houjin_bangou` / `entity_id_canonical`
  for routine queries.

## See also

- Migration: `scripts/migrations/wave24_208_am_entity_canonical_id.sql`
- ETL: `scripts/etl/cc3_entity_canonical_assignment_2026_05_17.py`
- Tests: `tests/test_entity_resolution_2026_05_17.py`
- Prior layer (entity bridge): `scripts/migrations/wave24_168_entity_resolution_bridge_v2.sql`
- Memory: `project_jpcite_smart_analysis_pipeline_2026_05_16`, `feedback_action_bias`.
