-- target_db: autonomath
-- migration 202_corpus_snapshot_v2 (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.
--
-- SQLite < 3.35 cannot DROP COLUMN; this companion drops the new indexes
-- (always safe) and leaves the v2 columns in place. Rebuilding the original
-- 172 shape is an operator decision because the column data may be useful
-- even after a rollback declaration.

DROP INDEX IF EXISTS idx_corpus_snapshot_previous;
DROP INDEX IF EXISTS idx_corpus_snapshot_freshness_floor;
DROP INDEX IF EXISTS idx_corpus_snapshot_release_channel;
DROP INDEX IF EXISTS idx_corpus_snapshot_publishable;
