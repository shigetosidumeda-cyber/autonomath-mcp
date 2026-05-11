-- target_db: autonomath
-- migration 266_fdi_country_80 — ROLLBACK
PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_fdi_country_run_log_started;
DROP TABLE IF EXISTS am_fdi_country_run_log;
DROP VIEW  IF EXISTS v_fdi_country_public;
DROP INDEX IF EXISTS idx_fdi_country_asean;
DROP INDEX IF EXISTS idx_fdi_country_oecd;
DROP INDEX IF EXISTS idx_fdi_country_g7;
DROP INDEX IF EXISTS idx_fdi_country_region;
DROP INDEX IF EXISTS idx_fdi_country_iso;
DROP TABLE IF EXISTS am_fdi_country;
