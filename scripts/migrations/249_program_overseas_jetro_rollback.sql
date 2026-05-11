-- migration 249_program_overseas_jetro — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_program_overseas_country_density;
DROP INDEX IF EXISTS idx_overseas_run_log_started;
DROP TABLE IF EXISTS am_overseas_run_log;
DROP INDEX IF EXISTS ux_overseas_edge;
DROP INDEX IF EXISTS idx_overseas_type;
DROP INDEX IF EXISTS idx_overseas_country;
DROP INDEX IF EXISTS idx_overseas_program;
DROP TABLE IF EXISTS am_program_overseas;
