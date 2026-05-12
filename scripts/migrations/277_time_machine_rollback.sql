-- target_db: autonomath
-- migration: 277_time_machine (rollback)
-- author: Wave 47 — Dim Q (time_machine + counterfactual) storage rollback
--
-- Rollback drops only the Dim Q audit/log surface (monthly snapshot log,
-- counterfactual eval log, latest-snapshot view). The existing time-machine
-- index pair (wave24_180_time_machine_index.sql) and underlying
-- am_amendment_snapshot are NOT touched, since the index migration owns
-- the live time-travel hot path and is orthogonal to this audit layer.
--
-- Irreversible for any rows already inserted; intended for non-production
-- / dev re-runs.

BEGIN;

DROP VIEW  IF EXISTS v_monthly_snapshot_latest;

DROP INDEX IF EXISTS idx_am_counterfactual_eval_log_query;
DROP INDEX IF EXISTS idx_am_counterfactual_eval_log_created;
DROP INDEX IF EXISTS idx_am_counterfactual_eval_log_as_of;
DROP TABLE IF EXISTS am_counterfactual_eval_log;

DROP INDEX IF EXISTS idx_am_monthly_snapshot_log_table;
DROP INDEX IF EXISTS idx_am_monthly_snapshot_log_as_of;
DROP TABLE IF EXISTS am_monthly_snapshot_log;

COMMIT;
