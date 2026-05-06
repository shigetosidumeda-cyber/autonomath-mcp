-- target_db: autonomath
-- ROLLBACK companion for wave24_132_am_tax_amendment_history.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_atah_year_kind;
DROP INDEX IF EXISTS idx_atah_ruleset_year;
DROP TABLE IF EXISTS am_tax_amendment_history;
PRAGMA foreign_keys = ON;
