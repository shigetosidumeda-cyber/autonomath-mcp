-- target_db: autonomath
-- ROLLBACK companion for wave24_136_am_program_narrative.sql
-- Manual review required — drops generated narrative content.

PRAGMA foreign_keys = OFF;

DROP TRIGGER IF EXISTS am_program_narrative_ad;
DROP TRIGGER IF EXISTS am_program_narrative_au;
DROP TRIGGER IF EXISTS am_program_narrative_ai;
DROP TABLE IF EXISTS am_program_narrative_fts;
DROP INDEX IF EXISTS idx_apn_program_lang;
DROP TABLE IF EXISTS am_program_narrative;

PRAGMA foreign_keys = ON;
