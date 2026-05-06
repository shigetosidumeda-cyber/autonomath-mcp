-- target_db: autonomath
-- migration wave24_107_am_compat_matrix_visibility_rollback (companion, manual-review only)
--
-- Reverts wave24_107_am_compat_matrix_visibility.sql:
--   1. Drops idx_am_compat_visibility.
--   2. Drops the visibility column from am_compat_matrix (requires
--      SQLite ≥ 3.35; production is 3.45.x as of 2026-04-30).
--
-- WARNING — manual-review only:
--   Once visibility has been used by /v1/am/compat/* and the find_combinable
--   tool, dropping the column reverts every caller to "see all rows incl.
--   heuristic + unknown" by silent default. Run this only in a recovery
--   scenario (e.g. CHECK constraint accidentally rejecting a legitimate
--   visibility value); otherwise prefer a forward-fix migration.
--
-- This file is NOT auto-applied by entrypoint.sh — the loop excludes
-- *_rollback.sql by name match (see entrypoint.sh §4).
--
-- Run manually:
--   sqlite3 /data/autonomath.db < wave24_107_am_compat_matrix_visibility_rollback.sql

PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_am_compat_visibility;

ALTER TABLE am_compat_matrix DROP COLUMN visibility;
