-- target_db: autonomath
-- rollback: 283_ax_layer3
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim W (AX Layer 3) rollback
--
-- WARNING: this drops the AX Layer 3 substrate (WebMCP + A2A +
-- Observability). Operator-internal only; do NOT run in production
-- unless you understand that all handshake history + metric stream
-- + endpoint registry is destroyed.

PRAGMA foreign_keys = OFF;

BEGIN;

DROP VIEW IF EXISTS v_webmcp_endpoint_active;
DROP VIEW IF EXISTS v_observability_recent;

DROP INDEX IF EXISTS idx_am_observability_metric_name_time;
DROP INDEX IF EXISTS idx_am_a2a_handshake_capability;
DROP INDEX IF EXISTS idx_am_a2a_handshake_target;
DROP INDEX IF EXISTS idx_am_webmcp_endpoint_capability;
DROP INDEX IF EXISTS uq_am_webmcp_endpoint_path_transport;

DROP TABLE IF EXISTS am_observability_metric;
DROP TABLE IF EXISTS am_a2a_handshake_log;
DROP TABLE IF EXISTS am_webmcp_endpoint;

COMMIT;
