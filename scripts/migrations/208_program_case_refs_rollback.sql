-- target_db: autonomath
-- ROLLBACK for migration 208_program_case_refs
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_program_case_refs_created_at;
DROP INDEX IF EXISTS idx_program_case_refs_score;
DROP INDEX IF EXISTS idx_program_case_refs_case;
DROP TABLE IF EXISTS program_case_refs;
