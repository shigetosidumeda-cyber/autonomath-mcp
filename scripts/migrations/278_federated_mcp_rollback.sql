-- target_db: autonomath
-- migration: 278_federated_mcp (rollback)
-- author: Wave 47 — Dim R (federated MCP recommendation) storage layer rollback
--
-- Rollback drops the Dim R storage surface (partner catalogue + handoff
-- log + indices). This is irreversible for any rows already inserted;
-- intended for non-production / dev re-runs.

BEGIN;

DROP INDEX IF EXISTS idx_am_handoff_log_time;
DROP INDEX IF EXISTS idx_am_handoff_log_partner;
DROP TABLE IF EXISTS am_handoff_log;
DROP INDEX IF EXISTS idx_am_federated_mcp_partner_health;
DROP INDEX IF EXISTS idx_am_federated_mcp_partner_capability;
DROP TABLE IF EXISTS am_federated_mcp_partner;

COMMIT;
