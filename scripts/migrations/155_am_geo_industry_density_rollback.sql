-- target_db: autonomath
-- migration 155 ROLLBACK — am_geo_industry_density
--
-- Drops the matrix table. Indexes drop transitively.

PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_agid_density;
DROP INDEX IF EXISTS idx_agid_jsic;
DROP INDEX IF EXISTS idx_agid_pref;
DROP TABLE IF EXISTS am_geo_industry_density;
