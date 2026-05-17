-- target_db: autonomath
-- migration 291_am_precomputed_answer_freshness rollback.
--
-- Reverses additive freshness column adds from 291_am_precomputed_answer_freshness.sql.
-- SQLite does not support DROP COLUMN before 3.35; this rollback drops the
-- supporting indexes only. The columns remain (NULLable, default 'fresh'),
-- which is benign — readers that do not select them are unaffected.

PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS ix_am_precomputed_answer_freshness;
DROP INDEX IF EXISTS ix_am_precomputed_answer_validated;
