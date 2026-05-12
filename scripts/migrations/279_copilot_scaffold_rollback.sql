-- target_db: autonomath
-- migration: 279_copilot_scaffold (rollback)
-- author: Wave 47 — Dim S (embedded copilot scaffold) storage rollback
--
-- Rollback drops only the Dim S scaffold/audit surface (widget config,
-- session log, enabled-widget helper view). No other module owns these
-- tables. Irreversible for any rows already inserted; intended for
-- non-production / dev re-runs only.

BEGIN;

DROP VIEW  IF EXISTS v_copilot_widget_enabled;

DROP INDEX IF EXISTS idx_am_copilot_session_log_active;
DROP INDEX IF EXISTS idx_am_copilot_session_log_started;
DROP INDEX IF EXISTS idx_am_copilot_session_log_widget;
DROP TABLE IF EXISTS am_copilot_session_log;

DROP INDEX IF EXISTS idx_am_copilot_widget_config_enabled;
DROP INDEX IF EXISTS idx_am_copilot_widget_config_host;
DROP TABLE IF EXISTS am_copilot_widget_config;

COMMIT;
