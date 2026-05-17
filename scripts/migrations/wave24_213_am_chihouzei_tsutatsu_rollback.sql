-- target_db: autonomath
-- rollback for: wave24_213_am_chihouzei_tsutatsu

DROP VIEW IF EXISTS v_am_chihouzei_coverage;
DROP TRIGGER IF EXISTS am_chihouzei_tsutatsu_au;
DROP TRIGGER IF EXISTS am_chihouzei_tsutatsu_ad;
DROP TRIGGER IF EXISTS am_chihouzei_tsutatsu_ai;
DROP TABLE IF EXISTS am_chihouzei_tsutatsu_fts;
DROP INDEX IF EXISTS ix_am_chihouzei_crawl_run;
DROP INDEX IF EXISTS ix_am_chihouzei_effective;
DROP INDEX IF EXISTS ix_am_chihouzei_pref_tax;
DROP TABLE IF EXISTS am_chihouzei_tsutatsu;
