-- target_db: autonomath
-- ROLLBACK companion for wave24_113b_jpi_programs_jsic.sql
-- Excluded from entrypoint.sh §4 by the `*_rollback.sql` name fence.

PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_jpi_programs_jsic_middle;
DROP INDEX IF EXISTS idx_jpi_programs_jsic_major_tier;

ALTER TABLE jpi_programs DROP COLUMN jsic_assigned_method;
ALTER TABLE jpi_programs DROP COLUMN jsic_assigned_at;
ALTER TABLE jpi_programs DROP COLUMN jsic_minor;
ALTER TABLE jpi_programs DROP COLUMN jsic_middle;
ALTER TABLE jpi_programs DROP COLUMN jsic_major;

PRAGMA foreign_keys = ON;
