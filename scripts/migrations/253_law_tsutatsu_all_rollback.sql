-- migration 253_law_tsutatsu_all — ROLLBACK
PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_tsutatsu_all_run_log_started;
DROP TABLE IF EXISTS am_law_tsutatsu_all_run_log;
DROP VIEW IF EXISTS v_tsutatsu_all_agency_density;
DROP TRIGGER IF EXISTS am_tsutatsu_all_au;
DROP TRIGGER IF EXISTS am_tsutatsu_all_ad;
DROP TRIGGER IF EXISTS am_tsutatsu_all_ai;
DROP TABLE IF EXISTS am_law_tsutatsu_all_fts;
DROP INDEX IF EXISTS idx_tsutatsu_all_hash;
DROP INDEX IF EXISTS ux_tsutatsu_all_source_url;
DROP INDEX IF EXISTS idx_tsutatsu_all_applicable_law;
DROP INDEX IF EXISTS idx_tsutatsu_all_industry;
DROP INDEX IF EXISTS idx_tsutatsu_all_issued;
DROP INDEX IF EXISTS idx_tsutatsu_all_agency;
DROP TABLE IF EXISTS am_law_tsutatsu_all;
