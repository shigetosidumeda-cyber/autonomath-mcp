-- target_db: autonomath
-- ROLLBACK companion for wave24_137_am_program_eligibility_predicate.sql
PRAGMA foreign_keys = OFF;
DROP VIEW IF EXISTS v_am_program_required_predicates;
DROP INDEX IF EXISTS idx_apep_kind_value;
DROP INDEX IF EXISTS idx_apep_program_kind;
DROP INDEX IF EXISTS uq_apep_predicate;
DROP INDEX IF EXISTS idx_apep_unique_predicate;
DROP TABLE IF EXISTS am_program_eligibility_predicate;
PRAGMA foreign_keys = ON;
