-- migration 217_am_amendment_announcement — ROLLBACK
-- Drop dependents first (view), then indexes, then base table.

PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_am_amendment_announcement_active;
DROP INDEX IF EXISTS idx_am_announcement_chrono;
DROP INDEX IF EXISTS idx_am_announcement_law;
DROP INDEX IF EXISTS idx_am_announcement_program;
DROP TABLE IF EXISTS am_amendment_announcement;
