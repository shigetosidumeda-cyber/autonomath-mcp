-- target_db: autonomath
-- migration: 236_am_houjin_risk_score
-- generated_at: 2026-05-12
-- author: Wave 34 Axis 4b — daily refreshed 0-100 risk score per houjin
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Purpose
-- -------
-- 法人 (houjin_master ~166,969 rows in am_entities) ごとに 0-100 の
-- 与信 + コンプラ + 採択 取消 + 行政処分 composite risk score を daily で固定。
-- request-time に am_enforcement_detail 22,258 + jpi_adoption_records 201,845
-- 全 walk すると O(N) overhead。本 store は 0-100 まで畳んで O(1) read。
--
-- Score composition (合計 100)
-- ----------------------------
--   * 0..40  行政処分 signal
--   * 0..30  invoice 取消 signal
--   * 0..15  採択取消 signal
--   * 0..15  与信 / 業歴 signal

PRAGMA foreign_keys = OFF;

BEGIN;

CREATE TABLE IF NOT EXISTS am_houjin_risk_score (
    houjin_bangou TEXT NOT NULL PRIMARY KEY,
    risk_score_0_100 INTEGER NOT NULL CHECK (risk_score_0_100 BETWEEN 0 AND 100),
    enforcement_subscore INTEGER NOT NULL DEFAULT 0 CHECK (enforcement_subscore BETWEEN 0 AND 40),
    invoice_subscore INTEGER NOT NULL DEFAULT 0 CHECK (invoice_subscore BETWEEN 0 AND 30),
    adoption_subscore INTEGER NOT NULL DEFAULT 0 CHECK (adoption_subscore BETWEEN 0 AND 15),
    credit_age_subscore INTEGER NOT NULL DEFAULT 0 CHECK (credit_age_subscore BETWEEN 0 AND 15),
    risk_bucket TEXT NOT NULL DEFAULT 'low' CHECK (risk_bucket IN ('low','medium','high','critical')),
    signals_json TEXT,
    enforcement_count_5y INTEGER NOT NULL DEFAULT 0,
    invoice_status TEXT,
    adoption_revoked_count INTEGER NOT NULL DEFAULT 0,
    established_year INTEGER,
    refreshed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_am_houjin_risk_score_desc
    ON am_houjin_risk_score(risk_score_0_100 DESC, houjin_bangou);

CREATE INDEX IF NOT EXISTS idx_am_houjin_risk_score_bucket
    ON am_houjin_risk_score(risk_bucket, risk_score_0_100 DESC);

CREATE INDEX IF NOT EXISTS idx_am_houjin_risk_score_refreshed
    ON am_houjin_risk_score(refreshed_at);

CREATE TABLE IF NOT EXISTS am_houjin_risk_score_refresh_log (
    refresh_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    houjin_count INTEGER NOT NULL DEFAULT 0,
    high_risk_count INTEGER NOT NULL DEFAULT 0,
    critical_risk_count INTEGER NOT NULL DEFAULT 0,
    error_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_am_houjin_risk_score_refresh_log_started
    ON am_houjin_risk_score_refresh_log(started_at DESC);

COMMIT;
