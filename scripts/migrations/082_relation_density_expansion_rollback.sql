-- target_db: autonomath
-- migration 082_relation_density_expansion_rollback (companion, manual-review only)
--
-- Reverts 082_relation_density_expansion.sql:
--   1. Drops harvested rows (origin = 'harvest') from am_relation.
--   2. Drops the three indexes added by 082.
--   3. Drops the harvested_at column (requires SQLite ≥ 3.35; the
--      production environment is 3.45.x as of 2026-04-29).
--
-- This file is NOT auto-applied by entrypoint.sh — the loop excludes
-- *_rollback.sql by name match (see entrypoint.sh §4).
--
-- Run manually:
--   sqlite3 /data/autonomath.db < 082_relation_density_expansion_rollback.sql

PRAGMA foreign_keys = ON;

DELETE FROM am_relation WHERE origin = 'harvest';

DROP INDEX IF EXISTS ux_am_relation_harvest;
DROP INDEX IF EXISTS ix_am_relation_src_type_conf;
DROP INDEX IF EXISTS ix_am_relation_origin;

ALTER TABLE am_relation DROP COLUMN harvested_at;
