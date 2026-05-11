-- migration 221_jpi_referral_event — ROLLBACK
PRAGMA foreign_keys = ON;

DROP INDEX  IF EXISTS idx_jpi_referral_utm;
DROP INDEX  IF EXISTS idx_jpi_referral_key;
DROP INDEX  IF EXISTS idx_jpi_referral_source;
DROP INDEX  IF EXISTS idx_jpi_referral_chrono;
DROP TABLE  IF EXISTS jpi_referral_event;
