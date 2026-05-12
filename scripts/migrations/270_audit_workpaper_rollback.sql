-- target_db: autonomath
-- migration_rollback: 270_audit_workpaper
-- generated_at: 2026-05-12
-- author: Wave 46 dim 19 D-final
-- Notes
-- -----
-- Idempotent rollback: every DROP uses IF EXISTS. The 5 source tables
-- (jpi_houjin_master / jpi_adoption_records / am_enforcement_detail /
-- jpi_invoice_registrants / am_amendment_diff) are NOT touched — only
-- the cached snapshot table + helper view + run log are removed.

BEGIN;

DROP VIEW IF EXISTS v_audit_workpaper_cohort;
DROP INDEX IF EXISTS idx_audit_workpaper_run_log_started;
DROP INDEX IF EXISTS idx_audit_workpaper_flags;
DROP INDEX IF EXISTS idx_audit_workpaper_fy;
DROP INDEX IF EXISTS idx_audit_workpaper_houjin;
DROP TABLE IF EXISTS am_audit_workpaper_run_log;
DROP TABLE IF EXISTS am_audit_workpaper;

COMMIT;
