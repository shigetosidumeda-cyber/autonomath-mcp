-- target_db: autonomath
-- migration 230_nta_tsutatsu_extended — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW    IF EXISTS v_am_nta_tsutatsu_sections;
DROP TRIGGER IF EXISTS am_nta_ts_ext_au;
DROP TRIGGER IF EXISTS am_nta_ts_ext_ad;
DROP TRIGGER IF EXISTS am_nta_ts_ext_ai;
DROP TABLE   IF EXISTS am_nta_tsutatsu_extended_fts;
DROP INDEX   IF EXISTS idx_am_nta_tsutatsu_ext_canonical;
DROP INDEX   IF EXISTS idx_am_nta_tsutatsu_ext_law_join;
DROP INDEX   IF EXISTS idx_am_nta_tsutatsu_ext_parent_code;
DROP INDEX   IF EXISTS idx_am_nta_tsutatsu_ext_parent;
DROP TABLE   IF EXISTS am_nta_tsutatsu_extended;
