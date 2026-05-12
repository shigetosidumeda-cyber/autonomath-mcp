-- target_db: autonomath
-- migration: 272_session_context (rollback)
-- author: Wave 47 — Dim L (session_context_design) storage layer rollback
--
-- Rollback only drops the Dim L audit/persistence surface (context table +
-- step log + alive view). The REST kernel's in-process LRU primitive
-- (src/jpintel_mcp/api/session_context.py) is untouched, since it does
-- not depend on these tables.
--
-- Irreversible for any rows already inserted; intended for non-production
-- / dev re-runs.

BEGIN;

DROP VIEW  IF EXISTS v_session_context_alive;

DROP INDEX IF EXISTS idx_am_session_step_log_created;
DROP INDEX IF EXISTS idx_am_session_step_log_request_hash;
DROP INDEX IF EXISTS idx_am_session_step_log_session_step;
DROP TABLE IF EXISTS am_session_step_log;

DROP INDEX IF EXISTS idx_am_session_context_status_expires;
DROP INDEX IF EXISTS idx_am_session_context_expires;
DROP INDEX IF EXISTS idx_am_session_context_token;
DROP TABLE IF EXISTS am_session_context;

COMMIT;
