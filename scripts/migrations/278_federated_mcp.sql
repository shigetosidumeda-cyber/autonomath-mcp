-- target_db: autonomath
-- migration: 278_federated_mcp
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim R (federated MCP recommendation) storage layer
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Persists the federated-MCP partner catalogue + handoff audit log
-- consumed by Dim R recommendation surface. jpcite becomes the agent
-- "hub" — when a query exits its own answerable surface (e.g. payroll
-- transactional ops, calendar workflows, doc collaboration), the hub
-- emits a curated handoff suggestion pointing the agent at one of 6
-- partner MCP servers (freee / MoneyForward / Notion / Slack / GitHub
-- / Linear). The seed catalogue is loaded by
-- scripts/etl/seed_federated_mcp_partners.py.
--
-- Pattern
-- -------
-- Two tables (catalogue + log), mirroring Dim K (271_rule_tree) and
-- Dim N (274_anonymized_query) split. The catalogue (am_federated_mcp_
-- partner) is a small static table refreshed by ETL re-seed; the log
-- (am_handoff_log) is append-only and grows linearly with handoff
-- recommendation traffic.
--
-- No external MCP server is called from this layer
-- ---------------------------------------------------------
-- This migration only stores the catalogue + the recommendation audit
-- trail. The actual cross-server handoff is initiated by the agent
-- client (Claude / Cursor / etc.) using the partner's published MCP
-- endpoint — the jpcite hub never proxies traffic. Per
-- feedback_federated_mcp_recommendation: 6 partner curated, gap ->
-- handoff suggestion, no LLM API call on our side.
--
-- Health check column
-- -------------------
-- last_health_at is updated by an out-of-band cron probe (DNS / TLS /
-- discovery doc reachability). A NULL value means "never checked";
-- callers should treat it as DEGRADED for safety. The probe is
-- non-LLM (pure HTTPS HEAD) and lives in scripts/cron/.
--
-- ¥3/req billing posture
-- ----------------------
-- Handoff recommendation answers stay at 1 metered unit. Logging the
-- handoff does NOT charge a separate unit; it is an internal audit
-- side-effect of the recommendation call.
--
-- Retention
-- ---------
-- am_handoff_log: 365-day rolling window swept by dlq_drain.py cleanup
-- pass. am_federated_mcp_partner: persistent (refreshed by seed ETL).

PRAGMA foreign_keys = ON;

BEGIN;

-- Curated partner catalogue. Refreshed by
-- scripts/etl/seed_federated_mcp_partners.py.
CREATE TABLE IF NOT EXISTS am_federated_mcp_partner (
    partner_id          TEXT PRIMARY KEY,                    -- short slug: freee / mf / notion / slack / github / linear
    name                TEXT NOT NULL,                       -- display name: "freee 会計", etc.
    server_url          TEXT NOT NULL,                       -- canonical MCP server endpoint (https://...)
    capability_tag      TEXT NOT NULL                        -- one or more pipe-separated tags
                        CHECK (length(capability_tag) > 0),  -- e.g. 'accounting|invoice', 'doc|kb', 'chat|notify'
    last_health_at      TEXT,                                -- NULL = never checked (treat as DEGRADED)
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_am_federated_mcp_partner_capability
    ON am_federated_mcp_partner(capability_tag);

CREATE INDEX IF NOT EXISTS idx_am_federated_mcp_partner_health
    ON am_federated_mcp_partner(last_health_at DESC);

-- Per-call handoff audit log. Append-only. partner_id is a soft FK
-- (no ON DELETE cascade) so deleting a partner row does not erase the
-- historical audit trail.
CREATE TABLE IF NOT EXISTS am_handoff_log (
    handoff_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_query        TEXT NOT NULL,                       -- user/agent query that triggered the handoff
    partner_id          TEXT NOT NULL,                       -- soft FK to am_federated_mcp_partner.partner_id
    response_summary    TEXT NOT NULL DEFAULT '',            -- short recommendation rationale
    requested_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_am_handoff_log_partner
    ON am_handoff_log(partner_id, requested_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_handoff_log_time
    ON am_handoff_log(requested_at DESC);

COMMIT;
