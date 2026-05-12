-- target_db: autonomath
-- migration: 282_x402_payment
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim V (x402 protocol micropayment) storage layer
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Storage substrate for the Dim V "x402 protocol micropayment" surface
-- (per feedback_agent_x402_protocol.md). x402 is the Coinbase-issued
-- HTTP-402-based USDC micropayment standard: no API key required, $0.001
-- minimum, < 2 second settlement on Base L2. jpcite exposes selected
-- endpoints as x402-gated so a stateless agent can call once, pay once,
-- without an account.
--
-- Two tables (separate write-shapes)
-- ----------------------------------
--   * am_x402_endpoint_config — config table; one row per x402-gated
--     endpoint. endpoint_path (PK) + required_amount_usdc + expires_after_
--     seconds (TTL for the issued bearer key, e.g. 3600 = 1h, default).
--     Refreshed by scripts/etl/seed_x402_endpoints.py.
--
--   * am_x402_payment_log — append-only audit log; one row per HTTP 402
--     transaction that the edge handler (functions/x402_handler.ts) has
--     verified as on-chain settled. payment_id PK + http_status_402_id
--     (canonical opaque ID issued back to the agent on the 402 challenge,
--     used to correlate the subsequent settled request) + amount_usdc +
--     payer_address (the EOA that paid) + txn_hash (Base L2 txn hash) +
--     occurred_at.
--
-- Relationship to existing x402_tx_bind (in billing_v2.py)
-- --------------------------------------------------------
-- The existing inline-CREATE x402_tx_bind table (created lazily by
-- billing_v2.x402_issue_key) maps Base txn -> api_key issuance. The
-- Dim V additions complement this:
--   * am_x402_endpoint_config registers WHICH endpoints are x402-gated
--     and at what price (per-call), decoupling pricing from code.
--   * am_x402_payment_log records WHEN the 402 challenge was resolved
--     and which endpoint was actually billed (the existing tx_bind
--     table only tracks api-key issuance, not per-call billing).
-- Neither table is renamed or replaced; this is an additive surface.
--
-- LLM-0 discipline
-- ----------------
-- Pure config + audit metadata. ZERO columns imply LLM inference (no
-- prompt_template / response_text / completion_tokens). The companion
-- test_dim_v_x402.py guards against schema drift that would re-introduce
-- an LLM-style column.
--
-- ¥3/req vs $0.001/req
-- --------------------
-- jpcite's primary rail is ¥3/req via metered API key (Stripe Portal /
-- ACP / metered SDK). x402 is the third rail (per
-- feedback_agent_monetization_3_payment_rails) for stateless agents who
-- cannot manage credentials. Pricing per endpoint is denominated in USDC
-- (with 6-decimal precision: amount_usdc is REAL > 0). Endpoint operators
-- pick a price band per call; an indicative seed is 0.001-0.01 USDC.
--
-- Retention
-- ---------
-- am_x402_payment_log: 365-day rolling window swept by dlq_drain.py.
-- am_x402_endpoint_config: persistent, refreshed by seed ETL.

PRAGMA foreign_keys = ON;

BEGIN;

-- x402-gated endpoint registry. One row per HTTP path we expose at the
-- $0.001-level price band. Refreshed by seed_x402_endpoints.py.
CREATE TABLE IF NOT EXISTS am_x402_endpoint_config (
    endpoint_path          TEXT PRIMARY KEY,                   -- canonical path, e.g. '/v1/search'
    required_amount_usdc   REAL NOT NULL,                      -- per-call price in USDC (6 dp)
    expires_after_seconds  INTEGER NOT NULL DEFAULT 3600,      -- TTL of the issued bearer key
    enabled                INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (length(endpoint_path) BETWEEN 1 AND 256),
    CHECK (endpoint_path LIKE '/%'),
    CHECK (required_amount_usdc > 0),
    CHECK (required_amount_usdc <= 100),                       -- sanity cap; x402 is for micropayments
    CHECK (expires_after_seconds BETWEEN 60 AND 86400)         -- 1 min ≤ TTL ≤ 24h
);

CREATE INDEX IF NOT EXISTS idx_am_x402_endpoint_config_enabled
    ON am_x402_endpoint_config(enabled, endpoint_path);

-- Helper view: enabled x402-gated endpoints only.
DROP VIEW IF EXISTS v_x402_endpoint_enabled;
CREATE VIEW v_x402_endpoint_enabled AS
SELECT
    endpoint_path,
    required_amount_usdc,
    expires_after_seconds,
    created_at,
    updated_at
FROM am_x402_endpoint_config
WHERE enabled = 1
ORDER BY endpoint_path;

-- Append-only per-payment audit log. http_status_402_id is the opaque
-- nonce returned on the original 402 challenge (so the edge can correlate
-- the eventual settled request back to its original gate).
CREATE TABLE IF NOT EXISTS am_x402_payment_log (
    payment_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    http_status_402_id   TEXT NOT NULL,                        -- opaque nonce from the 402 challenge
    endpoint_path        TEXT NOT NULL,                        -- soft FK -> am_x402_endpoint_config(endpoint_path)
    amount_usdc          REAL NOT NULL,                        -- actually-paid amount in USDC
    payer_address        TEXT NOT NULL,                        -- 0x... EOA on Base
    txn_hash             TEXT NOT NULL,                        -- 0x... Base L2 txn hash (66 chars incl prefix)
    occurred_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (txn_hash),                                         -- one log row per on-chain txn
    CHECK (length(http_status_402_id) BETWEEN 8 AND 128),
    CHECK (endpoint_path LIKE '/%'),
    CHECK (amount_usdc > 0),
    CHECK (payer_address LIKE '0x%' AND length(payer_address) = 42),
    CHECK (txn_hash LIKE '0x%' AND length(txn_hash) = 66)
);

CREATE INDEX IF NOT EXISTS idx_am_x402_payment_log_endpoint
    ON am_x402_payment_log(endpoint_path, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_x402_payment_log_payer
    ON am_x402_payment_log(payer_address, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_x402_payment_log_time
    ON am_x402_payment_log(occurred_at DESC);

COMMIT;
