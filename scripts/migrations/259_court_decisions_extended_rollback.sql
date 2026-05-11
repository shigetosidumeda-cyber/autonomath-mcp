-- target_db: autonomath
-- migration 259_court_decisions_extended — ROLLBACK
PRAGMA foreign_keys = ON;

DROP INDEX   IF EXISTS idx_court_v2_run_log_started;
DROP TABLE   IF EXISTS am_court_decisions_v2_run_log;
DROP VIEW    IF EXISTS v_am_court_decisions_v2_public;
DROP TRIGGER IF EXISTS am_court_v2_au;
DROP TRIGGER IF EXISTS am_court_v2_ad;
DROP TRIGGER IF EXISTS am_court_v2_ai;
DROP TABLE   IF EXISTS am_court_decisions_v2_fts;
DROP INDEX   IF EXISTS idx_court_v2_decision_date_only;
DROP INDEX   IF EXISTS idx_court_v2_precedent;
DROP INDEX   IF EXISTS idx_court_v2_source;
DROP INDEX   IF EXISTS idx_court_v2_fiscal_year;
DROP INDEX   IF EXISTS idx_court_v2_date_range;
DROP INDEX   IF EXISTS idx_court_v2_case_type;
DROP INDEX   IF EXISTS idx_court_v2_level_type;
DROP INDEX   IF EXISTS idx_court_v2_unified;
DROP TABLE   IF EXISTS am_court_decisions_v2;
