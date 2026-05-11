-- target_db: autonomath
-- migration 265_cross_source_agreement — ROLLBACK
PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_fact_agreement_run_log_started;
DROP TABLE IF EXISTS am_fact_source_agreement_run_log;
DROP VIEW  IF EXISTS v_fact_source_agreement;
DROP INDEX IF EXISTS idx_fact_agreement_ratio;
DROP INDEX IF EXISTS idx_fact_agreement_entity_field;
DROP INDEX IF EXISTS idx_fact_agreement_fact;
DROP TABLE IF EXISTS am_fact_source_agreement;
