-- target_db: autonomath
-- ROLLBACK for migration 209_case_enforcement_refs
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_case_enforcement_refs_created_at;
DROP INDEX IF EXISTS idx_case_enforcement_refs_year_ministry;
DROP INDEX IF EXISTS idx_case_enforcement_refs_enforcement;
DROP TABLE IF EXISTS case_enforcement_refs;
