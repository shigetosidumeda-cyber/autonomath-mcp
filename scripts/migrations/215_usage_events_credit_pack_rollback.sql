-- migration 215_usage_events_credit_pack — ROLLBACK
-- SQLite cannot DROP COLUMN before 3.35; this rollback drops the
-- supporting index only. Dropping the column itself requires a table
-- rebuild and is out of scope for an automated rollback — handled by an
-- operator-supervised migration on the unlikely path that the column
-- must be removed.

PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_usage_events_credit_pack;
