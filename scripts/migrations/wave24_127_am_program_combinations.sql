-- target_db: autonomath
-- migration wave24_127_am_program_combinations (MASTER_PLAN_v1 章 10.2.2 —
-- 制度ペア併給可否 事前計算テーブル)
--
-- Why this exists:
--   `find_combinable_programs` (#98) and `find_complementary_subsidies`
--   (#115) need to answer "given program A, can it be combined with
--   program B" without scanning the full Cartesian (11,601 ^ 2 ≈
--   136M pair) at request time. The classification is computed
--   offline by `scripts/etl/precompute_program_combinations.py`
--   from the existing `am_compat_matrix` (43,966 rows, sourced +
--   heuristic) and `exclusion_rules` (181 rows).
--
--   We canonicalize ordering with the CHECK
--   (program_a_unified_id < program_b_unified_id) so each unordered
--   pair lives in exactly ONE row. INSERT OR IGNORE on UNIQUE then
--   becomes a "first writer wins" upsert and the cron is safely
--   idempotent.
--
-- Schema:
--   * program_a_unified_id TEXT NOT NULL
--   * program_b_unified_id TEXT NOT NULL
--   * combinable INTEGER NOT NULL  — 0=incompatible, 1=combinable, 2=requires_review
--   * confidence TEXT              — 'high'|'medium'|'low'
--   * reason TEXT                  — short prose
--   * source_url TEXT              — primary citation (when combinable=0
--                                    is sourced from an explicit clause)
--   * source_kind TEXT             — 'exclusion_rule'|'compat_matrix'|'heuristic'
--   * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--   * CHECK(program_a_unified_id < program_b_unified_id)
--   * UNIQUE(program_a_unified_id, program_b_unified_id)
--
-- Indexes:
--   * (program_a_unified_id) and (program_b_unified_id) so a query
--     filtering by either side is cheap.
--
-- Idempotency:
--   CREATE * IF NOT EXISTS. The canonical-ordering CHECK + UNIQUE
--   guarantees `INSERT OR IGNORE` is the safe upsert primitive
--   when the cron re-runs.
--
-- DOWN:
--   See companion `wave24_127_am_program_combinations_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_program_combinations (
    pair_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    program_a_unified_id TEXT NOT NULL,
    program_b_unified_id TEXT NOT NULL,
    combinable           INTEGER NOT NULL CHECK (combinable IN (0, 1, 2)),
    confidence           TEXT CHECK (confidence IS NULL OR confidence IN
                                     ('high','medium','low')),
    reason               TEXT,
    source_url           TEXT,
    source_kind          TEXT CHECK (source_kind IS NULL OR source_kind IN
                                     ('exclusion_rule','compat_matrix','heuristic')),
    computed_at          TEXT NOT NULL DEFAULT (datetime('now')),
    -- canonical ordering: each unordered pair lives in exactly one row.
    CHECK (program_a_unified_id < program_b_unified_id),
    UNIQUE (program_a_unified_id, program_b_unified_id)
);

CREATE INDEX IF NOT EXISTS idx_apc_a
    ON am_program_combinations(program_a_unified_id);

CREATE INDEX IF NOT EXISTS idx_apc_b
    ON am_program_combinations(program_b_unified_id);
