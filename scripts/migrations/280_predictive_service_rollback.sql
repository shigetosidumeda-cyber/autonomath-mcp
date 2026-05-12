-- target_db: autonomath
-- migration: 280_predictive_service (rollback)
-- author: Wave 47 — Dim T (predictive service) storage rollback
--
-- Rollback drops only the Dim T predictive subscription + alert log +
-- helper view. No other module owns these tables. Irreversible for any
-- rows already inserted; intended for non-production / dev re-runs.
-- The customer-facing customer_watches (mig 088) is NOT touched —
-- predictive is an operator-internal overlay.

BEGIN;

DROP VIEW  IF EXISTS v_predictive_watch_active;

DROP INDEX IF EXISTS uq_am_predictive_alert_dedup;
DROP INDEX IF EXISTS idx_am_predictive_alert_pending_age;
DROP INDEX IF EXISTS idx_am_predictive_alert_status;
DROP INDEX IF EXISTS idx_am_predictive_alert_watch;
DROP TABLE IF EXISTS am_predictive_alert_log;

DROP INDEX IF EXISTS uq_am_predictive_watch_active;
DROP INDEX IF EXISTS idx_am_predictive_watch_subscriber;
DROP INDEX IF EXISTS idx_am_predictive_watch_target;
DROP TABLE IF EXISTS am_predictive_watch_subscription;

COMMIT;
