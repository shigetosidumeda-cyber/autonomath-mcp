-- target_db: autonomath
-- migration: 276_composable_tools (rollback)
-- author: Wave 47 — Dim P (composable_tools) storage layer rollback
--
-- Rollback only drops the Dim P storage surface (catalogue + invocation
-- log). This is irreversible for any rows already inserted; intended for
-- non-production / dev re-runs.

BEGIN;

DROP VIEW  IF EXISTS v_composed_tools_latest;
DROP INDEX IF EXISTS idx_am_composed_tool_invocation_log_input_hash;
DROP INDEX IF EXISTS idx_am_composed_tool_invocation_log_tool_time;
DROP TABLE IF EXISTS am_composed_tool_invocation_log;
DROP INDEX IF EXISTS idx_am_composed_tool_catalog_domain_status;
DROP INDEX IF EXISTS idx_am_composed_tool_catalog_tool_version;
DROP TABLE IF EXISTS am_composed_tool_catalog;

COMMIT;
