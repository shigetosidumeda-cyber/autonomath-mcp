-- target_db: autonomath
-- migration 172_corpus_snapshot (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_corpus_snapshot_corpus_checksum;
DROP INDEX IF EXISTS idx_corpus_snapshot_content_hash;
DROP INDEX IF EXISTS idx_corpus_snapshot_db_kind_created;
DROP TABLE IF EXISTS corpus_snapshot;
