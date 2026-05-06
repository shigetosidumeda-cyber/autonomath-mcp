-- target_db: autonomath
-- DOWN for migration 150_am_amount_condition_quality_tier.
--
-- Drops the index pair and the column. SQLite >= 3.35 supports
-- DROP COLUMN. entrypoint.sh §4 EXCLUDES *_rollback.sql by name match,
-- so this file is only invoked manually by the operator.

PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS ix_amount_condition_tier_verified;
DROP INDEX IF EXISTS ix_amount_condition_tier;

ALTER TABLE am_amount_condition DROP COLUMN quality_tier;
