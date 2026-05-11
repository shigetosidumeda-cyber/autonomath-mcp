-- migration 245_appi_compliance_dataset — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_appi_compliance_summary;
DROP INDEX IF EXISTS idx_am_appi_compliance_ingest_log_started;
DROP TABLE IF EXISTS am_appi_compliance_ingest_log;
DROP INDEX IF EXISTS ux_am_appi_compliance_houjin_source;
DROP INDEX IF EXISTS idx_am_appi_compliance_refreshed;
DROP INDEX IF EXISTS idx_am_appi_compliance_status;
DROP INDEX IF EXISTS idx_am_appi_compliance_houjin;
DROP TABLE IF EXISTS am_appi_compliance;
