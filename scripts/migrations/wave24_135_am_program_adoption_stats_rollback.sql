-- target_db: autonomath
-- ROLLBACK companion for wave24_135_am_program_adoption_stats.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_apas_fy_success;
DROP INDEX IF EXISTS idx_apas_program_fy;
DROP TABLE IF EXISTS am_program_adoption_stats;
PRAGMA foreign_keys = ON;
