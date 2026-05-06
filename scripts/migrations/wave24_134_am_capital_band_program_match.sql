-- target_db: autonomath
-- migration wave24_134_am_capital_band_program_match (MASTER_PLAN_v1
-- 章 10.2.9 — 資本金帯 × 採択統計マッチ)
--
-- Why this exists:
--   `match_programs_by_capital` (#105) and
--   `score_application_probability` (#112) both need a fast
--   lookup of "given a capital_yen value, which programs have
--   the strongest historical adoption signal at this capital
--   band". We bucket capital into the 9 bands NTA standard uses
--   and pre-aggregate per (capital_band × program).
--
-- Schema:
--   * capital_band TEXT NOT NULL CHECK (capital_band IN (
--          'under_1m','1m_to_3m','3m_to_5m','5m_to_10m',
--          '10m_to_50m','50m_to_100m','100m_to_300m',
--          '300m_to_1b','1b_plus'))
--   * program_unified_id TEXT NOT NULL
--   * adoption_count INTEGER NOT NULL DEFAULT 0
--   * adoption_rate REAL                     — 0..1 (count / applicants)
--   * avg_amount_man_yen REAL
--   * percentile_in_band REAL                — 0..1, this program vs others in same band
--   * sample_size INTEGER NOT NULL DEFAULT 0 — denominator for the rate
--   * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--   * UNIQUE (capital_band, program_unified_id)
--
--   The capital_band enum mirrors `am_target_profile` band labels
--   for cross-table joinability.
--
-- Indexes:
--   * (capital_band, percentile_in_band DESC) — top-N within a band.
--   * (program_unified_id) — reverse "which bands favor program X".
--
-- Idempotency:
--   CREATE * IF NOT EXISTS, INSERT OR REPLACE under UNIQUE.
--
-- DOWN:
--   See companion `wave24_134_am_capital_band_program_match_rollback.sql`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_capital_band_program_match (
    match_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    capital_band         TEXT NOT NULL CHECK (capital_band IN (
                            'under_1m','1m_to_3m','3m_to_5m','5m_to_10m',
                            '10m_to_50m','50m_to_100m','100m_to_300m',
                            '300m_to_1b','1b_plus'
                         )),
    program_unified_id   TEXT NOT NULL,
    adoption_count       INTEGER NOT NULL DEFAULT 0,
    adoption_rate        REAL CHECK (adoption_rate IS NULL OR
                                     (adoption_rate >= 0.0 AND adoption_rate <= 1.0)),
    avg_amount_man_yen   REAL,
    percentile_in_band   REAL CHECK (percentile_in_band IS NULL OR
                                     (percentile_in_band >= 0.0 AND percentile_in_band <= 1.0)),
    sample_size          INTEGER NOT NULL DEFAULT 0,
    computed_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (capital_band, program_unified_id)
);

CREATE INDEX IF NOT EXISTS idx_acbpm_band_pct
    ON am_capital_band_program_match(capital_band, percentile_in_band DESC);

CREATE INDEX IF NOT EXISTS idx_acbpm_program
    ON am_capital_band_program_match(program_unified_id);
