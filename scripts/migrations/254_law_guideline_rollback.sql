-- migration 254_law_guideline — ROLLBACK
PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_guideline_run_log_started;
DROP TABLE IF EXISTS am_law_guideline_run_log;
DROP VIEW IF EXISTS v_guideline_industry_density;
DROP TRIGGER IF EXISTS am_guideline_au;
DROP TRIGGER IF EXISTS am_guideline_ad;
DROP TRIGGER IF EXISTS am_guideline_ai;
DROP TABLE IF EXISTS am_law_guideline_fts;
DROP INDEX IF EXISTS idx_guideline_compliance;
DROP INDEX IF EXISTS idx_guideline_hash;
DROP INDEX IF EXISTS ux_guideline_source_url;
DROP INDEX IF EXISTS idx_guideline_issued;
DROP INDEX IF EXISTS idx_guideline_industry;
DROP INDEX IF EXISTS idx_guideline_agency;
DROP INDEX IF EXISTS idx_guideline_issuer;
DROP TABLE IF EXISTS am_law_guideline;
