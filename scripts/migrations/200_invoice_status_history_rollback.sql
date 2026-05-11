-- target_db: autonomath
-- migration 200_invoice_status_history (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS ux_invoice_status_history_event;
DROP INDEX IF EXISTS idx_invoice_status_history_source;
DROP INDEX IF EXISTS idx_invoice_status_history_bridge;
DROP INDEX IF EXISTS idx_invoice_status_history_new_status;
DROP INDEX IF EXISTS idx_invoice_status_history_kind;
DROP INDEX IF EXISTS idx_invoice_status_history_houjin;
DROP INDEX IF EXISTS idx_invoice_status_history_invoice;
DROP TABLE IF EXISTS invoice_status_history;
