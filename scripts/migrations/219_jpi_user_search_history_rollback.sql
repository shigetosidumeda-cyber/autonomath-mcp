-- migration 219_jpi_user_search_history — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW   IF EXISTS v_jpi_user_history_recent;
DROP INDEX  IF EXISTS idx_jpi_user_history_deleted;
DROP INDEX  IF EXISTS idx_jpi_user_history_retention;
DROP INDEX  IF EXISTS idx_jpi_user_history_recent;
DROP TABLE  IF EXISTS jpi_user_search_history;
