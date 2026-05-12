-- target_db: autonomath
-- migration: 280_predictive_service
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim T (predictive service: pull -> push) storage layer
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Storage substrate for the Dim T "predictive service" surface (per
-- feedback_predictive_service_design.md). Flips the access pattern from
-- pull (customer polls /v1/...) to push (jpcite notifies subscribers
-- when something they pre-registered as interesting CHANGES). Three
-- watch sources are unified at the storage layer:
--
--   * houjin (legal-entity)  -> upstream am_amendment_diff joined to
--                               the watched 法人番号 / jpi_invoice_registrants
--   * program (subsidy)      -> upstream am_amendment_diff + the
--                               program_window deadline gate
--   * amendment (statute)    -> upstream am_amendment_diff scoped to
--                               a watched law_id
--
-- This migration is the PREDICTIVE OVERLAY on top of customer_watches
-- (mig 088) — that table is the customer-facing registration store.
-- The new tables here capture predictive-service-specific state that
-- does NOT belong in customer_watches:
--
--   * am_predictive_watch_subscription — operator-internal predictive
--     subscription with watch_type enum + threshold + 24h notification
--     window. Lives ALONGSIDE customer_watches (it is the predictive
--     server's own bookkeeping; not the customer-facing registration).
--   * am_predictive_alert_log — append-only per-fire audit of every
--     predictive alert delivered (or attempted), with payload JSON +
--     delivery_status. Used for billing reconciliation (¥3/req on
--     successful 2xx delivery only) and forensic replay.
--
-- Push contract (per feedback_predictive_service_design)
-- ------------------------------------------------------
-- 24-hour predictive notification window: when an amendment_diff row
-- lands that matches an active subscription AND crosses its threshold
-- (e.g. amount_max_yen delta >= threshold_pct), the ETL queues an
-- alert. The alert MUST be delivered within 24h of fired_at or it is
-- considered stale and the row is marked delivery_status='expired'.
-- Re-firing for the same (subscription, source diff) is prevented by
-- the unique partial index further down.
--
-- LLM-0 discipline
-- ----------------
-- Schema is config + audit metadata only. ZERO columns imply LLM
-- inference (no "summary_text", no "ai_explanation"). The predictive
-- service only RANKS + ROUTES facts that already exist in
-- am_amendment_diff. All natural-language summarisation is done on
-- the customer side (their own agent / their own Claude).
-- Tests in test_dim_t_predictive.py guard the LLM-0 invariant.
--
-- ¥3/req billing posture
-- ----------------------
-- Registration is free. Each successful (delivery_status='delivered')
-- alert emits one Stripe usage_record at ¥3/req on the proxy side.
-- delivery_status in ('pending','failed','expired') NEVER bills.
-- This mirrors the customer_webhooks contract from mig 088.
--
-- §52 / §47条の2 / §72 / §1 disclaimer parity is enforced by the REST/
-- MCP envelope (_disclaimer field), not at the SQL layer.

PRAGMA foreign_keys = ON;

BEGIN;

-- Operator-internal predictive subscription bookkeeping. One row per
-- (subscriber_token_hash, watch_type, watch_target). Threshold gates
-- the predictive fire: only changes above the threshold queue alerts.
CREATE TABLE IF NOT EXISTS am_predictive_watch_subscription (
    watch_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    subscriber_token_hash   TEXT NOT NULL,                                      -- sha256 hex of the API key (raw never stored)
    watch_type              TEXT NOT NULL                                       -- predictive source enum
                                CHECK (watch_type IN ('houjin', 'program', 'amendment')),
    watch_target            TEXT NOT NULL,                                      -- 法人番号 / programs.unified_id / laws.law_id (opaque per type)
    threshold               REAL NOT NULL DEFAULT 0.0,                          -- fire when change magnitude >= threshold; 0.0 = always
    notify_window_hours     INTEGER NOT NULL DEFAULT 24                         -- predictive push window per feedback_predictive_service_design
                                CHECK (notify_window_hours BETWEEN 1 AND 168),  -- 1h..7d allowed; default 24h
    status                  TEXT NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'paused', 'cancelled')),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_fired_at           TEXT,                                               -- NULL until first fire
    CHECK (length(subscriber_token_hash) = 64),                                 -- sha256 hex
    CHECK (length(watch_target) BETWEEN 1 AND 128),
    CHECK (threshold >= 0.0)
);

-- Hot path: ETL daily scan groups by (watch_type, watch_target).
CREATE INDEX IF NOT EXISTS idx_am_predictive_watch_target
    ON am_predictive_watch_subscription(watch_type, watch_target, status);

-- "List my subscriptions" hot path.
CREATE INDEX IF NOT EXISTS idx_am_predictive_watch_subscriber
    ON am_predictive_watch_subscription(subscriber_token_hash, status);

-- Dedup: a single (subscriber, type, target) tuple should only have one
-- ACTIVE row. Re-subscribing to the same target soft-toggles the
-- existing row; this partial unique index is the backstop.
CREATE UNIQUE INDEX IF NOT EXISTS uq_am_predictive_watch_active
    ON am_predictive_watch_subscription(subscriber_token_hash, watch_type, watch_target)
 WHERE status = 'active';

-- Append-only audit of every predictive fire. delivery_status drives
-- the billing reconciliation (only 'delivered' rows bill ¥3/req).
CREATE TABLE IF NOT EXISTS am_predictive_alert_log (
    alert_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id                INTEGER NOT NULL,                                   -- FK -> am_predictive_watch_subscription(watch_id)
    fired_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    source_diff_id          INTEGER,                                            -- FK-ish to am_amendment_diff.diff_id (nullable for prog-window-only fires)
    payload                 TEXT NOT NULL,                                      -- JSON payload delivered to the subscriber (or to be delivered)
    delivery_status         TEXT NOT NULL DEFAULT 'pending'
                                CHECK (delivery_status IN ('pending', 'delivered', 'failed', 'expired')),
    delivered_at            TEXT,                                               -- stamped when delivery_status flips to 'delivered'
    CHECK (length(payload) BETWEEN 2 AND 65536),                                -- valid JSON minimum length is "{}"
    CHECK (delivered_at IS NULL OR delivered_at >= fired_at),
    FOREIGN KEY (watch_id) REFERENCES am_predictive_watch_subscription(watch_id)
);

CREATE INDEX IF NOT EXISTS idx_am_predictive_alert_watch
    ON am_predictive_alert_log(watch_id, fired_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_predictive_alert_status
    ON am_predictive_alert_log(delivery_status, fired_at);

-- 24h TTL purge hot path: stale 'pending' rows older than the watch's
-- notify_window_hours get flipped to 'expired'. Indexed for the cron
-- scan in build_predictive_watch_v2.py.
CREATE INDEX IF NOT EXISTS idx_am_predictive_alert_pending_age
    ON am_predictive_alert_log(fired_at)
 WHERE delivery_status = 'pending';

-- Dedup: prevent the ETL from re-firing the same (watch, source diff)
-- twice. Partial unique on rows that DO have a source_diff_id.
CREATE UNIQUE INDEX IF NOT EXISTS uq_am_predictive_alert_dedup
    ON am_predictive_alert_log(watch_id, source_diff_id)
 WHERE source_diff_id IS NOT NULL;

-- Helper view: active subscriptions only (driven by status filter so
-- the ETL collector can join cleanly without WHERE clauses).
DROP VIEW IF EXISTS v_predictive_watch_active;
CREATE VIEW v_predictive_watch_active AS
SELECT
    watch_id,
    subscriber_token_hash,
    watch_type,
    watch_target,
    threshold,
    notify_window_hours,
    created_at,
    last_fired_at
FROM am_predictive_watch_subscription
WHERE status = 'active'
ORDER BY watch_type, watch_target;

COMMIT;
