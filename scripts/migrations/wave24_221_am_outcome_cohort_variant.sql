-- target_db: autonomath
-- migration: wave24_221_am_outcome_cohort_variant
-- generated_at: 2026-05-17
-- author: GG7 — 432 outcome × 5 cohort variant fan-out (jpcite 2026-05-17)
-- idempotent: every CREATE uses IF NOT EXISTS; pure DDL, no DML.
--
-- Purpose
-- -------
-- Pre-compute the cohort-specific gloss + next-step + cohort-tier cost
-- saving for every (outcome × cohort) cell of the Wave 60-94 catalog
-- fan-out. 432 outcome × 5 cohort = 2,160 variant rows.
--
-- Each row supplies the cohort-specific viewpoint a 税理士 / 会計士 /
-- 行政書士 / 司法書士 / 中小経営者 needs when consuming the generic
-- Wave 60-94 outcome catalog. The MCP tool ``get_outcome_for_cohort``
-- reads this table directly so the cohort fan-out happens once at
-- pre-compute time, not per request (no LLM, no runtime persona).
--
-- Schema
-- ------
-- * variant_id              — autoincrement PRIMARY KEY.
-- * outcome_id              — Wave 60-94 catalog id (1..432).
-- * cohort                  — cohort enum (zeirishi / kaikeishi /
--                             gyouseishoshi / shihoshoshi / chusho_keieisha).
-- * gloss                   — 1-2 sentence cohort-specific viewpoint on
--                             the generic outcome (free Japanese text).
-- * next_step               — 1-2 sentence cohort-specific workflow step
--                             telling the persona how to fold the outcome
--                             into their daily 業務.
-- * cohort_saving_yen_per_query — integer ¥ saving per cohort query
--                             (cohort_tier_price vs Opus equivalent),
--                             derived deterministically from the FF1 SOT
--                             tier table.
-- * computed_at             — ISO-8601 UTC, producer-stamped.
--
-- Idempotency contract
-- --------------------
--   * UNIQUE (outcome_id, cohort) — re-running the generator for the
--     same (outcome, cohort) pair converges on the same row via
--     INSERT OR REPLACE on the unique index.
--   * All indexes are CREATE INDEX IF NOT EXISTS.
--
-- LLM call: 0. Producer = template rule-engine
-- (scripts/aws_credit_ops/generate_cohort_outcome_variants_2026_05_17.py).
-- Reader = SQLite SELECT only.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- am_outcome_cohort_variant — 432 outcome × 5 cohort variant fan-out
-- ============================================================================

CREATE TABLE IF NOT EXISTS am_outcome_cohort_variant (
    variant_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id                  INTEGER NOT NULL,
    cohort                      TEXT NOT NULL,
    gloss                       TEXT NOT NULL,
    next_step                   TEXT NOT NULL,
    cohort_saving_yen_per_query INTEGER NOT NULL,
    computed_at                 TEXT NOT NULL,
    CONSTRAINT ck_outcome_cohort_variant_cohort CHECK (cohort IN (
        'zeirishi',
        'kaikeishi',
        'gyouseishoshi',
        'shihoshoshi',
        'chusho_keieisha'
    )),
    CONSTRAINT ck_outcome_cohort_variant_outcome_id CHECK (
        outcome_id >= 1 AND outcome_id <= 432
    ),
    CONSTRAINT ck_outcome_cohort_variant_saving_positive CHECK (
        cohort_saving_yen_per_query >= 0
    )
);

-- Unique constraint on (outcome_id, cohort) — INSERT OR REPLACE-keyed.
CREATE UNIQUE INDEX IF NOT EXISTS ux_outcome_cohort_variant_tuple
    ON am_outcome_cohort_variant(outcome_id, cohort);

-- Forward lookup: get all 5 cohort variants for one outcome.
CREATE INDEX IF NOT EXISTS ix_outcome_cohort_variant_outcome_id
    ON am_outcome_cohort_variant(outcome_id);

-- Reverse lookup: get all 432 outcomes for one cohort.
CREATE INDEX IF NOT EXISTS ix_outcome_cohort_variant_cohort
    ON am_outcome_cohort_variant(cohort);

-- Freshness sweep: prune stale rows older than 24h.
CREATE INDEX IF NOT EXISTS ix_outcome_cohort_variant_computed_at
    ON am_outcome_cohort_variant(computed_at);

-- Operator dashboard view: per-cohort total saving aggregation.
DROP VIEW IF EXISTS v_outcome_cohort_variant_top;
CREATE VIEW v_outcome_cohort_variant_top AS
SELECT
    cohort,
    COUNT(*) AS variant_rows,
    SUM(cohort_saving_yen_per_query) AS sum_saving_yen,
    AVG(cohort_saving_yen_per_query) AS avg_saving_yen,
    MAX(cohort_saving_yen_per_query) AS max_saving_yen
FROM am_outcome_cohort_variant
GROUP BY cohort
ORDER BY avg_saving_yen DESC;
