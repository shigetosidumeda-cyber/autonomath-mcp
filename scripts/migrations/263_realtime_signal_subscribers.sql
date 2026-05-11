-- target_db: autonomath
-- migration: 263_realtime_signal_subscribers
-- generated_at: 2026-05-12
-- author: Wave 43.2.7 — Dim G real-time signal webhook
-- idempotent: every CREATE uses IF NOT EXISTS; no DML.
--
-- Generic broad webhook subscription on (target_kind, filter_json) — fires
-- whenever any kokkai_bill / amendment / enforcement_municipality / etc.
-- matches the filter. Distinct from customer_webhooks (per api_key) and
-- customer_watches (per houjin/program/law target).
--
-- Pricing: registration FREE, ¥3 per successful 2xx delivery.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_realtime_subscribers (
    subscriber_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_hash            TEXT NOT NULL,
    target_kind             TEXT NOT NULL,
    filter_json             TEXT NOT NULL DEFAULT '{}',
    webhook_url             TEXT NOT NULL,
    signature_secret        TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'active',
    failure_count           INTEGER NOT NULL DEFAULT 0,
    last_delivery_at        TEXT,
    last_signal_at          TEXT,
    disabled_at             TEXT,
    disabled_reason         TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CONSTRAINT ck_rts_kind CHECK (target_kind IN (
        'kokkai_bill','amendment','enforcement_municipality',
        'program_created','tax_treaty_amended','court_decision_added',
        'pubcomment_announcement','other'
    )),
    CONSTRAINT ck_rts_status CHECK (status IN ('active','disabled')),
    CONSTRAINT ck_rts_https CHECK (webhook_url LIKE 'https://%')
);

CREATE INDEX IF NOT EXISTS idx_rts_key_active
    ON am_realtime_subscribers(api_key_hash, status);

CREATE INDEX IF NOT EXISTS idx_rts_kind_active
    ON am_realtime_subscribers(target_kind, status);

CREATE INDEX IF NOT EXISTS idx_rts_last_delivery
    ON am_realtime_subscribers(last_delivery_at DESC);

CREATE TABLE IF NOT EXISTS am_realtime_dispatch_history (
    dispatch_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    subscriber_id           INTEGER NOT NULL,
    target_kind             TEXT NOT NULL,
    signal_id               TEXT NOT NULL,
    payload_hash            TEXT,
    status_code             INTEGER,
    attempt_count           INTEGER NOT NULL DEFAULT 1,
    error                   TEXT,
    delivered_at            TEXT,
    billed                  INTEGER NOT NULL DEFAULT 0 CHECK (billed IN (0, 1)),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (subscriber_id, target_kind, signal_id)
);

CREATE INDEX IF NOT EXISTS idx_rts_dispatch_sub_created
    ON am_realtime_dispatch_history(subscriber_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rts_dispatch_kind_created
    ON am_realtime_dispatch_history(target_kind, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rts_dispatch_failed
    ON am_realtime_dispatch_history(subscriber_id, status_code)
    WHERE status_code IS NULL OR status_code < 200 OR status_code >= 300;

DROP VIEW IF EXISTS v_realtime_subscribers_active;
CREATE VIEW v_realtime_subscribers_active AS
SELECT
    subscriber_id, api_key_hash, target_kind, filter_json,
    webhook_url, status, failure_count, last_delivery_at, last_signal_at,
    created_at, updated_at
FROM am_realtime_subscribers
WHERE status = 'active';

COMMIT;
