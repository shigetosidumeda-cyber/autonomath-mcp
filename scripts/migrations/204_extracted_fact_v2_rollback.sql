-- target_db: autonomath
-- migration 204_extracted_fact_v2 (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.
--
-- SQLite < 3.35 cannot DROP COLUMN. Indexes are dropped; columns remain in
-- place (nullable / default values keep pre-v2 readers compatible).

DROP INDEX IF EXISTS idx_extracted_fact_superseded;
DROP INDEX IF EXISTS idx_extracted_fact_status;
DROP INDEX IF EXISTS idx_extracted_fact_human_review;
DROP INDEX IF EXISTS idx_extracted_fact_stale_at;
DROP INDEX IF EXISTS idx_extracted_fact_bridge;
