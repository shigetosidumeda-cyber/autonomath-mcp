-- migration 216_am_program_substitute — ROLLBACK
-- Drop the view first (it references the table), then the indexes,
-- then the base table. Order matters: SQLite errors if a dependent
-- object still exists when the parent is dropped.

PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_am_program_substitute_active;
DROP INDEX IF EXISTS idx_am_program_substitute_approved;
DROP INDEX IF EXISTS idx_am_program_substitute_succ;
DROP INDEX IF EXISTS idx_am_program_substitute_pred;
DROP TABLE IF EXISTS am_program_substitute;
