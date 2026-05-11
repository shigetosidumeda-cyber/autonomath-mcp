-- migration 220_jpi_user_export_log
-- target_db: jpintel
-- generated_at: 2026-05-11
-- author: Wave 20 B5/C7 #5 (CSV/PDF export 監査)
--
-- Purpose
-- -------
-- Wave 21 added per-顧問先 CSV / PDF export flows under
-- `/v1/me/exports/{format}`. Every export is a potential leak vector
-- (PII / 顧問先 financial signals), so we audit-log:
--
--   - Who exported (key_hash)
--   - What format (csv / pdf / json / xlsx)
--   - Which dataset (programs / cases / loans / tax_rules / mixed)
--   - How many rows
--   - The filter signature (sha256 of the query JSON)
--
-- This table is **append-only** — there is no UPDATE / DELETE surface.
-- The audit-log retention is 5 years (規程 §12.3, 税理士法 §41).
--
-- Why a separate table from `jpi_user_search_history`
-- ----------------------------------------------------
-- - Different retention (5y vs 90d).
-- - Different read-side (operator / auditor vs end-user dashboard).
-- - Different write rate (exports are < 1% of searches).
-- - Different schema (file_size_bytes, format, export_status).
--
-- Surface contract
-- ----------------
-- - REST: NO public list endpoint. Operator-only via
--   `scripts/ops/audit_export_query.py`.
-- - Audit log: shipped to S3 archive nightly via
--   `scripts/cron/ship_export_audit.py` (NEW).
-- - Sensitive (§52 / GDPR Art 30): retention contract documented in
--   /privacy and /security.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS jpi_user_export_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash        TEXT    NOT NULL,
    export_format   TEXT    NOT NULL,                        -- 'csv' | 'pdf' | 'json' | 'xlsx'
    dataset         TEXT    NOT NULL,                        -- 'programs' | 'cases' | etc.
    row_count       INTEGER NOT NULL DEFAULT 0,
    file_size_bytes INTEGER,                                 -- on-disk size of generated file
    query_digest    TEXT,                                    -- sha256 of normalized query JSON
    started_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT,
    export_status   TEXT    NOT NULL DEFAULT 'started',      -- 'started' | 'completed' | 'failed' | 'cancelled'
    error_class     TEXT,                                    -- exception class name on failure
    -- The user-facing filename. Captured so an auditor can correlate
    -- "the file I received" with "this row" — Stripe-style receipt audit.
    artifact_name   TEXT,
    -- Source IP / UA captured here (NOT in search_history) because the
    -- export surface is the export surface — leaks are forensically
    -- traced by IP, and the audit-log obligation > the search privacy
    -- minimization principle.
    src_ip          TEXT,
    user_agent      TEXT,
    CONSTRAINT ck_export_format CHECK (export_format IN ('csv', 'pdf', 'json', 'xlsx', 'parquet')),
    CONSTRAINT ck_export_status CHECK (export_status IN ('started', 'completed', 'failed', 'cancelled'))
);

-- Per-key audit access ("show me everything user X exported").
CREATE INDEX IF NOT EXISTS idx_jpi_export_log_key
    ON jpi_user_export_log(key_hash, started_at DESC);

-- Time-window audit access ("everything exported on date X").
CREATE INDEX IF NOT EXISTS idx_jpi_export_log_time
    ON jpi_user_export_log(started_at DESC);

-- Failure triage index.
CREATE INDEX IF NOT EXISTS idx_jpi_export_log_failed
    ON jpi_user_export_log(started_at DESC)
    WHERE export_status = 'failed';

-- View: completed exports only, ordered for the operator audit report.
DROP VIEW IF EXISTS v_jpi_export_log_completed;
CREATE VIEW v_jpi_export_log_completed AS
SELECT
    id,
    key_hash,
    export_format,
    dataset,
    row_count,
    file_size_bytes,
    started_at,
    completed_at,
    artifact_name
FROM jpi_user_export_log
WHERE export_status = 'completed';
