-- target_db: autonomath
-- migration: 246_credit_signal
-- generated_at: 2026-05-12
-- author: Wave 41 Axis 7b — 与信スコア modeling (一次資料のみ、ML 無し)
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Purpose
-- -------
-- Aggregate credit-relevant signals per 法人番号 into a single rule-based
-- score 0-100, sourced from EXISTING primary-source corpora — no ML, no
-- LLM, no third-party score provider. Every signal must be traceable to
-- a row in:
--
--   * am_enforcement_detail (22,258 rows) — 行政処分 cases.
--   * invoice_registrants   (13,801 rows) — 適格事業者 取消 events.
--   * adoption_records / jpi_adoption_records — 採択取消 events.
--   * court_decisions       — 判決確定 倒産 / 民再 / 会更.
--
-- Memory `feedback_no_operator_llm_api` is strict: ZERO LLM calls in
-- aggregation. Rule-based score in `scripts/cron/aggregate_credit_signal_daily.py`
-- uses only stdlib + sqlite3.
--
-- Schema notes
-- ------------
-- * signal_id   — autoincrement PRIMARY KEY.
-- * houjin_bangou — 13-digit 法人番号. Required.
-- * signal_type — closed enum (CHECK below):
--     - 'enforcement'          行政処分 hit (program_subsidy_exclude / 命令 etc.)
--     - 'refund'               補助金返還命令
--     - 'invoice_revoked'      適格事業者 登録取消
--     - 'late_payment'         保険料滞納公表 / 税金滞納公表
--     - 'court_judgment'       倒産確定 / 民再 / 会更
--     - 'subsidy_revoked'      採択取消 / 中止 確定
--     - 'sanction_extension'   制裁 期間 延長
-- * signal_date   — yyyy-mm-dd, source row date.
-- * severity      — 0..100 numeric. 0 = informational, 100 = catastrophic.
-- * source_url    — 一次資料 URL (mandatory — no aggregator).
-- * source_kind   — debug enum (ministry / NTA / courts.go.jp / METI etc.).
--
-- Aggregation surface
-- -------------------
-- Daily cron computes `am_credit_signal_aggregate` per houjin: signal
-- count + max severity + summed-weighted score. NULL houjin signals are
-- discarded at write time.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_credit_signal (
    signal_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    houjin_bangou   TEXT NOT NULL,
    signal_type     TEXT NOT NULL,
    signal_date     TEXT,
    severity        INTEGER NOT NULL DEFAULT 0,
    source_url      TEXT,
    source_kind     TEXT,
    evidence_text   TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT ck_credit_signal_houjin_len CHECK (length(houjin_bangou) = 13),
    CONSTRAINT ck_credit_signal_severity CHECK (severity BETWEEN 0 AND 100),
    CONSTRAINT ck_credit_signal_type CHECK (signal_type IN (
        'enforcement',
        'refund',
        'invoice_revoked',
        'late_payment',
        'court_judgment',
        'subsidy_revoked',
        'sanction_extension'
    ))
);

CREATE INDEX IF NOT EXISTS idx_am_credit_signal_houjin
    ON am_credit_signal(houjin_bangou, signal_date DESC);

CREATE INDEX IF NOT EXISTS idx_am_credit_signal_type
    ON am_credit_signal(signal_type, signal_date DESC);

CREATE INDEX IF NOT EXISTS idx_am_credit_signal_severity
    ON am_credit_signal(severity DESC, houjin_bangou);

CREATE UNIQUE INDEX IF NOT EXISTS ux_am_credit_signal_dedupe
    ON am_credit_signal(
        houjin_bangou,
        signal_type,
        COALESCE(signal_date, '_undated'),
        COALESCE(source_url, '_no_url')
    );

-- Per-houjin aggregate. INSERT OR REPLACE by cron daily.
CREATE TABLE IF NOT EXISTS am_credit_signal_aggregate (
    houjin_bangou        TEXT PRIMARY KEY,
    signal_count         INTEGER NOT NULL DEFAULT 0,
    max_severity         INTEGER NOT NULL DEFAULT 0,
    rule_based_score     INTEGER NOT NULL DEFAULT 0,
    last_signal_date     TEXT,
    refreshed_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    type_breakdown_json  TEXT,
    CONSTRAINT ck_credit_signal_agg_houjin_len CHECK (length(houjin_bangou) = 13),
    CONSTRAINT ck_credit_signal_agg_score CHECK (rule_based_score BETWEEN 0 AND 100),
    CONSTRAINT ck_credit_signal_agg_severity CHECK (max_severity BETWEEN 0 AND 100)
);

CREATE INDEX IF NOT EXISTS idx_am_credit_signal_agg_score
    ON am_credit_signal_aggregate(rule_based_score DESC, houjin_bangou);

CREATE INDEX IF NOT EXISTS idx_am_credit_signal_agg_refreshed
    ON am_credit_signal_aggregate(refreshed_at);

-- Cron run log
CREATE TABLE IF NOT EXISTS am_credit_signal_run_log (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    signals_seen    INTEGER NOT NULL DEFAULT 0,
    houjin_aggregated INTEGER NOT NULL DEFAULT 0,
    error_text      TEXT
);

CREATE INDEX IF NOT EXISTS idx_am_credit_signal_run_log_started
    ON am_credit_signal_run_log(started_at DESC);

-- Operator dashboard: top houjin by rule_based_score (worst credit).
DROP VIEW IF EXISTS v_credit_signal_worst;
CREATE VIEW v_credit_signal_worst AS
SELECT
    houjin_bangou,
    signal_count,
    max_severity,
    rule_based_score,
    last_signal_date,
    refreshed_at
FROM am_credit_signal_aggregate
WHERE rule_based_score > 0
ORDER BY rule_based_score DESC, signal_count DESC, houjin_bangou ASC;

COMMIT;
