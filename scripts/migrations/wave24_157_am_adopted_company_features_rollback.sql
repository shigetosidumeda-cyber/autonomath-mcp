-- target_db: autonomath
-- ROLLBACK companion for wave24_157_am_adopted_company_features.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_aacf_enforcement;
DROP INDEX IF EXISTS idx_aacf_adoption;
DROP INDEX IF EXISTS idx_aacf_credibility;
DROP TABLE IF EXISTS am_adopted_company_features;
PRAGMA foreign_keys = ON;
