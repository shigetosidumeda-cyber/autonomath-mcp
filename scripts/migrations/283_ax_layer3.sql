-- target_db: autonomath
-- migration: 283_ax_layer3
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim W (AX Layer 3: WebMCP + A2A + Observability) storage layer
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
--
-- Purpose
-- -------
-- Storage substrate for the Dim W "AX Layer 3" surface (per
-- feedback_ax_4_pillars.md — Layer 1+2 (Access/Context/Tools) already
-- complete; Layer 3 = WebMCP + A2A handshake + Observability metrics).
-- Three independent axes captured by three small tables:
--
--   * am_webmcp_endpoint — registry of WebMCP transport endpoints
--     advertised by jpcite (HTTP transport variant of MCP for browser /
--     in-page agent embeds). Each row pairs a URL path with a transport
--     enum (sse | streamable_http) and a capability tag.
--   * am_a2a_handshake_log — append-only audit of agent-to-agent
--     handshake attempts (capability negotiation between two agents).
--     Used to score AX funnel "Trustability" and to debug interop.
--   * am_observability_metric — append-only metric stream (Layer 3
--     observability piece). Pairs metric_name + value + recorded_at;
--     downstream rollups read this for AX-Layer-3 dashboards.
--
-- This migration is the OBSERVABILITY OVERLAY on top of the AX 4
-- pillars (Access/Context/Tools/Orchestration). Layers 1 and 2 are
-- already wired (mcp_resources / openapi / mcp_prompts / discovery /
-- mcp.json — present in main HEAD); Layer 3 was the only remaining
-- pillar without a persistent substrate. Pure additive — does NOT
-- touch any existing AX 4-pillar table.
--
-- LLM-0 discipline
-- ----------------
-- Schema is config + audit metadata only. ZERO columns imply LLM
-- inference (no "summary_text", no "ai_explanation"). The handshake
-- log records WHAT was negotiated, not WHY. All natural-language
-- explanation is rendered customer-side by the customer's own agent.
-- Tests in test_dim_w_ax_layer3.py guard the LLM-0 invariant.
--
-- ¥3/req billing posture
-- ----------------------
-- These tables are internal AX-layer bookkeeping; they do NOT bill.
-- Each WebMCP endpoint hit still bills ¥3/req via the existing
-- usage_events meter (the endpoint REGISTRATION here is config, not
-- a billable event).
--
-- §52 / §47条の2 / §72 / §1 disclaimer parity is enforced by the REST/
-- MCP envelope (_disclaimer field), not at the SQL layer.

PRAGMA foreign_keys = ON;

BEGIN;

-- Registry of WebMCP transport endpoints advertised by jpcite.
-- One row per (path, transport) pair. Capability tag groups endpoints
-- by AX pillar (access | context | tools | orchestration).
CREATE TABLE IF NOT EXISTS am_webmcp_endpoint (
    endpoint_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    path                    TEXT NOT NULL,                                      -- URL path served by the WebMCP transport (e.g. /v1/mcp/sse)
    transport               TEXT NOT NULL                                       -- MCP transport variant per spec 2025-06-18
                                CHECK (transport IN ('sse', 'streamable_http')),
    capability_tag          TEXT NOT NULL                                       -- AX 4-pillar tag (access|context|tools|orchestration)
                                CHECK (capability_tag IN ('access', 'context', 'tools', 'orchestration')),
    status                  TEXT NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'deprecated', 'retired')),
    description             TEXT,                                               -- short human-readable description (config only)
    registered_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (length(path) BETWEEN 1 AND 256),
    CHECK (path LIKE '/%')                                                      -- path must be a rooted URL path
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_am_webmcp_endpoint_path_transport
    ON am_webmcp_endpoint(path, transport);

CREATE INDEX IF NOT EXISTS idx_am_webmcp_endpoint_capability
    ON am_webmcp_endpoint(capability_tag, status);

-- Append-only audit of agent-to-agent (A2A) handshake attempts.
-- Each row captures one handshake: source agent identifier, target
-- agent identifier, the capability that was negotiated, and an
-- ISO-8601 succeeded_at stamp. Failed handshakes are recorded with
-- succeeded_at = NULL and a non-null failed_at.
CREATE TABLE IF NOT EXISTS am_a2a_handshake_log (
    handshake_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_agent            TEXT NOT NULL,                                      -- opaque source agent identifier (e.g. claude-3.5-sonnet)
    target_agent            TEXT NOT NULL,                                      -- opaque target agent identifier
    capability_negotiated   TEXT NOT NULL,                                      -- capability ID that was negotiated (free-form per A2A spec)
    initiated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    succeeded_at            TEXT,                                               -- non-null on success
    failed_at               TEXT,                                               -- non-null on failure
    failure_reason          TEXT,                                               -- short failure tag (capability_mismatch | auth_failed | timeout | other)
    CHECK (length(source_agent) BETWEEN 1 AND 128),
    CHECK (length(target_agent) BETWEEN 1 AND 128),
    CHECK (length(capability_negotiated) BETWEEN 1 AND 128),
    CHECK (
        (succeeded_at IS NOT NULL AND failed_at IS NULL)
        OR (succeeded_at IS NULL AND failed_at IS NOT NULL)
        OR (succeeded_at IS NULL AND failed_at IS NULL)  -- in-flight
    ),
    CHECK (succeeded_at IS NULL OR succeeded_at >= initiated_at),
    CHECK (failed_at IS NULL OR failed_at >= initiated_at)
);

CREATE INDEX IF NOT EXISTS idx_am_a2a_handshake_target
    ON am_a2a_handshake_log(target_agent, initiated_at DESC);

CREATE INDEX IF NOT EXISTS idx_am_a2a_handshake_capability
    ON am_a2a_handshake_log(capability_negotiated, succeeded_at);

-- Append-only metric stream for AX Layer 3 observability. Each row
-- captures (metric_name, value, recorded_at). Rollups (hourly /
-- daily) are computed downstream — this table is the raw substrate.
CREATE TABLE IF NOT EXISTS am_observability_metric (
    metric_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name             TEXT NOT NULL,                                      -- dotted metric path (e.g. webmcp.sse.requests_per_min)
    value                   REAL NOT NULL,                                      -- numeric value (use 0/1 for boolean signals)
    unit                    TEXT,                                               -- optional unit hint (ms | count | bytes | ratio)
    recorded_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (length(metric_name) BETWEEN 1 AND 128),
    CHECK (unit IS NULL OR length(unit) BETWEEN 1 AND 16)
);

CREATE INDEX IF NOT EXISTS idx_am_observability_metric_name_time
    ON am_observability_metric(metric_name, recorded_at DESC);

-- Helper view: latest 100 observability metric points per name.
-- Drives the AX Layer 3 dashboard tile.
DROP VIEW IF EXISTS v_observability_recent;
CREATE VIEW v_observability_recent AS
SELECT
    metric_id,
    metric_name,
    value,
    unit,
    recorded_at
FROM am_observability_metric
ORDER BY recorded_at DESC
LIMIT 100;

-- Helper view: active WebMCP endpoints grouped by capability.
DROP VIEW IF EXISTS v_webmcp_endpoint_active;
CREATE VIEW v_webmcp_endpoint_active AS
SELECT
    endpoint_id,
    path,
    transport,
    capability_tag,
    description,
    registered_at
FROM am_webmcp_endpoint
WHERE status = 'active'
ORDER BY capability_tag, path;

COMMIT;
