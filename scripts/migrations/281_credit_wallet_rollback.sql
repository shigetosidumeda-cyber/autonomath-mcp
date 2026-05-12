-- target_db: autonomath
-- migration: 281_credit_wallet (rollback)
-- author: Wave 47 — Dim U (Agent Credit Wallet) storage rollback
--
-- Rollback drops only the Dim U wallet / ledger / alert surface.
-- No other module owns these tables. Irreversible for any rows
-- already inserted; intended for non-production / dev re-runs only.

BEGIN;

DROP VIEW  IF EXISTS v_credit_wallet_topup_due;

DROP INDEX IF EXISTS idx_am_credit_spending_alert_cycle;
DROP INDEX IF EXISTS idx_am_credit_spending_alert_wallet;
DROP TABLE IF EXISTS am_credit_spending_alert;

DROP INDEX IF EXISTS idx_am_credit_transaction_log_type;
DROP INDEX IF EXISTS idx_am_credit_transaction_log_wallet;
DROP TABLE IF EXISTS am_credit_transaction_log;

DROP INDEX IF EXISTS idx_am_credit_wallet_enabled;
DROP INDEX IF EXISTS idx_am_credit_wallet_owner;
DROP TABLE IF EXISTS am_credit_wallet;

COMMIT;
