-- migration 250_program_private_foundation — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_program_private_foundation_summary;
DROP INDEX IF EXISTS idx_am_foundation_ingest_log_started;
DROP TABLE IF EXISTS am_program_private_foundation_ingest_log;
DROP INDEX IF EXISTS ux_am_foundation_program;
DROP INDEX IF EXISTS idx_am_foundation_refreshed;
DROP INDEX IF EXISTS idx_am_foundation_donation;
DROP INDEX IF EXISTS idx_am_foundation_theme;
DROP INDEX IF EXISTS idx_am_foundation_type;
DROP TABLE IF EXISTS am_program_private_foundation;
