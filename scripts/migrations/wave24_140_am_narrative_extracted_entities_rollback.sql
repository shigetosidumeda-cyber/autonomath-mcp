-- target_db: autonomath
-- ROLLBACK companion for wave24_140_am_narrative_extracted_entities.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_nee_kind_match;
DROP INDEX IF EXISTS idx_nee_narrative;
DROP TABLE IF EXISTS am_narrative_extracted_entities;
PRAGMA foreign_keys = ON;
