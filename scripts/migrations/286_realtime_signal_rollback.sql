-- target_db: autonomath
-- migration: 286_realtime_signal (rollback)
-- author: Wave 47 — Dim G (realtime_signal) Wave 47 layer rollback
--
-- Rollback drops only the Wave 47 layer (signal_subscriber + signal_event_log
-- + helper view). The Wave 43 base layer (migration 263) is untouched.
-- Irreversible for any rows already inserted; intended for non-production /
-- dev re-runs only.

BEGIN;

DROP VIEW  IF EXISTS v_realtime_signal_subscriber_enabled;

DROP INDEX IF EXISTS idx_am_rt_sig_event_delivered;
DROP INDEX IF EXISTS idx_am_rt_sig_event_pending;
DROP INDEX IF EXISTS idx_am_rt_sig_event_type_created;
DROP INDEX IF EXISTS idx_am_rt_sig_event_sub_created;
DROP TABLE IF EXISTS am_realtime_signal_event_log;

DROP INDEX IF EXISTS idx_am_rt_sig_sub_last_signal;
DROP INDEX IF EXISTS idx_am_rt_sig_sub_enabled;
DROP TABLE IF EXISTS am_realtime_signal_subscriber;

COMMIT;
