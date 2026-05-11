-- target_db: autonomath
-- migration: 244_pdf_report_generator_rollback
-- generated_at: 2026-05-12
-- author: Wave 35 Axis 6a — rollback companion
--
-- WARNING: dropping these tables removes the operator-visible
-- subscription configuration and the audit log. Only run in DR drills
-- after exporting `am_pdf_report_subscriptions` and
-- `am_pdf_report_generation_log` to R2.

PRAGMA foreign_keys = OFF;

BEGIN;

DROP INDEX IF EXISTS idx_am_pdf_report_subscriptions_enabled_cadence;
DROP INDEX IF EXISTS idx_am_pdf_report_subscriptions_client;
DROP INDEX IF EXISTS idx_am_pdf_report_generation_log_client_started;
DROP INDEX IF EXISTS idx_am_pdf_report_generation_log_started;

DROP TABLE IF EXISTS am_pdf_report_subscriptions;
DROP TABLE IF EXISTS am_pdf_report_generation_log;

COMMIT;
