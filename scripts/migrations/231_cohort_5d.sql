-- target_db: autonomath
-- migration: 231_cohort_5d
-- generated_at: 2026-05-12
-- author: Wave 33 Axis 2a — 5-axis cohort precompute (jpcite 2026-05-12)
--
-- Purpose
-- -------
-- Pre-compute the eligible-program set for every (houjin × jsic_major ×
-- employee_band × prefecture × program-eligibility-chain) cohort cell.
-- The on-demand match path (POST /v1/cohort/5d/match) returns the cached
-- list verbatim instead of re-doing the 5-axis join against
-- `houjin_master` × 11,601 programs × eligibility chain.
--
-- Why precompute (not a runtime view)
-- -----------------------------------
-- * 5-axis Cartesian product is O(N×M×K×P×R) — pure-SQL evaluation per
--   request would scan `houjin_master` (~500k rows) × `programs` (~11.6k)
--   per call; precompute amortizes the cost to one daily pass.
-- * The MCP tool `match_cohort_5d_am` must return inside the FastMCP
--   1-second envelope to avoid client timeouts.
-- * Memory `feedback_no_quick_check_on_huge_sqlite` forbids full-scan ops
--   on the 9.7GB autonomath.db at runtime — precompute path is a single
--   daily job under a controlled budget.
--
-- Schema
-- ------
-- * cohort_id           — autoincrement PRIMARY KEY.
-- * houjin_bangou       — 13-digit 法人番号 (FK soft-ref to houjin_master).
--                         NULL for anonymous synthetic cohorts (caller
--                         passes only the band tuple, not a specific
--                         houjin).
-- * jsic_major          — 1-char JSIC major class (A-T).
-- * employee_band       — coarse size band: '1-9' / '10-99' / '100-999' /
--                         '1000+'. Bucketed at precompute time from the
--                         houjin_master corp size signal (when present).
-- * prefecture_code     — 2-digit zero-padded JIS code ('01' = 北海道
--                         .. '47' = 沖縄県). NULL = nationwide.
-- * eligible_program_ids — JSON array of program unified_id strings.
--                          Sorted by tier (S/A/B/C) then by amount_max DESC.
-- * eligible_count      — len(eligible_program_ids) materialized for
--                         O(1) cohort sparsity inspection.
-- * last_refreshed_at   — ISO-8601 UTC. Stale cohorts (> 24h) are
--                         re-evaluated by the next cron run.
--
-- The same cohort tuple may be re-emitted by the cron with an updated
-- eligible_program_ids set — INSERT OR REPLACE keyed on the unique tuple.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_cohort_5d (
    cohort_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou          TEXT,                                          -- soft FK; NULL = synthetic
    jsic_major             TEXT NOT NULL,                                  -- 'A'..'T'
    employee_band          TEXT NOT NULL,                                  -- band enum below
    prefecture_code        TEXT,                                            -- '01'..'47' OR NULL
    eligible_program_ids   TEXT NOT NULL DEFAULT '[]',                      -- JSON array
    eligible_count         INTEGER NOT NULL DEFAULT 0,
    last_refreshed_at      TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT ck_cohort_5d_band CHECK (employee_band IN (
        '1-9', '10-99', '100-999', '1000+'
    )),
    CONSTRAINT ck_cohort_5d_jsic CHECK (length(jsic_major) = 1),
    CONSTRAINT ck_cohort_5d_pref CHECK (prefecture_code IS NULL OR length(prefecture_code) = 2)
);

-- Primary hot-path index: matcher endpoint groups by (jsic, band, pref).
CREATE INDEX IF NOT EXISTS idx_cohort_5d_jbp
    ON am_cohort_5d(jsic_major, employee_band, prefecture_code);

-- Per-houjin reverse index for the houjin_360 surface (when a caller asks
-- "which cohorts include this houjin?").
CREATE INDEX IF NOT EXISTS idx_cohort_5d_houjin
    ON am_cohort_5d(houjin_bangou)
    WHERE houjin_bangou IS NOT NULL;

-- Staleness sweep: cron picks rows older than 24h.
CREATE INDEX IF NOT EXISTS idx_cohort_5d_refresh
    ON am_cohort_5d(last_refreshed_at);

-- Unique constraint on the cohort tuple. NULL-tolerant (houjin_bangou
-- NULL means "synthetic band cohort"; prefecture_code NULL means
-- "nationwide"). Used by INSERT OR REPLACE in the cron precompute.
CREATE UNIQUE INDEX IF NOT EXISTS ux_cohort_5d_tuple
    ON am_cohort_5d(
        COALESCE(houjin_bangou, '_synthetic'),
        jsic_major,
        employee_band,
        COALESCE(prefecture_code, '_nationwide')
    );

-- Operator dashboard view: top cohorts by eligible_count (which 5-axis
-- cells unlock the most programs). Useful for SEO landing-page generation.
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
