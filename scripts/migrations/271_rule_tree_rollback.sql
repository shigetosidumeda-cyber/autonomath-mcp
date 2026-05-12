-- target_db: autonomath
-- migration: 271_rule_tree (rollback)
-- author: Wave 47 — Dim K (rule_tree_branching) storage layer rollback
--
-- Rollback only drops the Dim K storage surface (catalogue + audit log).
-- This is irreversible for any rows already inserted; intended for
-- non-production / dev re-runs.

BEGIN;

DROP VIEW  IF EXISTS v_rule_trees_latest;
DROP INDEX IF EXISTS idx_am_rule_tree_eval_log_input_hash;
DROP INDEX IF EXISTS idx_am_rule_tree_eval_log_tree_time;
DROP TABLE IF EXISTS am_rule_tree_eval_log;
DROP INDEX IF EXISTS idx_am_rule_trees_domain_status;
DROP INDEX IF EXISTS idx_am_rule_trees_tree_version;
DROP TABLE IF EXISTS am_rule_trees;

COMMIT;
