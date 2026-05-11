-- migration 223_am_authority_contact — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW   IF EXISTS v_am_authority_contact_surface;
DROP INDEX  IF EXISTS idx_authority_contact_tos_pending;
DROP INDEX  IF EXISTS idx_authority_contact_surface;
DROP INDEX  IF EXISTS idx_authority_contact_auth;
DROP TABLE  IF EXISTS am_authority_contact;
