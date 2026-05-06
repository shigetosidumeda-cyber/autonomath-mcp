-- target_db: autonomath
-- migration 175_extracted_fact (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_extracted_fact_confidence;
DROP INDEX IF EXISTS idx_extracted_fact_observed;
DROP INDEX IF EXISTS idx_extracted_fact_field_kind;
DROP INDEX IF EXISTS idx_extracted_fact_snapshot;
DROP INDEX IF EXISTS idx_extracted_fact_source_document;
DROP INDEX IF EXISTS idx_extracted_fact_entity;
DROP INDEX IF EXISTS idx_extracted_fact_subject_field;
DROP TABLE IF EXISTS extracted_fact;
