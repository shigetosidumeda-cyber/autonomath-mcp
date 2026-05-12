-- target_db: autonomath
-- migration: 282_x402_payment (rollback)
-- author: Wave 47 — Dim V (x402 protocol micropayment) storage rollback
--
-- Rollback drops only the Dim V x402 micropayment additions (endpoint
-- config, payment log, enabled-endpoint helper view). Does NOT touch
-- the legacy inline-CREATE x402_tx_bind table owned by billing_v2.py.
-- Irreversible for any rows already inserted; intended for non-production
-- / dev re-runs only.

BEGIN;

DROP VIEW  IF EXISTS v_x402_endpoint_enabled;

DROP INDEX IF EXISTS idx_am_x402_payment_log_time;
DROP INDEX IF EXISTS idx_am_x402_payment_log_payer;
DROP INDEX IF EXISTS idx_am_x402_payment_log_endpoint;
DROP TABLE IF EXISTS am_x402_payment_log;

DROP INDEX IF EXISTS idx_am_x402_endpoint_config_enabled;
DROP TABLE IF EXISTS am_x402_endpoint_config;

COMMIT;
