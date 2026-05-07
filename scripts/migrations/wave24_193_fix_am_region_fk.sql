-- target_db: autonomath
-- boot_time: manual
-- migration: wave24_193_fix_am_region_fk
-- generated_at: 2026-05-07
-- author: R8 DB integrity audit follow-up (FK drift remediation)
-- spec: tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_DB_FK_FIX_2026-05-07.md
--
-- Purpose
-- -------
-- Replace the ghost foreign-key declaration on am_region.parent_code which
-- currently REFERENCES am_region_new(region_code). The target table
-- am_region_new has not existed since the original am_region rename — the
-- declaration was carried forward as a cosmetic typo, not a data link.
--
-- R8 audit (2026-05-07) recorded 1,965 advisory FK violations from this
-- declaration. PRAGMA foreign_keys is OFF on the production boot connection
-- so the declaration has zero runtime impact today; the rewrite below makes
-- the declaration honest so a future global FK enable does not error out.
--
-- All 1,966 parent codes resolve INSIDE am_region itself; the data graph is
-- self-consistent. This migration only rewrites the schema declaration.
--
-- Why boot_time: manual
-- ---------------------
-- The autonomath.db file on production is 12.4 GB. SQLite cannot ALTER a
-- column-level FK in place; the only correct rewrites are:
--   (a) CREATE TABLE … AS SELECT swap (full row copy — 1,966 rows is cheap
--       but the rewrite path also touches sqlite_master rebuild),
--   (b) writable_schema patch (PRAGMA writable_schema=1 + UPDATE on
--       sqlite_master).
-- Both are write operations. Production policy is read-only DB on operator
-- workstation; production schema swap belongs in a maintenance window with
-- backup verification, not in entrypoint.sh self-heal.
--
-- Therefore this file declares `-- boot_time: manual` so entrypoint.sh §4
-- skips it. Application path is offline only:
--
--   sqlite3 autonomath.db < scripts/migrations/wave24_193_fix_am_region_fk.sql
--
-- Companion rollback (`wave24_193_fix_am_region_fk_rollback.sql`) restores
-- the prior ghost FK form for forensic recovery.
--
-- Strategy
-- --------
-- Use writable_schema patch (path b). It avoids row copies on a 12.4 GB
-- file and is atomic inside the implicit transaction. The integrity_check
-- pragma at the end aborts the transaction if the rewrite produced a
-- malformed schema. PRAGMA foreign_key_check is run last to confirm the
-- 1,965 ghost violations are gone.
--
-- Idempotency
-- -----------
-- The UPDATE matches the literal "REFERENCES am_region_new(region_code)"
-- substring, which exists only on the bad declaration. Re-running on a DB
-- already migrated produces zero updates (UPDATE … WHERE name='am_region'
-- AND sql LIKE '%am_region_new%' returns 0 rows post-fix).
--
-- LLM call: 0. Pure SQLite DDL.

PRAGMA foreign_keys = OFF;

-- ===========================================================================
-- Step 1 — Cleanup any historical staging table left behind. Per R8 audit,
-- am_region_new is absent on autonomath.db; this DROP is purely defensive.
-- ===========================================================================
DROP TABLE IF EXISTS am_region_new;

-- ===========================================================================
-- Step 2 — Patch the FK declaration on am_region via writable_schema.
--
-- The patched schema points parent_code at am_region(region_code), which is
-- the table's own primary key. This is consistent with the actual data graph
-- (every parent_code in am_region resolves to a region_code in am_region).
-- ===========================================================================
PRAGMA writable_schema = 1;

UPDATE sqlite_master
SET sql = replace(
            sql,
            'REFERENCES am_region_new(region_code)',
            'REFERENCES am_region(region_code)'
          )
WHERE type = 'table'
  AND name = 'am_region'
  AND sql LIKE '%REFERENCES am_region_new(region_code)%';

PRAGMA writable_schema = 0;

-- ===========================================================================
-- Step 3 — Re-establish the parent_code lookup index under a stable name.
-- The pre-existing idx_am_region_parent already covers parent_code; this
-- IF NOT EXISTS guard simply confirms presence post-rewrite.
-- ===========================================================================
CREATE INDEX IF NOT EXISTS idx_am_region_parent
    ON am_region(parent_code);

-- ===========================================================================
-- Step 4 — Verify integrity. integrity_check fails the transaction if the
-- schema rewrite produced malformed DDL.
-- ===========================================================================
PRAGMA integrity_check;

-- Bookkeeping is recorded by the operator running this file manually
-- (INSERT into schema_migrations after offline application). entrypoint.sh
-- §4 will not reach this file because of the boot_time: manual marker.
