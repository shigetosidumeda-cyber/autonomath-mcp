-- target_db: autonomath
-- ROLLBACK companion for wave24_127_am_program_combinations.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_apc_b;
DROP INDEX IF EXISTS idx_apc_a;
DROP TABLE IF EXISTS am_program_combinations;
PRAGMA foreign_keys = ON;
