-- target_db: autonomath
-- migration 251_program_agriculture — ROLLBACK
-- Companion to 251_program_agriculture.sql (MAFF 農水省 agri / fishery cohort).
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql per CLAUDE.md
-- "Autonomath-target migrations land via entrypoint.sh" — only `migrate.py
-- rollback` / manual DR drills will execute this file.
PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_program_agri_ingest_log_started;
DROP TABLE IF EXISTS am_program_agriculture_ingest_log;

DROP VIEW  IF EXISTS v_program_agriculture_density;

DROP INDEX IF EXISTS idx_program_agri_deadline;
DROP INDEX IF EXISTS idx_program_agri_bureau;
DROP INDEX IF EXISTS idx_program_agri_program_id;
DROP INDEX IF EXISTS idx_program_agri_type;
DROP INDEX IF EXISTS ux_program_agri_maff_id;
DROP TABLE IF EXISTS am_program_agriculture;
