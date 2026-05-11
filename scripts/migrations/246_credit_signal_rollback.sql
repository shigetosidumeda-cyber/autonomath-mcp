-- migration 246_credit_signal — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_credit_signal_worst;
DROP INDEX IF EXISTS idx_am_credit_signal_run_log_started;
DROP TABLE IF EXISTS am_credit_signal_run_log;
DROP INDEX IF EXISTS idx_am_credit_signal_agg_refreshed;
DROP INDEX IF EXISTS idx_am_credit_signal_agg_score;
DROP TABLE IF EXISTS am_credit_signal_aggregate;
DROP INDEX IF EXISTS ux_am_credit_signal_dedupe;
DROP INDEX IF EXISTS idx_am_credit_signal_severity;
DROP INDEX IF EXISTS idx_am_credit_signal_type;
DROP INDEX IF EXISTS idx_am_credit_signal_houjin;
DROP TABLE IF EXISTS am_credit_signal;
