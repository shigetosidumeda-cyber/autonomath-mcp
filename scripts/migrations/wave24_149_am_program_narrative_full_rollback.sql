-- target_db: autonomath
-- ROLLBACK companion for wave24_149_am_program_narrative_full.sql
-- Manual review required — drops generated W20 narrative cache + 反駁 bank.

PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_apnf_model_used;
DROP INDEX IF EXISTS idx_apnf_generated_at;
DROP TABLE IF EXISTS am_program_narrative_full;

PRAGMA foreign_keys = ON;
