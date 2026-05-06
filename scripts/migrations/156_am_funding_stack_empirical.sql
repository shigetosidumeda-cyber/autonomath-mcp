-- target_db: autonomath
-- migration 156_am_funding_stack_empirical
--
-- Why this exists (Wave 25 empirical compat-matrix complement, 2026-05-05):
--   `am_compat_matrix` (43,966 rows: 4,300 sourced + heuristic with
--   inferred_only=1) is rule-based — it tells us what *should* be
--   compatible by published exclusion text. It does NOT tell us what
--   beneficiaries actually combined.
--
--   `jpi_adoption_records` (201,845 rows; 81,218 program-resolved
--   across 65,102 distinct houjin_bangou) is the ground truth: when
--   the same houjin shows up in two programs, those two programs
--   *were* stacked in practice — regardless of what the matrix says.
--
--   This migration creates `am_funding_stack_empirical` to crystalize
--   that signal as a (program_a, program_b) co-adoption table, joined
--   against the matrix to surface honest gaps:
--     - mined says co-adopt, matrix says 'incompatible'  -> conflict_flag=1
--       (exclusion-rule false positive: the rule blocks a combo that
--        the corpus shows actually happened)
--
--   Surface use-case:
--     1. Recommendation strength: if combo (A,B) has co_adoption_count
--        >= 5, prefer it over matrix-only co-recommendations.
--     2. Exclusion-rule audit: conflict_flag=1 rows are honest gaps in
--        our scraped exclusion text — they need human re-read of the
--        source PDF.
--
-- Schema:
--   program_a_id < program_b_id  (CHECK; normalize ordering, dedupe AB/BA)
--   co_adoption_count            INTEGER, count of distinct houjin
--                                that adopted BOTH A and B.
--   mean_days_between            INTEGER, avg |days| between A's and
--                                B's announced_at per houjin. NULL if
--                                announced_at missing on either side.
--   compat_matrix_says           TEXT, snapshot of am_compat_matrix
--                                .compat_status at populate time
--                                ('compatible' / 'incompatible' /
--                                 'case_by_case' / 'unknown' / NULL if
--                                 the pair has no matrix row at all).
--                                Stored verbatim (not normalized to
--                                'allowed' / 'excluded') so audit
--                                trace stays 1:1 with am_compat_matrix.
--   conflict_flag                INTEGER 0/1; 1 iff
--                                compat_matrix_says='incompatible'
--                                AND co_adoption_count >= 1.
--                                Computed at populate time, NOT a
--                                generated column (SQLite generated
--                                cols + ATTACH-less self-join in
--                                INSERT…SELECT have edge cases).
--
-- Populator (this migration body):
--   1. Self-join jpi_adoption_records on houjin_bangou where both
--      sides have program_id resolved and houjin not blank.
--   2. GROUP BY normalized (LEAST, GREATEST) program_id pair.
--   3. Filter co_adoption_count >= 5 (cohort signal-strength floor;
--      below 5 the empirical signal is anecdotal).
--   4. LEFT JOIN am_compat_matrix on the same normalized pair to
--      stamp compat_matrix_says (matrix is also normalized via the
--      CHECK in migration 049's am_compat_matrix DDL — both columns
--      ordered alphabetically).
--   5. Compute conflict_flag in a follow-up UPDATE.
--
-- NON-LLM:
--   Pure SQL self-join + aggregate. No Python ETL, no LLM.
--
-- Idempotency:
--   CREATE TABLE IF NOT EXISTS. Populator uses INSERT OR REPLACE on
--   PRIMARY KEY so re-runs overwrite cleanly. CREATE INDEX uses
--   IF NOT EXISTS.
--
-- DOWN:
--   companion `156_am_funding_stack_empirical_rollback.sql`.

PRAGMA foreign_keys = ON;

-- 1. Table.
CREATE TABLE IF NOT EXISTS am_funding_stack_empirical (
    program_a_id        TEXT NOT NULL,
    program_b_id        TEXT NOT NULL,
    co_adoption_count   INTEGER NOT NULL DEFAULT 0,
    mean_days_between   INTEGER,
    compat_matrix_says  TEXT,
    conflict_flag       INTEGER NOT NULL DEFAULT 0,
    generated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (program_a_id, program_b_id),
    CHECK (program_a_id < program_b_id)
);

CREATE INDEX IF NOT EXISTS ix_funding_stack_count
    ON am_funding_stack_empirical(co_adoption_count DESC);

CREATE INDEX IF NOT EXISTS ix_funding_stack_conflict
    ON am_funding_stack_empirical(conflict_flag)
 WHERE conflict_flag = 1;

-- 2. Populate. INSERT OR REPLACE keeps re-runs idempotent on the PK.
--    Self-join on houjin_bangou; restrict to resolved program_id rows;
--    normalize ordering with MIN/MAX so (A,B) and (B,A) collapse.
INSERT OR REPLACE INTO am_funding_stack_empirical
    (program_a_id, program_b_id, co_adoption_count,
     mean_days_between, compat_matrix_says, conflict_flag, generated_at)
SELECT
    pair.program_a_id,
    pair.program_b_id,
    pair.co_adoption_count,
    pair.mean_days_between,
    cm.compat_status AS compat_matrix_says,
    CASE
        WHEN cm.compat_status = 'incompatible' AND pair.co_adoption_count >= 1
        THEN 1 ELSE 0
    END AS conflict_flag,
    datetime('now')
  FROM (
    SELECT
        MIN(a.program_id, b.program_id) AS program_a_id,
        MAX(a.program_id, b.program_id) AS program_b_id,
        COUNT(DISTINCT a.houjin_bangou) AS co_adoption_count,
        CAST(
            AVG(
                ABS(
                    julianday(b.announced_at) - julianday(a.announced_at)
                )
            ) AS INTEGER
        ) AS mean_days_between
      FROM jpi_adoption_records a
      JOIN jpi_adoption_records b
        ON a.houjin_bangou = b.houjin_bangou
       AND a.program_id  < b.program_id
     WHERE a.program_id   IS NOT NULL AND a.program_id   != ''
       AND b.program_id   IS NOT NULL AND b.program_id   != ''
       AND a.houjin_bangou IS NOT NULL AND a.houjin_bangou != ''
     GROUP BY MIN(a.program_id, b.program_id),
              MAX(a.program_id, b.program_id)
    HAVING COUNT(DISTINCT a.houjin_bangou) >= 5
  ) pair
  LEFT JOIN am_compat_matrix cm
    ON cm.program_a_id = pair.program_a_id
   AND cm.program_b_id = pair.program_b_id;

-- Bookkeeping is recorded by entrypoint.sh §4 / scripts/migrate.py.
