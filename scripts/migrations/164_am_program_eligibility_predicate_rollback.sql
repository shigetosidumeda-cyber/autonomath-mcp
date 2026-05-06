-- target_db: autonomath
-- ROLLBACK for 164_am_program_eligibility_predicate.sql
--
-- Drops the eligibility predicate JSON cache. Used only when the
-- predicate_json shape changes incompatibly. Re-run the forward migration
-- + scripts/etl/extract_eligibility_predicate.py to repopulate.

DROP INDEX IF EXISTS ix_apepj_extracted_at;
DROP INDEX IF EXISTS ix_apepj_method;
DROP TABLE IF EXISTS am_program_eligibility_predicate_json;
