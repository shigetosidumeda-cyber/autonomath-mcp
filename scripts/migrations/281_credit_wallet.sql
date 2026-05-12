-- target_db: autonomath
-- migration: 281_credit_wallet
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim U (Agent Credit Wallet) storage layer
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Storage substrate for the Dim U "Agent Credit Wallet" surface
-- (per feedback_agent_credit_wallet_design.md). Provides three
-- operator-internal tables for the pre-paid wallet, transaction
-- log, and spending-alert ledger that backs the ¥3/req call rail.
-- Designed for CFO/CIO budget-predictability concerns: pre-payment
-- + auto-topup + 50%/80%/100% threshold spending alerts.
--
-- Three tables (separate write-shapes)
-- ------------------------------------
--   * am_credit_wallet: one row per wallet (owner_token_hash unique).
--     balance_yen (current balance in JPY units), plus auto-topup
--     configuration (threshold + amount). Updated by topup/charge.
--
--   * am_credit_transaction_log: append-only ledger. Every topup,
--     charge, and refund is one row. txn_type enum constrained
--     to {topup, charge, refund}. Used for billing reconciliation
--     and per-tenant forensic replay.
--
--   * am_credit_spending_alert: per-wallet + per-threshold record
--     of the moment an alert fired (50/80/100 pct). UNIQUE
--     (wallet_id, threshold_pct, billing_cycle) ensures we never
--     re-fire the same alert in the same cycle.
--
-- LLM-0 discipline
-- ----------------
-- This migration registers ZERO columns that would imply LLM
-- inference. Every column is financial accounting / audit only.
-- Wallet balance enforcement is server-side, not LLM-side.
--
-- Per-call billing rail
-- ---------------------
-- Each MCP / REST call deducts a configured charge_yen from the
-- wallet via charge txn. Refund txn allowed only by operator
-- script. spending_alert workflow runs hourly by the ETL.

PRAGMA foreign_keys = ON;

BEGIN;

-- Wallet table: one row per agent owner (token-hashed).
CREATE TABLE IF NOT EXISTS am_credit_wallet (
    wallet_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_token_hash       TEXT NOT NULL,                       -- sha256 hex of owner API token (raw never stored)
    balance_yen            INTEGER NOT NULL DEFAULT 0,          -- current wallet balance in JPY
    auto_topup_threshold   INTEGER NOT NULL DEFAULT 0,          -- if balance falls below, trigger auto-topup
    auto_topup_amount      INTEGER NOT NULL DEFAULT 0,          -- amount to topup automatically (¥)
    monthly_budget_yen     INTEGER NOT NULL DEFAULT 0,          -- soft cap used by spending alert (0 = disabled)
    enabled                INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (owner_token_hash),
    CHECK (length(owner_token_hash) = 64),                       -- sha256 hex
    CHECK (balance_yen >= 0),
    CHECK (auto_topup_threshold >= 0),
    CHECK (auto_topup_amount >= 0),
    CHECK (monthly_budget_yen >= 0)
);

CREATE INDEX IF NOT EXISTS idx_am_credit_wallet_owner
    ON am_credit_wallet(owner_token_hash);

CREATE INDEX IF NOT EXISTS idx_am_credit_wallet_enabled
    ON am_credit_wallet(enabled);

-- Append-only transaction ledger.
CREATE TABLE IF NOT EXISTS am_credit_transaction_log (
    txn_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_id     INTEGER NOT NULL,                              -- FK -> am_credit_wallet(wallet_id)
    amount_yen    INTEGER NOT NULL,                              -- positive (topup/refund) or negative (charge)
    txn_type      TEXT NOT NULL,                                 -- enum: topup | charge | refund
    occurred_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    note          TEXT,                                          -- optional human note
    CHECK (txn_type IN ('topup', 'charge', 'refund')),
    CHECK (
        (txn_type = 'topup'  AND amount_yen > 0) OR
        (txn_type = 'refund' AND amount_yen > 0) OR
        (txn_type = 'charge' AND amount_yen < 0)
    ),
    FOREIGN KEY (wallet_id) REFERENCES am_credit_wallet(wallet_id)
);

CREATE INDEX IF NOT EXISTS idx_am_credit_transaction_log_wallet
    ON am_credit_transaction_log(wallet_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_credit_transaction_log_type
    ON am_credit_transaction_log(txn_type, occurred_at);

-- Spending alert ledger. One row per (wallet, threshold, cycle) firing.
CREATE TABLE IF NOT EXISTS am_credit_spending_alert (
    alert_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_id       INTEGER NOT NULL,                            -- FK -> am_credit_wallet(wallet_id)
    threshold_pct   INTEGER NOT NULL,                            -- enum-like: 50 | 80 | 100
    billing_cycle   TEXT NOT NULL,                               -- 'YYYY-MM' bucket so re-fire in next month is allowed
    fired_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    spent_yen       INTEGER NOT NULL,                            -- amount spent at firing time
    budget_yen      INTEGER NOT NULL,                            -- monthly_budget_yen at firing time
    UNIQUE (wallet_id, threshold_pct, billing_cycle),
    CHECK (threshold_pct IN (50, 80, 100)),
    CHECK (length(billing_cycle) = 7),                            -- YYYY-MM
    CHECK (spent_yen >= 0),
    CHECK (budget_yen >= 0),
    FOREIGN KEY (wallet_id) REFERENCES am_credit_wallet(wallet_id)
);

CREATE INDEX IF NOT EXISTS idx_am_credit_spending_alert_wallet
    ON am_credit_spending_alert(wallet_id, fired_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_credit_spending_alert_cycle
    ON am_credit_spending_alert(billing_cycle, threshold_pct);

-- Helper view: wallets eligible for auto-topup (enabled + balance below threshold).
DROP VIEW IF EXISTS v_credit_wallet_topup_due;
CREATE VIEW v_credit_wallet_topup_due AS
SELECT
    wallet_id,
    owner_token_hash,
    balance_yen,
    auto_topup_threshold,
    auto_topup_amount
FROM am_credit_wallet
WHERE enabled = 1
  AND auto_topup_threshold > 0
  AND auto_topup_amount > 0
  AND balance_yen < auto_topup_threshold;

COMMIT;
