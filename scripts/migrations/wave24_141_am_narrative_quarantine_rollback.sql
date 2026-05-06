-- target_db: autonomath
-- ROLLBACK companion for wave24_141_am_narrative_quarantine.sql
-- Manual review required. Dropping is_active will let any
-- legacy serve-path queries that never filtered by is_active
-- start returning quarantined rows.

PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_alas_active;
DROP INDEX IF EXISTS idx_acsn_active;
DROP INDEX IF EXISTS idx_aes_active;
DROP INDEX IF EXISTS idx_ah360n_active;
DROP INDEX IF EXISTS idx_apn_active;
DROP INDEX IF EXISTS uq_alas_article_lang;
DROP INDEX IF EXISTS idx_alas_unique_article_lang;

-- SQLite 3.35+ DROP COLUMN.
ALTER TABLE am_law_article_summary DROP COLUMN content_hash;
ALTER TABLE am_law_article_summary DROP COLUMN quarantine_id;
ALTER TABLE am_law_article_summary DROP COLUMN is_active;

ALTER TABLE am_case_study_narrative DROP COLUMN content_hash;
ALTER TABLE am_case_study_narrative DROP COLUMN quarantine_id;
ALTER TABLE am_case_study_narrative DROP COLUMN is_active;

ALTER TABLE am_enforcement_summary DROP COLUMN content_hash;
ALTER TABLE am_enforcement_summary DROP COLUMN quarantine_id;
ALTER TABLE am_enforcement_summary DROP COLUMN is_active;

ALTER TABLE am_houjin_360_narrative DROP COLUMN content_hash;
ALTER TABLE am_houjin_360_narrative DROP COLUMN quarantine_id;
ALTER TABLE am_houjin_360_narrative DROP COLUMN is_active;

ALTER TABLE am_program_narrative DROP COLUMN content_hash;
ALTER TABLE am_program_narrative DROP COLUMN quarantine_id;
ALTER TABLE am_program_narrative DROP COLUMN is_active;

-- Drop the stub tables created here. NOTE: if the offline ETL
-- has already populated them, this destroys data. Confirm offsite
-- backup before running.
DROP TABLE IF EXISTS am_law_article_summary;
DROP TABLE IF EXISTS am_case_study_narrative;
DROP TABLE IF EXISTS am_enforcement_summary;
DROP TABLE IF EXISTS am_houjin_360_narrative;

DROP INDEX IF EXISTS idx_anq_unresolved;
DROP INDEX IF EXISTS idx_anq_state;
DROP TABLE IF EXISTS am_narrative_quarantine;

PRAGMA foreign_keys = ON;
