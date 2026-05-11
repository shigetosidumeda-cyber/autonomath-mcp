-- target_db: autonomath
-- migration 261_legal_chain_5layer — ROLLBACK
PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_legal_chain_run_log_started;
DROP TABLE IF EXISTS am_legal_chain_run_log;
DROP VIEW  IF EXISTS v_legal_chain_public;
DROP INDEX IF EXISTS uq_legal_chain_anchor_layer_url;
DROP INDEX IF EXISTS idx_legal_chain_host;
DROP INDEX IF EXISTS idx_legal_chain_layer_date;
DROP INDEX IF EXISTS idx_legal_chain_anchor;
DROP TABLE IF EXISTS am_legal_chain;
