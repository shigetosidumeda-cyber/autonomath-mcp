-- target_db: jpintel
-- migration 148_programs_jsic_majors ROLLBACK
--
-- SQLite は ALTER TABLE DROP COLUMN を 3.35+ から saport 済。
-- index は DROP INDEX IF EXISTS で安全に巻き戻す。

PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS ix_programs_jsic_majors;
ALTER TABLE programs DROP COLUMN jsic_majors;
