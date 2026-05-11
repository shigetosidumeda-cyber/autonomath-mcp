-- migration 252_law_jorei_pref — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_law_jorei_pref_density;
DROP INDEX IF EXISTS idx_jorei_pref_run_log_started;
DROP TABLE IF EXISTS am_law_jorei_pref_run_log;
DROP TABLE IF EXISTS am_law_jorei_pref_fts;
DROP INDEX IF EXISTS idx_jorei_pref_title;
DROP INDEX IF EXISTS idx_jorei_pref_fetched;
DROP INDEX IF EXISTS idx_jorei_pref_kind;
DROP INDEX IF EXISTS idx_jorei_pref_law;
DROP INDEX IF EXISTS idx_jorei_pref_code;
DROP TABLE IF EXISTS am_law_jorei_pref;
