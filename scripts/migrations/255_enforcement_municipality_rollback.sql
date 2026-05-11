-- target_db: autonomath
-- migration 255_enforcement_municipality — ROLLBACK
PRAGMA foreign_keys = ON;
DROP INDEX IF EXISTS idx_enmuni_run_log_started;
DROP TABLE IF EXISTS am_enforcement_municipality_run_log;
DROP VIEW IF EXISTS v_enforcement_municipality_public;
DROP TRIGGER IF EXISTS am_enmuni_au;
DROP TRIGGER IF EXISTS am_enmuni_ad;
DROP TRIGGER IF EXISTS am_enmuni_ai;
DROP TABLE IF EXISTS am_enforcement_municipality_fts;
DROP INDEX IF EXISTS idx_enmuni_source_host;
DROP INDEX IF EXISTS idx_enmuni_houjin;
DROP INDEX IF EXISTS idx_enmuni_agency_type;
DROP INDEX IF EXISTS idx_enmuni_action_type;
DROP INDEX IF EXISTS idx_enmuni_muni_date;
DROP INDEX IF EXISTS idx_enmuni_pref_date;
DROP INDEX IF EXISTS idx_enmuni_unified;
DROP TABLE IF EXISTS am_enforcement_municipality;
