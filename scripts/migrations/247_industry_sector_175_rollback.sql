-- migration 247_industry_sector_175 — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_industry_sector_175_density;
DROP INDEX IF EXISTS idx_industry_sector_175_run_log_started;
DROP TABLE IF EXISTS am_industry_sector_175_run_log;
DROP INDEX IF EXISTS ux_sector_175_map_edge;
DROP INDEX IF EXISTS idx_sector_175_map_sector;
DROP INDEX IF EXISTS idx_sector_175_map_program;
DROP TABLE IF EXISTS am_program_sector_175_map;
DROP INDEX IF EXISTS idx_jsic_175_refreshed;
DROP INDEX IF EXISTS idx_jsic_175_adoption;
DROP INDEX IF EXISTS idx_jsic_175_programs;
DROP INDEX IF EXISTS idx_jsic_175_major;
DROP TABLE IF EXISTS am_industry_jsic_175;
