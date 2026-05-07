-- target_db: jpintel
-- migration: wave24_194_amendment_alert_subscriptions_rollback
-- generated_at: 2026-05-07
-- author: R8 amendment-alert subscription feed (jpcite v0.3.4)
--
-- Forensic rollback for wave24_194. Drops the new amendment_alert_subscriptions
-- table and its two indexes. Companion file is excluded from
-- entrypoint.sh §4 self-heal because the filename ends in `_rollback.sql`.
--
-- Application path is offline only:
--   sqlite3 data/jpintel.db < scripts/migrations/wave24_194_amendment_alert_subscriptions_rollback.sql
--
-- LLM call: 0. Pure SQLite DDL.

PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS idx_amendment_alert_sub_active;
DROP INDEX IF EXISTS idx_amendment_alert_sub_key;
DROP TABLE IF EXISTS amendment_alert_subscriptions;
