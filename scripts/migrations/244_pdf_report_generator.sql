-- target_db: autonomath
-- migration: 244_pdf_report_generator
-- generated_at: 2026-05-12
-- author: Wave 35 Axis 6a — 顧問先別月次 PDF 報告書 generator subscriptions
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Backs the `POST /v1/pdf_report/generate` endpoint + the monthly cron in
-- `scripts/cron/generate_pdf_reports_monthly.py`.
--
-- Memory references
-- -----------------
-- * feedback_no_operator_llm_api : the PDF generator is pure reportlab — no
--   LLM call site touches this table.
-- * feedback_zero_touch_solo : subscription rows are operator-managed via
--   REST + dashboard; no admin UI is required.

PRAGMA foreign_keys = OFF;

BEGIN;

-- One row per (client_id × cadence). `client_id` aligns with the
-- `client_profiles.client_id` master from migration 096; the cadence column
-- lets the same client subscribe to both monthly + quarterly cycles
-- without a JOIN explosion.
CREATE TABLE IF NOT EXISTS am_pdf_report_subscriptions (
    subscription_id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    customer_id TEXT,
    cadence TEXT NOT NULL CHECK (cadence IN ('monthly','quarterly','annual')),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    -- Template token expansion at runtime — e.g. `{client_id}/{yyyymm}.pdf`.
    r2_url_template TEXT NOT NULL DEFAULT 'pdf_reports/{client_id}/{yyyymm}.pdf',
    last_generated_at TEXT,
    last_generated_r2_key TEXT,
    last_generated_byte_size INTEGER,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Hot path: monthly cron walks `enabled=1 AND cadence='monthly'`.
CREATE INDEX IF NOT EXISTS idx_am_pdf_report_subscriptions_enabled_cadence
    ON am_pdf_report_subscriptions(enabled, cadence, last_generated_at);

-- Quick lookup by client.
CREATE INDEX IF NOT EXISTS idx_am_pdf_report_subscriptions_client
    ON am_pdf_report_subscriptions(client_id, enabled);

-- Run log — one row per cron invocation, append-only for audit.
CREATE TABLE IF NOT EXISTS am_pdf_report_generation_log (
    log_id TEXT PRIMARY KEY,
    subscription_id TEXT,
    client_id TEXT NOT NULL,
    cadence TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    success INTEGER NOT NULL DEFAULT 0 CHECK (success IN (0,1)),
    r2_key TEXT,
    byte_size INTEGER,
    page_count INTEGER,
    error_text TEXT,
    billing_units INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_am_pdf_report_generation_log_client_started
    ON am_pdf_report_generation_log(client_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_pdf_report_generation_log_started
    ON am_pdf_report_generation_log(started_at DESC);

COMMIT;
