-- target_db: autonomath
-- boot_time: manual
-- rollback: wave24_193_fix_am_region_fk
-- generated_at: 2026-05-07
--
-- Restores the prior ghost FK form (REFERENCES am_region_new) on
-- am_region.parent_code. Forensic recovery only — applying this rollback
-- re-introduces the 1,965 advisory FK violations.
--
-- Apply offline (manual review):
--   sqlite3 autonomath.db < scripts/migrations/wave24_193_fix_am_region_fk_rollback.sql

PRAGMA foreign_keys = OFF;

PRAGMA writable_schema = 1;

UPDATE sqlite_master
SET sql = replace(
            sql,
            'REFERENCES am_region(region_code)',
            'REFERENCES am_region_new(region_code)'
          )
WHERE type = 'table'
  AND name = 'am_region'
  AND sql LIKE '%REFERENCES am_region(region_code)%';

PRAGMA writable_schema = 0;

PRAGMA integrity_check;
