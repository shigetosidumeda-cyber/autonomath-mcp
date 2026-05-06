-- target_db: autonomath
-- migration_rollback: wave24_187_brand_mention_rollback
-- generated_at: 2026-05-07
-- author: DEEP-41 brand mention dashboard cron (rollback companion)
--
-- Drops every object created by wave24_187_brand_mention.sql.
-- Safe to re-run: each DROP uses IF EXISTS.
--
-- ENTRYPOINT NOTE
-- ---------------
-- entrypoint.sh §4 deliberately filters out files whose names end in
-- `_rollback.sql`, so this file is NEVER applied at boot. Operator must
-- invoke it manually via:
--     sqlite3 "$AUTONOMATH_DB_PATH" \
--       < scripts/migrations/wave24_187_brand_mention_rollback.sql

PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_brand_mention_root_kpi;
DROP VIEW  IF EXISTS v_brand_mention_monthly_trend;
DROP VIEW  IF EXISTS v_brand_mention_source_rollup;
DROP INDEX IF EXISTS idx_brand_mention_kind_date;
DROP INDEX IF EXISTS idx_brand_mention_source_date;
DROP TABLE IF EXISTS brand_mention;
