-- target_db: autonomath
-- ROLLBACK for migration 207_program_law_refs
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_program_law_refs_created_at;
DROP INDEX IF EXISTS idx_program_law_refs_kind;
DROP INDEX IF EXISTS idx_program_law_refs_law;
DROP TABLE IF EXISTS program_law_refs;
