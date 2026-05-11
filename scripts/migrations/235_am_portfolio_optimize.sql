-- target_db: autonomath
-- migration: 235_am_portfolio_optimize
-- generated_at: 2026-05-12
-- author: Wave 34 Axis 4a — daily precomputed portfolio_optimize per houjin
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Purpose
-- -------
-- houjin (法人) ごとに「最適 8 制度」を毎日 precompute する store。
-- composition_tools.simulate_application_am は 1 件ごと SQL JOIN するため、
-- 顧問先 fan-out (税理士 1 人 × N 顧問先) では request-time コストが N に比例。
-- 本 store は houjin × top-N を offline で固定し、API/MCP は単純 SELECT のみ。
--
-- 入力 axes (refresh_portfolio_optimize_daily.py が join):
--   * houjin_master.business_law_axis (8 業法)
--   * houjin_master.jsic_major + medium (23 業種)
--   * eligibility_chain (am_program_eligibility_predicate / am_compat_matrix)
--   * 11,601 searchable programs (jpi_programs)
--   * adoption pattern (jpi_adoption_records 201,845 rows)
--   * application_window (am_application_round 1,256 rows)
--
-- Score
-- -----
-- 0-100 composite (重み):
--   * 0.25 eligibility_pass    — am_program_eligibility_predicate match
--   * 0.20 amount_band_fit     — houjin の adoption history vs program amount
--   * 0.15 jsic_alignment      — 業種 major+medium 一致
--   * 0.15 region_match        — prefecture or 全国
--   * 0.10 compat_with_others  — am_compat_matrix で他制度と compatible
--   * 0.10 application_window  — am_application_round で 60d 以内 open
--   * 0.05 freshness           — am_amendment_diff で 90d 以内 修正

PRAGMA foreign_keys = OFF;

BEGIN;

CREATE TABLE IF NOT EXISTS am_portfolio_optimize (
    houjin_bangou TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank BETWEEN 1 AND 8),
    program_unified_id TEXT NOT NULL,
    program_primary_name TEXT,
    score_0_100 INTEGER NOT NULL CHECK (score_0_100 BETWEEN 0 AND 100),
    eligibility_pass_score REAL NOT NULL DEFAULT 0,
    amount_band_fit_score REAL NOT NULL DEFAULT 0,
    jsic_alignment_score REAL NOT NULL DEFAULT 0,
    region_match_score REAL NOT NULL DEFAULT 0,
    compat_with_others_score REAL NOT NULL DEFAULT 0,
    application_window_score REAL NOT NULL DEFAULT 0,
    freshness_score REAL NOT NULL DEFAULT 0,
    reason_json TEXT,
    tier TEXT,
    program_amount_max_yen INTEGER,
    application_close_date TEXT,
    refreshed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (houjin_bangou, rank)
);

CREATE INDEX IF NOT EXISTS idx_am_portfolio_optimize_score
    ON am_portfolio_optimize(score_0_100 DESC, houjin_bangou);

CREATE INDEX IF NOT EXISTS idx_am_portfolio_optimize_program
    ON am_portfolio_optimize(program_unified_id, score_0_100 DESC);

CREATE INDEX IF NOT EXISTS idx_am_portfolio_optimize_refreshed
    ON am_portfolio_optimize(refreshed_at);

CREATE TABLE IF NOT EXISTS am_portfolio_optimize_refresh_log (
    refresh_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    houjin_count INTEGER NOT NULL DEFAULT 0,
    program_pairs_written INTEGER NOT NULL DEFAULT 0,
    skipped_no_data INTEGER NOT NULL DEFAULT 0,
    error_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_am_portfolio_optimize_refresh_log_started
    ON am_portfolio_optimize_refresh_log(started_at DESC);

COMMIT;
