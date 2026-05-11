-- migration 220_jpi_user_export_log — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW   IF EXISTS v_jpi_export_log_completed;
DROP INDEX  IF EXISTS idx_jpi_export_log_failed;
DROP INDEX  IF EXISTS idx_jpi_export_log_time;
DROP INDEX  IF EXISTS idx_jpi_export_log_key;
DROP TABLE  IF EXISTS jpi_user_export_log;
