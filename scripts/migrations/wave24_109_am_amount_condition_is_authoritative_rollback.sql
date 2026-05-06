-- target_db: autonomath
-- migration wave24_109_am_amount_condition_is_authoritative_rollback
--   (companion, manual-review only — NOT auto-applied)
--
-- Reverts wave24_109_am_amount_condition_is_authoritative.sql:
--   1. Drops idx_amc_authoritative.
--   2. Drops the three columns added on the forward path
--      (is_authoritative, authority_source, authority_evaluated_at)
--      via ALTER TABLE DROP COLUMN (requires SQLite ≥ 3.35; production
--      runs 3.45.x as of 2026-05-04).
--
-- WARNING — manual-review only:
--   Once `tools/offline/` operator-LLM pipelines have written authoritative
--   amount conditions tagged via these columns, dropping them silently
--   demotes every authoritative row back into the template-default soup,
--   re-exposing the §M5 trust hazard. NEVER run this in production unless
--   the operator has staged a replacement column / view that preserves
--   the same `is_authoritative` semantics.
--
-- This file is NOT auto-applied by entrypoint.sh — the loop excludes
-- *_rollback.sql by name match (see entrypoint.sh §4, same pattern as
-- wave24_105_audit_seal_key_version_rollback.sql).
--
-- Run manually:
--   sqlite3 $AUTONOMATH_DB_PATH < wave24_109_am_amount_condition_is_authoritative_rollback.sql

PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_amc_authoritative;

-- SQLite ≥ 3.35 supports DROP COLUMN, but it cannot drop a column
-- referenced by an index. The DROP INDEX above clears that path.
ALTER TABLE am_amount_condition DROP COLUMN authority_evaluated_at;
ALTER TABLE am_amount_condition DROP COLUMN authority_source;
ALTER TABLE am_amount_condition DROP COLUMN is_authoritative;
