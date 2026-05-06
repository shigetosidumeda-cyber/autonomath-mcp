-- target_db: autonomath
-- rollback for wave24_170_source_catalog
--
-- DROP VIEWS first (they depend on the table), then the table. Indexes are
-- dropped automatically when the table is dropped.
--
-- WARNING: dropping this table erases the normalized source registry. The
-- companion ETL (scripts/etl/backfill_source_catalog.py) reads from
-- 02_A_SOURCE_PROFILE.jsonl which is preserved in the inbox, so re-creation
-- is non-destructive — but `source_freshness_ledger` (171) and
-- `cross_source_signal_layer` (172) join against source_id and will lose
-- referential integrity until backfill re-runs.

DROP VIEW IF EXISTS v_source_catalog_family_rollup;
DROP VIEW IF EXISTS v_source_catalog_paid_safe;
DROP TABLE IF EXISTS source_catalog;
