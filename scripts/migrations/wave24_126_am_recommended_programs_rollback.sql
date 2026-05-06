-- target_db: autonomath
-- ROLLBACK companion for wave24_126_am_recommended_programs.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_arp_program;
DROP INDEX IF EXISTS idx_arp_houjin_rank;
DROP TABLE IF EXISTS am_recommended_programs;
PRAGMA foreign_keys = ON;
