-- migration 248_program_source_municipality_v2 — ROLLBACK
-- target_db: autonomath
PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_msv2_run_log_started;
DROP TABLE IF EXISTS am_program_source_municipality_v2_run_log;
DROP INDEX IF EXISTS idx_msv2_pref_verified;
DROP INDEX IF EXISTS idx_msv2_muni_grant;
DROP TABLE IF EXISTS am_program_source_municipality_v2;
