-- target_db: autonomath
-- migration 114_adoption_program_join
--
-- Why: `jpi_adoption_records` (~201,845 rows) carries a free-text
-- `program_name_raw` column from 採択公表 PDFs but no foreign key to
-- `programs.id` / `programs.unified_id` (which lives in jpintel.db, not
-- ATTACHable). The API has no way to answer "which 制度 does this 採択
-- belong to?" — the join rate is 0%.
--
-- Plan refs: docs/_internal/value_maximization_plan_no_llm_api.md §7.1
-- (採択金額・採択者・制度join 最優先) + §28.7 (90日 Evidence Graph
-- milestone). The same plan calls out the join column as nullable on
-- purpose: programs lives in a separate SQLite file and we deliberately
-- never ATTACH (architecture forbids cross-DB JOIN).
--
-- Schema additions (autonomath.db only, never touch programs):
--   * `program_id`               TEXT, nullable. Holds the matched
--                                 `programs.unified_id`. NOT a FK because
--                                 the target table is in jpintel.db.
--   * `program_id_match_method`  TEXT, one of:
--                                 'exact_alias' | 'fuzzy_name_high' |
--                                 'fuzzy_name_med' | 'unknown'.
--   * `program_id_match_score`   REAL in [0.0, 1.0]. 1.0 for
--                                 exact_alias matches; ratio for fuzzy.
--
-- Index `idx_jpi_adoption_records_program_id` covers the API hot path
-- (count of matches per program) + the cron's "WHERE program_id IS NULL"
-- backfill scan.
--
-- Idempotency: ADD COLUMN IF NOT EXISTS is not portable SQLite syntax,
-- so we rely on (a) the migrate.py duplicate-column fallback that records
-- the migration as applied even when ALTER TABLE raises "duplicate column
-- name", and (b) `CREATE INDEX IF NOT EXISTS` on the index. The same
-- pattern is used in migrations 049/067_autonomath/077/078/082/090/092/101.
-- entrypoint.sh §4 self-heal loop also picks this file up via the
-- `target_db: autonomath` marker on line 1.

ALTER TABLE jpi_adoption_records ADD COLUMN program_id TEXT;
ALTER TABLE jpi_adoption_records ADD COLUMN program_id_match_method TEXT;
ALTER TABLE jpi_adoption_records ADD COLUMN program_id_match_score REAL;

CREATE INDEX IF NOT EXISTS idx_jpi_adoption_records_program_id
    ON jpi_adoption_records(program_id, program_id_match_method);

-- Bookkeeping recorded by scripts/migrate.py + entrypoint.sh §4.
