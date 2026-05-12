-- target_db: autonomath
-- migration: 277_time_machine
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim Q (time_machine + counterfactual) storage layer
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Storage substrate for the Dim Q "regulatory time machine + counterfactual"
-- surface (per feedback_time_machine_query_design.md). Pairs with the
-- existing index-only mig wave24_180_time_machine_index.sql (which optimises
-- am_amendment_snapshot.effective_from lookups) by adding the *operational*
-- audit layer:
--
--   * am_monthly_snapshot_log: book-keeping for the monthly snapshot batch
--     (scripts/etl/build_monthly_snapshot.py). One row per
--     (snapshot_id, table_name) tuple: as_of_date, row_count, sha256 of
--     the canonical row digest. 5-year retention (60 snapshot windows).
--
--   * am_counterfactual_eval_log: append-only audit for
--     am_evaluate_counterfactual / am_query_as_of tool calls. Records the
--     as_of_date the call resolved against, the counterfactual_input
--     envelope (PII-stripped JSON, capped 8 KiB), and the result_diff
--     (JSON describing which fields flipped vs the live evaluation).
--
-- Why TWO tables (not one)
-- ------------------------
-- am_monthly_snapshot_log is write-once-per-month, ~12 rows/month, queried
-- by as_of_date for "does a snapshot for 2024-06-01 exist?" lookups.
-- am_counterfactual_eval_log is append-only per request, grows with
-- traffic; indexed by as_of_date for billing reconciliation and by
-- eval_id for forensic replay. Merging would force a scan of every
-- counterfactual on every as_of probe.
--
-- 5-year retention discipline
-- ---------------------------
-- 60 monthly snapshots (2021-04 .. 2026-05 baseline) per
-- feedback_time_machine_query_design. The retention sweeper lives in the
-- ETL (build_monthly_snapshot.py --gc); the migration only defines the
-- table shape — no DML.
--
-- ¥3/req billing posture
-- ----------------------
-- /v1/query?as_of=YYYY-MM-DD and /v1/evaluate/counterfactual each remain
-- 1 metered unit per call. The audit row is server-side overhead, not a
-- customer-facing read path; the table is operator-internal.
--
-- Scope (this migration only)
-- ---------------------------
-- Schema only. NO actual snapshot data is inserted by 277. The monthly
-- batch (scripts/etl/build_monthly_snapshot.py) backfills 60 months on
-- first run; 277 just provides the audit/log surface so the batch is
-- idempotent and replayable.
--
-- §52 / §47条の2 / §72 / §1 disclaimer parity is enforced by the REST
-- surface envelope (_disclaimer field), not at the SQL layer.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_monthly_snapshot_log (
    snapshot_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of_date        TEXT NOT NULL,                        -- YYYY-MM-DD (first of month, UTC)
    table_name        TEXT NOT NULL,                        -- snapshotted table (e.g. am_amendment_snapshot)
    row_count         INTEGER NOT NULL DEFAULT 0
                      CHECK (row_count >= 0),
    sha256            TEXT NOT NULL,                        -- canonical hex digest of ordered rows
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (as_of_date, table_name),
    CHECK (length(as_of_date) = 10),                        -- YYYY-MM-DD (10 chars)
    CHECK (length(sha256) = 64)                             -- sha256 hex
);

CREATE INDEX IF NOT EXISTS idx_am_monthly_snapshot_log_as_of
    ON am_monthly_snapshot_log(as_of_date);

CREATE INDEX IF NOT EXISTS idx_am_monthly_snapshot_log_table
    ON am_monthly_snapshot_log(table_name, as_of_date DESC);

-- Helper view: most recent snapshot per table.
DROP VIEW IF EXISTS v_monthly_snapshot_latest;
CREATE VIEW v_monthly_snapshot_latest AS
SELECT
    table_name,
    MAX(as_of_date) AS latest_as_of,
    SUM(row_count)  AS lifetime_rows
FROM am_monthly_snapshot_log
GROUP BY table_name;

-- Append-only counterfactual eval audit log.
CREATE TABLE IF NOT EXISTS am_counterfactual_eval_log (
    eval_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of_date           TEXT NOT NULL,                     -- YYYY-MM-DD the call resolved against
    query                TEXT NOT NULL,                     -- canonical query identifier (slug or hash)
    counterfactual_input TEXT NOT NULL DEFAULT '{}',        -- JSON envelope, <= 8 KiB
    result_diff          TEXT NOT NULL DEFAULT '{}',        -- JSON of flipped fields, <= 8 KiB
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (length(as_of_date) = 10),
    CHECK (length(counterfactual_input) <= 8192),
    CHECK (length(result_diff) <= 8192)
);

CREATE INDEX IF NOT EXISTS idx_am_counterfactual_eval_log_as_of
    ON am_counterfactual_eval_log(as_of_date);

CREATE INDEX IF NOT EXISTS idx_am_counterfactual_eval_log_created
    ON am_counterfactual_eval_log(created_at);

CREATE INDEX IF NOT EXISTS idx_am_counterfactual_eval_log_query
    ON am_counterfactual_eval_log(query, as_of_date);

COMMIT;
