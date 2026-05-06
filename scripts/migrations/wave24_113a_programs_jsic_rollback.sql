-- target_db: jpintel
-- ROLLBACK companion for wave24_113a_programs_jsic.sql
-- Excluded from entrypoint.sh §4 by the `*_rollback.sql` name fence.

PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_houjin_master_jsic_major;
DROP INDEX IF EXISTS idx_programs_jsic_middle;
DROP INDEX IF EXISTS idx_programs_jsic_major_tier;

-- SQLite 3.35+ DROP COLUMN. Production Fly is 3.46+.
ALTER TABLE houjin_master DROP COLUMN jsic_assigned_method;
ALTER TABLE houjin_master DROP COLUMN jsic_assigned_at;
ALTER TABLE houjin_master DROP COLUMN jsic_minor;
ALTER TABLE houjin_master DROP COLUMN jsic_middle;
ALTER TABLE houjin_master DROP COLUMN jsic_major;

ALTER TABLE programs DROP COLUMN jsic_assigned_method;
ALTER TABLE programs DROP COLUMN jsic_assigned_at;
ALTER TABLE programs DROP COLUMN jsic_minor;
ALTER TABLE programs DROP COLUMN jsic_middle;
ALTER TABLE programs DROP COLUMN jsic_major;

PRAGMA foreign_keys = ON;
