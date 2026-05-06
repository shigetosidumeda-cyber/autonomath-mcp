-- target_db: autonomath
-- ROLLBACK companion for wave24_128_am_program_calendar_12mo.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_apcal_month_open;
DROP TABLE IF EXISTS am_program_calendar_12mo;
PRAGMA foreign_keys = ON;
