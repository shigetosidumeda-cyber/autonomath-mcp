-- target_db: autonomath
-- migration: 274_anonymized_query (rollback)
-- author: Wave 47 — Dim N (anonymized_query) storage layer rollback
--
-- Rollback only drops the Dim N storage surface (audit log + aggregate
-- view table + helper view). This is irreversible for any rows already
-- inserted; intended for non-production / dev re-runs.

BEGIN;

DROP VIEW  IF EXISTS v_anon_cohort_outcomes_latest;
DROP INDEX IF EXISTS idx_am_agg_outcome_type;
DROP INDEX IF EXISTS idx_am_agg_outcome_cluster;
DROP TABLE IF EXISTS am_aggregated_outcome_view;
DROP INDEX IF EXISTS idx_am_anon_query_log_time;
DROP INDEX IF EXISTS idx_am_anon_query_log_hash;
DROP TABLE IF EXISTS am_anonymized_query_log;

COMMIT;
