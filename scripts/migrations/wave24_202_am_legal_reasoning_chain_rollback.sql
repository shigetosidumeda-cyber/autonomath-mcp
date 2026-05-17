-- target_db: autonomath
-- migration: wave24_202_am_legal_reasoning_chain (rollback)
-- generated_at: 2026-05-17
--
-- Rollback companion for the Lane N3 reasoning chain table.
-- The entrypoint.sh §4 loop excludes *_rollback.sql, so this file is only
-- invoked by hand (or test fixtures) — never re-run at boot.

DROP VIEW IF EXISTS v_am_legal_reasoning_chain_confident;
DROP INDEX IF EXISTS idx_amlrc_computed;
DROP INDEX IF EXISTS idx_amlrc_category;
DROP INDEX IF EXISTS idx_amlrc_topic;
DROP TABLE IF EXISTS am_legal_reasoning_chain;
