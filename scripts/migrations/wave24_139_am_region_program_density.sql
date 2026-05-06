-- target_db: autonomath
-- migration wave24_139_am_region_program_density (MASTER_PLAN_v1 章
-- 10.2.14 — 地域 × JSIC density, #117 用)
--
-- Why this exists:
--   `get_industry_program_density` (#117) needs a precomputed
--   per-(region × jsic) density rollup. The base table
--   `am_region_program_density` is created here; wave24_112 also
--   declares it under IF NOT EXISTS as a defensive duplicate so
--   either migration can land independently. Both shapes are
--   identical — apply order is irrelevant.
--
--   This file ALSO adds the supporting cohort breakdown table
--   `am_region_program_density_breakdown` (per program list,
--   keeps the rollup readers small) which is unique to this
--   migration.
--
-- Schema:
--   am_region_program_density
--     (created here OR by wave24_112; identical column shape under
--      IF NOT EXISTS so re-apply collapses to no-op)
--
--   am_region_program_density_breakdown
--     * breakdown_id INTEGER PRIMARY KEY AUTOINCREMENT
--     * region_code TEXT NOT NULL
--     * jsic_major TEXT NOT NULL
--     * program_unified_id TEXT NOT NULL
--     * tier TEXT
--     * is_open INTEGER
--     * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--     * UNIQUE (region_code, jsic_major, program_unified_id)
--
-- Indexes:
--   * (region_code, jsic_major) on breakdown for "list-the-programs".
--   * (program_unified_id) reverse lookup.
--
-- Idempotency:
--   CREATE * IF NOT EXISTS, INSERT OR REPLACE under UNIQUE.
--
-- DOWN:
--   See companion `wave24_139_am_region_program_density_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_region_program_density (
    density_id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    region_code                      TEXT NOT NULL,
    jsic_major                       TEXT NOT NULL,
    program_count                    INTEGER NOT NULL DEFAULT 0,
    programs_per_million_yen_gdp     REAL,
    programs_per_business            REAL,
    percentile_in_prefecture         REAL,
    computed_at                      TEXT NOT NULL DEFAULT (datetime('now')),
    source_snapshot_id               TEXT,
    UNIQUE (region_code, jsic_major)
);

CREATE INDEX IF NOT EXISTS idx_arpd_region
    ON am_region_program_density(region_code);

CREATE INDEX IF NOT EXISTS idx_arpd_jsic
    ON am_region_program_density(jsic_major);

CREATE TABLE IF NOT EXISTS am_region_program_density_breakdown (
    breakdown_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    region_code         TEXT NOT NULL,
    jsic_major          TEXT NOT NULL,
    program_unified_id  TEXT NOT NULL,
    tier                TEXT,
    is_open             INTEGER CHECK (is_open IS NULL OR is_open IN (0, 1)),
    computed_at         TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (region_code, jsic_major, program_unified_id)
);

CREATE INDEX IF NOT EXISTS idx_arpdb_region_jsic
    ON am_region_program_density_breakdown(region_code, jsic_major);

CREATE INDEX IF NOT EXISTS idx_arpdb_program
    ON am_region_program_density_breakdown(program_unified_id);
