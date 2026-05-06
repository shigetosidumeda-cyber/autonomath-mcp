-- target_db: autonomath
-- migration wave24_106_amendment_snapshot_rebuild ROLLBACK companion
--
-- Manual-review only. The entrypoint loop name-fences `*_rollback.sql`
-- (see entrypoint.sh §4 line 387-391) so this file is NEVER auto-applied
-- on Fly boot. Operators apply it manually if a regression is confirmed.
--
-- WARNING:
--   * SQLite cannot DROP a column added via ALTER TABLE without a full
--     table rebuild. We do NOT auto-rebuild am_amendment_snapshot here
--     because (a) the table holds 14,596 rows that downstream tools
--     (track_amendment_lineage_am, refresh_amendment_diff.py,
--     amendment_alert.py) read on every run and (b) a botched rebuild
--     loses the legacy corpus permanently. The two new columns
--     (`snapshot_source`, `rebuilt_at`) are non-destructive and can be
--     left in place; only the new history table is dropped.
--   * `am_program_eligibility_history` rows produced by the daily ETL
--     are LOST on rollback. There is no off-DB backup unless the operator
--     ran `r2_backup.sh` before invoking this rollback. The historical
--     records can be re-derived by re-running
--     `scripts/etl/rebuild_amendment_snapshot.py --tier S,A --window 30d`
--     after the operator decides what to do about the migration.
--
-- DOWN steps (manual):
--   1. Drop the new history table + indexes.
--   2. Leave the snapshot_source / rebuilt_at columns in place.
--      (Re-applying wave24_106 after this rollback is a no-op for the
--      ALTER TABLE lines because of the duplicate-column swallow path.)

PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_apeh_diff;
DROP INDEX IF EXISTS idx_apeh_program;
DROP TABLE IF EXISTS am_program_eligibility_history;

-- The ALTER TABLE additions are intentionally NOT rolled back. See
-- WARNING above. To strip them, the operator must rebuild
-- am_amendment_snapshot via:
--   CREATE TABLE am_amendment_snapshot__new ( <original schema, no new cols> );
--   INSERT INTO am_amendment_snapshot__new SELECT
--     snapshot_id, entity_id, version_seq, observed_at, effective_from,
--     effective_until, amount_max_yen, subsidy_rate_max, target_set_json,
--     eligibility_hash, summary_hash, source_url, source_fetched_at,
--     raw_snapshot_json
--   FROM am_amendment_snapshot;
--   DROP TABLE am_amendment_snapshot;
--   ALTER TABLE am_amendment_snapshot__new RENAME TO am_amendment_snapshot;
--   -- recreate ix_amendment_entity_obs + ix_amendment_effective indexes.
-- This is destructive — verify a fresh r2_backup.sh checkpoint first.
