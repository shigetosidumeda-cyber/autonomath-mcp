-- target_db: autonomath
-- migration 168_am_actionable_answer_cache (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS ix_actionable_cache_kind;
DROP TABLE IF EXISTS am_actionable_answer_cache;
