-- target_db: autonomath
-- ROLLBACK for migration 210_law_amendment_refs
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_law_amendment_refs_created_at;
DROP INDEX IF EXISTS idx_law_amendment_refs_diff_type;
DROP INDEX IF EXISTS idx_law_amendment_refs_effective;
DROP INDEX IF EXISTS idx_law_amendment_refs_amendment;
DROP TABLE IF EXISTS law_amendment_refs;
