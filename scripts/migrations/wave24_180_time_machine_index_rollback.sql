-- target_db: autonomath
-- ROLLBACK for wave24_180_time_machine_index (DEEP-22 / CL-01).
--
-- Drops only the indexes added by the forward migration. The base table
-- am_amendment_snapshot predates this migration; never dropped here.

DROP INDEX IF EXISTS ix_am_amendment_snapshot_entity_effective;
DROP INDEX IF EXISTS ix_am_amendment_snapshot_entity_version;
DROP INDEX IF EXISTS ix_am_amendment_snapshot_quality;
DROP INDEX IF EXISTS ix_am_amendment_snapshot_eligibility_hash;
