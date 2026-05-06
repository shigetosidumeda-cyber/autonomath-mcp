-- target_db: jpintel
-- migration wave24_108_programs_source_verified_at_rollback (companion, manual-review only)
--
-- Reverts wave24_108_programs_source_verified_at.sql:
--   1. Drops the two freshness indexes.
--   2. Drops the three additive columns (requires SQLite ≥ 3.35; the
--      production environment is 3.45.x as of 2026-04-29).
--
-- This file is NOT auto-applied by entrypoint.sh — the loop excludes
-- *_rollback.sql by name match (see entrypoint.sh §4).
--
-- Run manually:
--   sqlite3 data/jpintel.db < wave24_108_programs_source_verified_at_rollback.sql
--
-- Operator caveat:
--   Rolling back drops every recorded verify event. The next refresh_sources.py
--   pass will repopulate `source_verified_at` from scratch, but until that
--   pass completes the median-freshness KPI query returns NULL for every
--   row. Prefer leaving the columns in place even when toggling the cron
--   off — they are NULL-safe and ignored by every legacy read path.

PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_programs_verify_freshness;
DROP INDEX IF EXISTS idx_programs_source_verified_at;

ALTER TABLE programs DROP COLUMN source_verify_method;
ALTER TABLE programs DROP COLUMN source_content_hash_at_verify;
ALTER TABLE programs DROP COLUMN source_verified_at;
