-- target_db: autonomath
-- migration: wave24_195_am_case_extracted_facts_rollback
-- generated_at: 2026-05-17
-- spec: see wave24_195_am_case_extracted_facts.sql

DROP INDEX IF EXISTS idx_amcef_jsic_year;
DROP INDEX IF EXISTS idx_amcef_amount_pref;
DROP INDEX IF EXISTS idx_amcef_case;
DROP TABLE IF EXISTS am_case_extracted_facts;
