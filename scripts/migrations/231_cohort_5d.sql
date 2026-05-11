-- target_db: autonomath
-- migration: 231_cohort_5d
-- generated_at: 2026-05-12
-- author: Wave 33 Axis 2a — 5-axis cohort precompute (jpcite 2026-05-12)
--
-- Purpose
-- -------
-- Pre-compute eligible-program set per (houjin × jsic_major × employee_band
-- × prefecture_code × program-eligibility-chain) cohort cell. The on-demand
-- match path (POST /v1/cohort/5d/match) reads the cached list verbatim
-- instead of re-doing the 5-axis join against houjin_master × 11,601
-- programs × eligibility chain at request time.
--
-- Why precompute (not a runtime view)
-- -----------------------------------
-- * 5-axis Cartesian is O(N×M×K×P×R) — full evaluation per request would
--   scan houjin_master (~500k rows) × programs (~11.6k) per call.
-- * MCP tool `match_cohort_5d_am` must return inside FastMCP 1s envelope.
-- * Memory `feedback_no_quick_check_on_huge_sqlite` forbids full-scan ops
--   on 9.7GB autonomath.db at runtime; precompute path is one daily job.
--
-- Schema
-- ------
-- cohort_id           autoincrement PK
-- houjin_bangou       13-digit FK soft ref; NULL = synthetic band cohort
-- jsic_major          1 char (A-T)
-- employee_band       '1-9' / '10-99' / '100-999' / '1000+'
-- prefecture_code     2-digit JIS or NULL = nationwide
-- eligible_program_ids JSON array, sorted tier (S/A/B/C) then amount DESC
-- eligible_count       len(eligible_program_ids), materialized
-- last_refreshed_at    ISO-8601 UTC

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_cohort_5d (
    cohort_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou          TEXT,
    jsic_major             TEXT NOT NULL,
    employee_band          TEXT NOT NULL,
    prefecture_code        TEXT,
    eligible_program_ids   TEXT NOT NULL DEFAULT '[]',
    eligible_count         INTEGER NOT NULL DEFAULT 0,
    last_refreshed_at      TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT ck_cohort_5d_band CHECK (employee_band IN (
        '1-9', '10-99', '100-999', '1000+'
    )),
    CONSTRAINT ck_cohort_5d_jsic CHECK (length(jsic_major) = 1),
    CONSTRAINT ck_cohort_5d_pref CHECK (prefecture_code IS NULL OR length(prefecture_code) = 2)
);

CREATE INDEX IF NOT EXISTS idx_cohort_5d_jbp
    ON am_cohort_5d(jsic_major, employee_band, prefecture_code);
CREATE INDEX IF NOT EXISTS idx_cohort_5d_houjin
    ON am_cohort_5d(houjin_bangou) WHERE houjin_bangou IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cohort_5d_refresh
    ON am_cohort_5d(last_refreshed_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cohort_5d_tuple
    ON am_cohort_5d(
        COALESCE(houjin_bangou, '_synthetic'),
        jsic_major,
        employee_band,
        COALESCE(prefecture_code, '_nationwide')
    );

DROP VIEW IF EXISTS v_cohort_5d_top;
CREATE VIEW v_cohort_5d_top AS
SELECT
    jsic_major,
    employee_band,
    prefecture_code,
    COUNT(*) AS cohort_rows,
    AVG(eligible_count) AS avg_eligible,
    MAX(eligible_count) AS max_eligible
FROM am_cohort_5d
GROUP BY jsic_major, employee_band, prefecture_code
ORDER BY avg_eligible DESC;
