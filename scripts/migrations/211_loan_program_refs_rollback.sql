-- target_db: autonomath
-- ROLLBACK for migration 211_loan_program_refs
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_loan_program_refs_created_at;
DROP INDEX IF EXISTS idx_loan_program_refs_score;
DROP INDEX IF EXISTS idx_loan_program_refs_program;
DROP TABLE IF EXISTS loan_program_refs;
