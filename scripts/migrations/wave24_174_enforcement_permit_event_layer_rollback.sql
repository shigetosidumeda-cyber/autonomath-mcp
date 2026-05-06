-- target_db: autonomath
-- rollback for wave24_174_enforcement_permit_event_layer
--
-- Drops the public view, all 6 indexes, and the table in dependency
-- order. Re-running is safe (DROP IF EXISTS).
--
-- WARNING: destructive. Take a backup of $AUTONOMATH_DB_PATH first:
--   sqlite3 autonomath.db ".backup autonomath.db.bak-pre-rollback-174"
-- Backfill ETL (scripts/etl/backfill_enforcement_event_layer.py) can
-- re-derive rows from `am_enforcement_detail` + raw nta/jftc/fsa/mhlw/
-- mlit mirror tables, but `severity` mapping + DEEP-08 anonymization
-- are recomputed and may differ from the prior population.

DROP VIEW IF EXISTS v_enforcement_event_public;
DROP INDEX IF EXISTS idx_enforcement_event_source_fetched;
DROP INDEX IF EXISTS idx_enforcement_event_receipt;
DROP INDEX IF EXISTS idx_enforcement_event_severity;
DROP INDEX IF EXISTS idx_enforcement_event_region_industry;
DROP INDEX IF EXISTS idx_enforcement_event_houjin_dated;
DROP INDEX IF EXISTS idx_enforcement_event_kind_dated;
DROP TABLE IF EXISTS enforcement_permit_event_layer;
