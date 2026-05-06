-- target_db: autonomath
-- ROLLBACK companion for wave24_113c_autonomath_houjin_master_jsic.sql
-- Excluded from entrypoint.sh §4 by the `*_rollback.sql` name fence.

PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_houjin_master_jsic_major;

-- SQLite 3.35+ DROP COLUMN. Production Fly is 3.46+.
ALTER TABLE houjin_master DROP COLUMN jsic_assigned_at;
ALTER TABLE houjin_master DROP COLUMN jsic_assigned_method;
ALTER TABLE houjin_master DROP COLUMN jsic_minor;
ALTER TABLE houjin_master DROP COLUMN jsic_middle;
ALTER TABLE houjin_master DROP COLUMN jsic_major;

PRAGMA foreign_keys = ON;
