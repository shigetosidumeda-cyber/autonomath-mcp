-- target_db: autonomath
-- migration 229_industry_guidelines — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW    IF EXISTS v_am_industry_guidelines_rollup;
DROP TRIGGER IF EXISTS am_ind_gl_au;
DROP TRIGGER IF EXISTS am_ind_gl_ad;
DROP TRIGGER IF EXISTS am_ind_gl_ai;
DROP TABLE   IF EXISTS am_industry_guidelines_fts;
DROP INDEX   IF EXISTS idx_am_industry_guidelines_issued;
DROP INDEX   IF EXISTS idx_am_industry_guidelines_ministry;
DROP INDEX   IF EXISTS idx_am_industry_guidelines_jsic;
DROP TABLE   IF EXISTS am_industry_guidelines;
