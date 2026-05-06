-- target_db: autonomath
-- ROLLBACK companion for wave24_138_am_program_documents.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_apd_program_required;
DROP INDEX IF EXISTS uq_apd_document;
DROP INDEX IF EXISTS idx_apd_unique_document;
DROP TABLE IF EXISTS am_program_documents;
PRAGMA foreign_keys = ON;
