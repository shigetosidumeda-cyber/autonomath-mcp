-- target_db: autonomath
-- migration 268_state_checkpoint — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_state_checkpoint_latest;
DROP INDEX IF EXISTS idx_state_checkpoint_status_expires;
DROP INDEX IF EXISTS idx_state_checkpoint_kind_committed;
DROP INDEX IF EXISTS idx_state_checkpoint_workflow;
DROP TABLE IF EXISTS am_state_checkpoint;
