-- target_db: autonomath
-- ROLLBACK companion for wave24_142_am_narrative_customer_reports.sql
-- Manual review required — dropping the customer reports table
-- destroys defect inbox history; ensure CSV export exists.

PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_nsl_recent;
DROP INDEX IF EXISTS idx_nsl_narrative_time;
DROP TABLE IF EXISTS am_narrative_serve_log;

DROP INDEX IF EXISTS idx_ncr_narrative;
DROP INDEX IF EXISTS idx_ncr_state_due;
DROP TABLE IF EXISTS am_narrative_customer_reports;

PRAGMA foreign_keys = ON;
