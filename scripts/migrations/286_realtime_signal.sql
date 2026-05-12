-- target_db: autonomath
-- migration: 286_realtime_signal
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim G (realtime_signal subscriber + event_log)
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Wave 47 layer-on for the Dim G "realtime_signal" surface. Migration 263
-- already shipped `am_realtime_subscribers` + `am_realtime_dispatch_history`
-- with a per-(subscriber, target_kind, signal_id) UNIQUE attempt log. The
-- Wave 47 booster adds a SECOND, signal-types-driven write shape that the
-- new dispatcher ETL writes into directly:
--
--   * `am_realtime_signal_subscriber` — one row per webhook destination,
--     keyed by the `subscriber_id` AUTOINCREMENT and indexed by JSON-array
--     `signal_types` (NOT a single target_kind). Lets a single webhook URL
--     fan in N signal types in one delivery contract.
--
--   * `am_realtime_signal_event_log` — append-only delivery log keyed by
--     `event_id`. Records subscriber_id (soft FK), signal_type, payload
--     (JSON, capped 8 KB) and delivered_at. Used by the dispatcher cron to
--     mark "delivered" and by the billing reconciliation job to count
--     ¥3/req 2xx deliveries.
--
-- Why two tables instead of extending 263
-- ---------------------------------------
-- 263 modeled one subscription per target_kind (filter_json discriminator
-- inside the same row). Wave 47 customers ask for fan-out: a single webhook
-- contract that fires on ANY of N signal types. Extending 263 in place
-- would require a destructive DDL rewrite (CHECK constraint shape change);
-- a parallel layer is additive only and lets both subscriber models
-- co-exist while we migrate clients in their own time.
--
-- ¥3/req billing posture
-- ----------------------
-- One 2xx delivery row in `am_realtime_signal_event_log` = one billable
-- unit. Pre-delivery rows (pending / 5xx-retry / 4xx-permanent-fail) are
-- ALSO recorded but `delivered_at IS NULL` rows do NOT count toward billing.
-- Reconciliation joins on `delivered_at IS NOT NULL` only.
--
-- LLM-0 discipline
-- ----------------
-- This migration registers ZERO columns that imply LLM inference. Every
-- column is config/audit metadata. The dispatcher ETL is plain HTTP POST
-- (no Anthropic / OpenAI SDK; per `feedback_no_operator_llm_api`).

PRAGMA foreign_keys = ON;

BEGIN;

-- Wave 47 signal subscriber (fan-out across signal_types JSON array).
CREATE TABLE IF NOT EXISTS am_realtime_signal_subscriber (
    subscriber_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_url       TEXT NOT NULL,                       -- https://... destination (validated by API)
    signal_types      TEXT NOT NULL DEFAULT '[]',          -- JSON array of signal_type strings
    enabled           INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    last_signal_at    TEXT,                                -- last successful 2xx delivery (NULL until first hit)
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (webhook_url),
    CHECK (webhook_url LIKE 'https://%'),
    CHECK (length(webhook_url) BETWEEN 12 AND 512),
    CHECK (length(signal_types) <= 4096),
    CHECK (json_valid(signal_types))
);

CREATE INDEX IF NOT EXISTS idx_am_rt_sig_sub_enabled
    ON am_realtime_signal_subscriber(enabled, subscriber_id);

CREATE INDEX IF NOT EXISTS idx_am_rt_sig_sub_last_signal
    ON am_realtime_signal_subscriber(last_signal_at DESC);

-- Wave 47 append-only event log (one row per dispatch attempt).
CREATE TABLE IF NOT EXISTS am_realtime_signal_event_log (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    subscriber_id   INTEGER NOT NULL,                      -- soft FK -> am_realtime_signal_subscriber
    signal_type     TEXT NOT NULL,                         -- e.g. 'kokkai_bill' | 'amendment' | 'program_created'
    payload         TEXT NOT NULL DEFAULT '{}',            -- JSON payload (cap 8 KB)
    status_code     INTEGER,                               -- HTTP 2xx/4xx/5xx; NULL while pending
    attempt_count   INTEGER NOT NULL DEFAULT 1,
    error           TEXT,                                  -- last error string, capped 256 chars
    delivered_at    TEXT,                                  -- timestamp of the 2xx event; NULL while pending
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (length(signal_type) BETWEEN 1 AND 64),
    CHECK (length(payload) <= 8192),
    CHECK (json_valid(payload)),
    CHECK (attempt_count >= 1)
);

CREATE INDEX IF NOT EXISTS idx_am_rt_sig_event_sub_created
    ON am_realtime_signal_event_log(subscriber_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_rt_sig_event_type_created
    ON am_realtime_signal_event_log(signal_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_rt_sig_event_pending
    ON am_realtime_signal_event_log(subscriber_id, created_at)
    WHERE delivered_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_am_rt_sig_event_delivered
    ON am_realtime_signal_event_log(delivered_at)
    WHERE delivered_at IS NOT NULL;

-- Helper view: enabled subscribers only, sorted by subscriber_id.
DROP VIEW IF EXISTS v_realtime_signal_subscriber_enabled;
CREATE VIEW v_realtime_signal_subscriber_enabled AS
SELECT
    subscriber_id,
    webhook_url,
    signal_types,
    last_signal_at,
    created_at,
    updated_at
FROM am_realtime_signal_subscriber
WHERE enabled = 1
ORDER BY subscriber_id;

COMMIT;
