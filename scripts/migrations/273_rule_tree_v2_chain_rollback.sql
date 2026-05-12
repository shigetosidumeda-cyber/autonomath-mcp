-- target_db: autonomath
-- migration: 273_rule_tree_v2_chain (rollback)
-- author: Wave 47 — Dim M (rule_tree v2 chain extension) rollback
--
-- Rollback only drops the Dim M storage surface (chain + version history).
-- This is irreversible for any rows already inserted; intended for
-- non-production / dev re-runs.

BEGIN;

DROP VIEW  IF EXISTS v_rule_tree_version_history_latest;
DROP INDEX IF EXISTS idx_am_rule_tree_version_history_hash;
DROP INDEX IF EXISTS idx_am_rule_tree_version_history_tree_seq;
DROP TABLE IF EXISTS am_rule_tree_version_history;
DROP INDEX IF EXISTS idx_am_rule_tree_chain_domain_status;
DROP TABLE IF EXISTS am_rule_tree_chain;

COMMIT;
