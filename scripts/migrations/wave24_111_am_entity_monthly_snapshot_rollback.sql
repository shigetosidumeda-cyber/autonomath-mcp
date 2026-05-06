-- target_db: autonomath
-- ROLLBACK companion for wave24_111_am_entity_monthly_snapshot.sql
-- Excluded from entrypoint.sh §4 by the `*_rollback.sql` name fence.
--
-- Manual review required. Dropping `am_entity_monthly_snapshot`
-- destroys irrecoverable historical state — there is no replayable
-- source for the snapshots once they are taken. Confirm offsite
-- backup exists before running.

PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_aems_entity_month;
DROP INDEX IF EXISTS idx_aems_month_kind;
DROP TABLE IF EXISTS am_entity_monthly_snapshot;

PRAGMA foreign_keys = ON;
