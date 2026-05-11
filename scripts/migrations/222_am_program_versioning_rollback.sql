-- migration 222_am_program_versioning — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW   IF EXISTS v_am_program_version_timeline;
DROP INDEX  IF EXISTS idx_program_version_major;
DROP INDEX  IF EXISTS idx_program_version_article;
DROP INDEX  IF EXISTS idx_program_version_program;
DROP INDEX  IF EXISTS uq_program_version_sv;
DROP TABLE  IF EXISTS am_program_version;
