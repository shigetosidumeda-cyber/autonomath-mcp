-- target_db: autonomath
-- migration 228_court_decisions_extended — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW    IF EXISTS v_am_court_decisions_unified;
DROP TRIGGER IF EXISTS am_court_ext_au;
DROP TRIGGER IF EXISTS am_court_ext_ad;
DROP TRIGGER IF EXISTS am_court_ext_ai;
DROP TABLE   IF EXISTS am_court_decisions_extended_fts;
DROP INDEX   IF EXISTS idx_am_court_ext_source;
DROP INDEX   IF EXISTS idx_am_court_ext_date_range;
DROP INDEX   IF EXISTS idx_am_court_ext_case_type;
DROP INDEX   IF EXISTS idx_am_court_ext_level_type;
DROP INDEX   IF EXISTS idx_am_court_ext_unified;
DROP TABLE   IF EXISTS am_court_decisions_extended;
