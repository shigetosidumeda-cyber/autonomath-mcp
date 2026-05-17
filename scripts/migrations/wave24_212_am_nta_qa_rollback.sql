-- target_db: autonomath
-- rollback for: wave24_212_am_nta_qa
-- excluded from boot-time auto-apply by the `*_rollback.sql` suffix.
--
-- Forward-only is preferred. Use this only for DR drill or operator
-- decision to drop the AA1-G1 surface.

DROP VIEW IF EXISTS v_am_nta_qa_coverage;
DROP TRIGGER IF EXISTS am_nta_qa_au;
DROP TRIGGER IF EXISTS am_nta_qa_ad;
DROP TRIGGER IF EXISTS am_nta_qa_ai;
DROP TABLE IF EXISTS am_nta_qa_fts;
DROP INDEX IF EXISTS ix_am_nta_qa_crawl_run;
DROP INDEX IF EXISTS ix_am_nta_qa_category_date;
DROP INDEX IF EXISTS ix_am_nta_qa_kind_category;
DROP TABLE IF EXISTS am_nta_qa;
