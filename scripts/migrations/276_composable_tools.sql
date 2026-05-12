-- target_db: autonomath
-- migration: 276_composable_tools
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim P (composable_tools) storage layer
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Persists the server-side composition catalogue for Dim P (composable
-- tools). Atomic 139-tool surface is wrapped by named "composed tools"
-- whose execution chains a fixed sequence of atomic tool invocations
-- into one logical call. Replaces a 7-call DD walk with 1 call (7×
-- economisation). Pairs with the 4 canonical composed tools seeded by
-- scripts/etl/seed_composed_tools.py:
--   1. ultimate_due_diligence_kit
--   2. construction_total_dd
--   3. welfare_total_dd
--   4. tourism_total_dd
--
-- Pattern
-- -------
-- The catalogue (am_composed_tool_catalog) stores the composition itself
-- as a JSON blob (atomic_tool_chain) keyed by (tool_id, version). Editing
-- a composition means INSERTing a new version row; the dispatcher picks
-- the latest committed version unless a caller pins one. Every actual
-- invocation appends a row to am_composed_tool_invocation_log with input
-- / output content hashes + latency so downstream forensics can replay
-- or audit a past call without re-running it.
--
-- Why two tables (not one)
-- ------------------------
-- - am_composed_tool_catalog: small (≤ low hundreds over lifetime).
--   Read-heavy; indexed by tool_id + version.
-- - am_composed_tool_invocation_log: append-only, linear with traffic.
--   Indexed by tool_id + created_at for time-window queries.
-- Mixing catalogue + log on a single table would force a full scan over
-- every past invocation each time the catalogue is loaded.
--
-- ¥3/req billing posture
-- ----------------------
-- A composed tool counts as ONE metered call regardless of atomic chain
-- length — this is the entire economic point of Dim P. Server-side
-- composition does NOT multiply Anthropic API consumption either: the
-- atomic chain is dispatched in-process against SQLite, no LLM invoked
-- (feedback_no_operator_llm_api).
--
-- Retention
-- ---------
-- am_composed_tool_catalog: indefinite (source-of-truth for past chains).
-- am_composed_tool_invocation_log: 90-day rolling window swept by
-- dlq_drain.py cleanup pass; failed invocations retained 180d for
-- post-mortem.
--
-- §52 / §47条の2 / §72 / §1 disclaimer parity is enforced by the REST
-- envelope of each composed tool, not at the SQL layer.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS am_composed_tool_catalog (
    row_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_id             TEXT NOT NULL,                       -- e.g. 'ultimate_due_diligence_kit'
    version             INTEGER NOT NULL DEFAULT 1
                        CHECK (version >= 1),
    atomic_tool_chain   TEXT NOT NULL,                       -- canonical JSON chain
    source_doc_id       TEXT,                                -- Dim O citation anchor
    description         TEXT,
    domain              TEXT,                                -- dd / construction / welfare / tourism
    status              TEXT NOT NULL DEFAULT 'committed'    -- committed / draft / retired
                        CHECK (status IN ('committed','draft','retired')),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (tool_id, version)
);

CREATE INDEX IF NOT EXISTS idx_am_composed_tool_catalog_tool_version
    ON am_composed_tool_catalog(tool_id, version DESC);

CREATE INDEX IF NOT EXISTS idx_am_composed_tool_catalog_domain_status
    ON am_composed_tool_catalog(domain, status);

-- Helper view: latest committed version per tool_id (used by dispatcher).
DROP VIEW IF EXISTS v_composed_tools_latest;
CREATE VIEW v_composed_tools_latest AS
SELECT
    tool_id,
    MAX(version)        AS latest_version,
    COUNT(*)            AS total_versions
FROM am_composed_tool_catalog
WHERE status = 'committed'
GROUP BY tool_id;

-- Per-invocation audit trail.
CREATE TABLE IF NOT EXISTS am_composed_tool_invocation_log (
    invocation_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_id             TEXT NOT NULL,
    tool_version        INTEGER,                             -- nullable for ad-hoc dispatches
    input_hash          TEXT NOT NULL,                       -- sha256 of canonicalised input
    output_hash         TEXT NOT NULL,                       -- sha256 of envelope payload
    latency_ms          INTEGER NOT NULL DEFAULT 0
                        CHECK (latency_ms >= 0),
    result              TEXT NOT NULL DEFAULT 'ok'           -- ok / partial / error
                        CHECK (result IN ('ok','partial','error')),
    error_message       TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_am_composed_tool_invocation_log_tool_time
    ON am_composed_tool_invocation_log(tool_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_composed_tool_invocation_log_input_hash
    ON am_composed_tool_invocation_log(input_hash);

COMMIT;
