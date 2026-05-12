-- target_db: autonomath
-- migration: 279_copilot_scaffold
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim S (embedded copilot scaffold) storage layer
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Storage substrate for the Dim S "embedded copilot scaffold" surface
-- (per feedback_copilot_scaffold_only_no_llm.md). Provides the operator
-- audit layer for embed widgets that customers drop into their own SaaS
-- (freee / MoneyForward / Notion / Slack) — but with **LLM inference 0**:
-- the widget is a scaffold + MCP proxy + OAuth bridge ONLY. All reasoning
-- happens on the customer side (their own Claude / their own agent). We
-- expose tools + data through MCP; we never invoke an LLM API.
--
-- Two tables (separate write-shapes)
-- ----------------------------------
--   * am_copilot_widget_config: write-rare config table, one row per
--     supported host SaaS. host_saas + embed_url + mcp_proxy_url +
--     oauth_scope. ~4 seed rows initially (freee / MF / Notion / Slack),
--     extended only by config commits.
--
--   * am_copilot_session_log: append-only per-session audit. Records
--     widget_id + user_token_hash (sha256, raw token never stored) +
--     started_at + ended_at. Used for billing reconciliation (¥3/req on
--     the MCP proxy back-end, NOT for any LLM call) and forensic replay.
--
-- LLM-0 discipline
-- ----------------
-- This migration registers ZERO columns that would imply LLM inference
-- (no "prompt_template", no "response_text", no "completion_tokens").
-- Every column is config/audit metadata only. If a future PR tries to
-- add such a column, tests/test_dim_s_copilot_scaffold.py guards reject
-- the schema delta. See feedback_copilot_scaffold_only_no_llm.md.
--
-- ¥3/req billing posture
-- ----------------------
-- Each MCP proxy call from inside the embedded widget is metered like
-- any other call. The session_log row is operator-internal book-keeping
-- (not a customer read path).
--
-- §52 / §47条の2 / §72 / §1 disclaimer parity is enforced by the REST/
-- MCP envelope (_disclaimer field), not at the SQL layer.

PRAGMA foreign_keys = ON;

BEGIN;

-- Config: one row per supported host SaaS.
CREATE TABLE IF NOT EXISTS am_copilot_widget_config (
    widget_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    host_saas        TEXT NOT NULL,                       -- e.g. 'freee' | 'moneyforward' | 'notion' | 'slack'
    embed_url        TEXT NOT NULL,                       -- HTTPS URL where the customer SaaS iframes the scaffold
    mcp_proxy_url    TEXT NOT NULL,                       -- jpcite-side MCP proxy endpoint (Streamable HTTP)
    oauth_scope      TEXT NOT NULL DEFAULT '',            -- space-separated OAuth scopes brokered by the bridge
    enabled          INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (host_saas),
    CHECK (length(host_saas) BETWEEN 1 AND 64),
    CHECK (embed_url LIKE 'https://%'),
    CHECK (mcp_proxy_url LIKE 'https://%'),
    CHECK (length(oauth_scope) <= 512)
);

CREATE INDEX IF NOT EXISTS idx_am_copilot_widget_config_host
    ON am_copilot_widget_config(host_saas);

CREATE INDEX IF NOT EXISTS idx_am_copilot_widget_config_enabled
    ON am_copilot_widget_config(enabled, host_saas);

-- Helper view: enabled widgets only (driven by host SaaS).
DROP VIEW IF EXISTS v_copilot_widget_enabled;
CREATE VIEW v_copilot_widget_enabled AS
SELECT
    widget_id,
    host_saas,
    embed_url,
    mcp_proxy_url,
    oauth_scope,
    created_at,
    updated_at
FROM am_copilot_widget_config
WHERE enabled = 1
ORDER BY host_saas;

-- Append-only session audit log.
CREATE TABLE IF NOT EXISTS am_copilot_session_log (
    session_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    widget_id         INTEGER NOT NULL,                   -- FK -> am_copilot_widget_config(widget_id)
    user_token_hash   TEXT NOT NULL,                      -- sha256 hex of the user OAuth token (raw never stored)
    started_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    ended_at          TEXT,                               -- nullable until session closes
    CHECK (length(user_token_hash) = 64),                 -- sha256 hex
    CHECK (ended_at IS NULL OR ended_at >= started_at),
    FOREIGN KEY (widget_id) REFERENCES am_copilot_widget_config(widget_id)
);

CREATE INDEX IF NOT EXISTS idx_am_copilot_session_log_widget
    ON am_copilot_session_log(widget_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_copilot_session_log_started
    ON am_copilot_session_log(started_at);

CREATE INDEX IF NOT EXISTS idx_am_copilot_session_log_active
    ON am_copilot_session_log(widget_id) WHERE ended_at IS NULL;

COMMIT;
