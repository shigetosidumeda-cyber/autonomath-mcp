-- target_db: autonomath
-- migration: 237_am_subsidy_30yr_forecast
-- generated_at: 2026-05-12
-- author: Wave 34 Axis 4c — 30 yr forecast model per program
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- 30-year × 12-month Markov chain transition matrix per program.
-- forecast_program_renewal (Wave 22) × am_application_round (1,256 rows)
-- + am_amendment_snapshot (14,596 rows) で 30 yr 先まで P(state).
--
-- Markov state: {active, paused, sunset, renewed}.
-- 11,601 programs × 360 月 = ~4.18M max rows; tier S/A/B/C のみ persist。

PRAGMA foreign_keys = OFF;

BEGIN;

CREATE TABLE IF NOT EXISTS am_subsidy_30yr_forecast (
    program_unified_id TEXT NOT NULL,
    forecast_year_offset INTEGER NOT NULL CHECK (forecast_year_offset BETWEEN 0 AND 29),
    horizon_month INTEGER NOT NULL CHECK (horizon_month BETWEEN 0 AND 11),
    state TEXT NOT NULL CHECK (state IN ('active','paused','sunset','renewed')),
    p_active REAL NOT NULL DEFAULT 0 CHECK (p_active BETWEEN 0 AND 1),
    p_paused REAL NOT NULL DEFAULT 0 CHECK (p_paused BETWEEN 0 AND 1),
    p_sunset REAL NOT NULL DEFAULT 0 CHECK (p_sunset BETWEEN 0 AND 1),
    p_renewed REAL NOT NULL DEFAULT 0 CHECK (p_renewed BETWEEN 0 AND 1),
    expected_call_count REAL NOT NULL DEFAULT 0,
    program_tier TEXT,
    refreshed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (program_unified_id, forecast_year_offset, horizon_month)
);

CREATE INDEX IF NOT EXISTS idx_am_subsidy_30yr_forecast_program
    ON am_subsidy_30yr_forecast(program_unified_id, forecast_year_offset);

CREATE INDEX IF NOT EXISTS idx_am_subsidy_30yr_forecast_year
    ON am_subsidy_30yr_forecast(forecast_year_offset, horizon_month, p_active DESC);

CREATE INDEX IF NOT EXISTS idx_am_subsidy_30yr_forecast_refreshed
    ON am_subsidy_30yr_forecast(refreshed_at);

CREATE TABLE IF NOT EXISTS am_subsidy_30yr_forecast_refresh_log (
    refresh_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    programs_processed INTEGER NOT NULL DEFAULT 0,
    rows_written INTEGER NOT NULL DEFAULT 0,
    skipped_no_round_data INTEGER NOT NULL DEFAULT 0,
    error_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_am_subsidy_30yr_forecast_refresh_log_started
    ON am_subsidy_30yr_forecast_refresh_log(started_at DESC);

COMMIT;
