-- target_db: autonomath
-- rollback for: wave24_214_am_tax_amendment_history

DROP VIEW IF EXISTS v_am_tax_amendment_coverage;
DROP TRIGGER IF EXISTS am_tax_amendment_history_au;
DROP TRIGGER IF EXISTS am_tax_amendment_history_ad;
DROP TRIGGER IF EXISTS am_tax_amendment_history_ai;
DROP TABLE IF EXISTS am_tax_amendment_history_fts;
DROP INDEX IF EXISTS ix_am_tax_amendment_statute;
DROP INDEX IF EXISTS ix_am_tax_amendment_crawl_run;
DROP INDEX IF EXISTS ix_am_tax_amendment_effective;
DROP INDEX IF EXISTS ix_am_tax_amendment_fy_tax;
DROP TABLE IF EXISTS am_tax_amendment_history;
