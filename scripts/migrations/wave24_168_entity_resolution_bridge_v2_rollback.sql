-- target_db: autonomath
-- migration wave24_168_entity_resolution_bridge_v2 ROLLBACK
--
-- The leading `_rollback` suffix on the filename excludes this from
-- entrypoint.sh §4 auto-discovery (which globs `scripts/migrations/*.sql`
-- and filters out *_rollback.sql per CLAUDE.md "Common gotchas").
-- Marker is `autonomath` (matches its forward partner) so the verifier's
-- ROLLBACK_PAIR_MARKER_MISMATCH check passes; the *_rollback.sql filename
-- fence is what keeps this off the auto-apply path.
--
-- Rollback only runs operator-side, manually:
--
--   sqlite3 $AUTONOMATH_DB_PATH \
--     < scripts/migrations/wave24_168_entity_resolution_bridge_v2_rollback.sql
--
-- Effect
-- ------
-- Drops the `v_entity_resolution_public` view, all 6 indexes, and the
-- `entity_resolution_bridge_v2` table itself. After the rollback the
-- backfill ETL must be re-run to restore data.
--
-- IF NOT EXISTS / IF EXISTS guards make the rollback idempotent —
-- re-running on a DB that is already rolled back is a no-op.
--
-- WARNING
-- -------
-- Rolling back DESTROYS every row that the backfill ETL produced. Only run
-- this when the operator has accepted that loss (e.g. corrupted backfill
-- pass that re-runs cleaner from scratch).

PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_entity_resolution_public;

DROP INDEX IF EXISTS idx_entity_resolution_bridge_v2_dispute;
DROP INDEX IF EXISTS idx_entity_resolution_bridge_v2_confidence;
DROP INDEX IF EXISTS idx_entity_resolution_bridge_v2_name;
DROP INDEX IF EXISTS idx_entity_resolution_bridge_v2_edinet;
DROP INDEX IF EXISTS idx_entity_resolution_bridge_v2_invoice;
DROP INDEX IF EXISTS idx_entity_resolution_bridge_v2_houjin;

DROP TABLE IF EXISTS entity_resolution_bridge_v2;
