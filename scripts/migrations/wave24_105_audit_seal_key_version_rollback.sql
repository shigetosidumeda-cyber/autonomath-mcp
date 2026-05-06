-- target_db: jpintel
-- migration wave24_105_audit_seal_key_version_rollback (companion, manual-review only)
--
-- Reverts wave24_105_audit_seal_key_version.sql:
--   1. Drops idx_audit_seal_key_version.
--   2. Drops the key_version column from audit_seals (requires SQLite
--      ≥ 3.35; production is 3.45.x as of 2026-04-29).
--   3. Drops the audit_seal_keys registry table.
--
-- WARNING — manual-review only:
--   Dropping audit_seal_keys after secrets have rotated leaves orphan
--   audit_seals rows (key_version > 1) that can no longer be verified
--   against the live key set. NEVER run this in production unless the
--   operator has either (a) re-keyed all live seals back to key_version=1
--   or (b) accepted that those seals will be unverifiable.
--
-- This file is NOT auto-applied by entrypoint.sh — the loop excludes
-- *_rollback.sql by name match (see entrypoint.sh §4).
--
-- Run manually:
--   sqlite3 /data/jpintel.db < wave24_105_audit_seal_key_version_rollback.sql

PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_audit_seal_key_version;

ALTER TABLE audit_seals DROP COLUMN key_version;

DROP TABLE IF EXISTS audit_seal_keys;
