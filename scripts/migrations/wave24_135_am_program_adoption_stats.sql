-- target_db: autonomath
-- migration wave24_135_am_program_adoption_stats (MASTER_PLAN_v1 章
-- 10.2.10 — 採択統計事前計算)
--
-- Why this exists:
--   `get_program_adoption_stats` (#106) returns
--   "for program X in fiscal year Y, what was adoption_count,
--   avg_amount, success_rate, industry_distribution,
--   region_distribution". JSON columns let the read path return a
--   single row that the API serializes verbatim.
--
-- Schema:
--   * program_unified_id TEXT NOT NULL
--   * fiscal_year INTEGER NOT NULL
--   * adoption_count INTEGER NOT NULL DEFAULT 0
--   * applicant_count INTEGER                — denominator for success_rate
--   * success_rate REAL                      — 0..1
--   * avg_amount_man_yen REAL
--   * median_amount_man_yen REAL
--   * total_amount_man_yen REAL
--   * industry_distribution TEXT             — JSON {jsic_major: ratio_0..1}
--   * region_distribution TEXT               — JSON {prefecture_code: ratio_0..1}
--   * source_snapshot_id TEXT
--   * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--   * UNIQUE (program_unified_id, fiscal_year)
--
-- Indexes:
--   * (program_unified_id, fiscal_year DESC) — single program time-series.
--   * (fiscal_year, success_rate DESC) — KPI roll-up "highest success rate in FYY".
--
-- Idempotency:
--   CREATE * IF NOT EXISTS, INSERT OR REPLACE under UNIQUE.
--
-- DOWN:
--   See companion `wave24_135_am_program_adoption_stats_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_program_adoption_stats (
    stat_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    program_unified_id     TEXT NOT NULL,
    fiscal_year            INTEGER NOT NULL,
    adoption_count         INTEGER NOT NULL DEFAULT 0,
    applicant_count        INTEGER,
    success_rate           REAL CHECK (success_rate IS NULL OR
                                       (success_rate >= 0.0 AND success_rate <= 1.0)),
    avg_amount_man_yen     REAL,
    median_amount_man_yen  REAL,
    total_amount_man_yen   REAL,
    industry_distribution  TEXT,    -- JSON {jsic_major: ratio}
    region_distribution    TEXT,    -- JSON {prefecture_code: ratio}
    source_snapshot_id     TEXT,
    computed_at            TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (program_unified_id, fiscal_year)
);

CREATE INDEX IF NOT EXISTS idx_apas_program_fy
    ON am_program_adoption_stats(program_unified_id, fiscal_year DESC);

CREATE INDEX IF NOT EXISTS idx_apas_fy_success
    ON am_program_adoption_stats(fiscal_year, success_rate DESC)
    WHERE success_rate IS NOT NULL;
