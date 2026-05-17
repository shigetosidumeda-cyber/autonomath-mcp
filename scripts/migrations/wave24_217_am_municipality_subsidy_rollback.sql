-- target_db: autonomath
-- rollback: wave24_217_am_municipality_subsidy
-- generated_at: 2026-05-17
--
-- Drops the DD2 municipality subsidy structured corpus + 2 geo views.
-- Idempotent: every DROP uses IF EXISTS.

PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_municipality_subsidy_by_jsic_major;
DROP VIEW  IF EXISTS v_municipality_subsidy_by_prefecture;
DROP INDEX IF EXISTS ix_am_munic_subsidy_ingested;
DROP INDEX IF EXISTS ix_am_munic_subsidy_sha256;
DROP INDEX IF EXISTS ix_am_munic_subsidy_amount_max;
DROP INDEX IF EXISTS ix_am_munic_subsidy_deadline;
DROP INDEX IF EXISTS ix_am_munic_subsidy_pref;
DROP TABLE IF EXISTS am_municipality_subsidy;
