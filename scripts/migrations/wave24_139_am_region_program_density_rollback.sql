-- target_db: autonomath
-- ROLLBACK companion for wave24_139_am_region_program_density.sql
-- NOTE: the base am_region_program_density table is also referenced
-- by wave24_112 — coordinate the rollback if both migrations are
-- being reverted together.

PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_arpdb_program;
DROP INDEX IF EXISTS idx_arpdb_region_jsic;
DROP TABLE IF EXISTS am_region_program_density_breakdown;

DROP INDEX IF EXISTS idx_arpd_jsic;
DROP INDEX IF EXISTS idx_arpd_region;
DROP TABLE IF EXISTS am_region_program_density;

PRAGMA foreign_keys = ON;
