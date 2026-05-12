-- target_db: autonomath
-- migration 267_dlq — ROLLBACK
PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_dlq_drain_log_started;
DROP TABLE IF EXISTS dlq_drain_log;
DROP VIEW  IF EXISTS v_am_dlq_quarantine_summary;
DROP INDEX IF EXISTS idx_am_dlq_replay_run;
DROP INDEX IF EXISTS idx_am_dlq_source_kind_kind;
DROP INDEX IF EXISTS idx_am_dlq_status_abandoned;
DROP TABLE IF EXISTS am_dlq;
