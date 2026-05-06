-- target_db: autonomath
-- migration 169_am_actionable_qa_cache (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_am_actionable_rendered_at;
DROP INDEX IF EXISTS idx_am_actionable_intent_hash;
DROP TABLE IF EXISTS am_actionable_qa_cache;
