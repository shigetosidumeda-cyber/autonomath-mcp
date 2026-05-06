-- target_db: autonomath
-- ROLLBACK companion for wave24_129_am_enforcement_industry_risk.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_aeir_region_cat;
DROP INDEX IF EXISTS idx_aeir_jsic_region;
DROP TABLE IF EXISTS am_enforcement_industry_risk;
PRAGMA foreign_keys = ON;
