-- migration 218_am_pubcomment_engagement — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW   IF EXISTS v_am_pubcomment_active;
DROP INDEX  IF EXISTS idx_pubcomment_authority;
DROP INDEX  IF EXISTS idx_pubcomment_open;
DROP INDEX  IF EXISTS idx_pubcomment_program;
DROP INDEX  IF EXISTS uq_pubcomment_egov_case;
DROP TABLE  IF EXISTS am_pubcomment_engagement;
