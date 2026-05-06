-- target_db: autonomath
-- rollback for wave24_173_invoice_status_history
--
-- Purpose: emergency reversal. Drops the view + indexes + table in
-- dependency order. Re-running is safe (DROP IF EXISTS).
--
-- WARNING: this is destructive. All history rows are lost. Take a
-- backup of $AUTONOMATH_DB_PATH first:
--   sqlite3 autonomath.db ".backup autonomath.db.bak-pre-rollback-173"
-- The companion backfill ETL (scripts/etl/backfill_invoice_status_history.py)
-- can re-derive history from `invoice_registrants` snapshots + raw
-- nta_invoice_* mirror tables, but only as far back as the earliest
-- mirror snapshot. Pre-snapshot history is NOT recoverable.

DROP VIEW IF EXISTS v_invoice_status_history_public;
DROP INDEX IF EXISTS idx_invoice_status_history_cause;
DROP INDEX IF EXISTS idx_invoice_status_history_receipt;
DROP INDEX IF EXISTS idx_invoice_status_history_houjin_changed;
DROP INDEX IF EXISTS idx_invoice_status_history_t_changed;
DROP TABLE IF EXISTS invoice_status_history;
