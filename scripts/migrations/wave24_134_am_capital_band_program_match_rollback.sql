-- target_db: autonomath
-- ROLLBACK companion for wave24_134_am_capital_band_program_match.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_acbpm_program;
DROP INDEX IF EXISTS idx_acbpm_band_pct;
DROP TABLE IF EXISTS am_capital_band_program_match;
PRAGMA foreign_keys = ON;
