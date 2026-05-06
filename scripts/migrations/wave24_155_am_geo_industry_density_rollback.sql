-- target_db: autonomath
-- ROLLBACK for wave24_155_am_geo_industry_density.
--
-- We DO NOT drop am_geo_industry_density here because it predates
-- this migration (legacy shape was created by an earlier wave with
-- one extra column). Removing the seed admin JSIC buckets is safe.

DELETE FROM am_industry_jsic WHERE jsic_code IN ('U','V');

-- If you really want to drop the density table itself, uncomment:
-- DROP INDEX IF EXISTS idx_agid_density;
-- DROP INDEX IF EXISTS idx_agid_jsic;
-- DROP INDEX IF EXISTS idx_agid_pref;
-- DROP TABLE IF EXISTS am_geo_industry_density;
