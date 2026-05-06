-- target_db: jpintel
-- migration: wave24_191_municipality_subsidy_rollback
-- generated_at: 2026-05-07
-- author: DEEP-44 自治体 1,741 補助金 page weekly diff cron rollback
--
-- Rollback companion for wave24_191_municipality_subsidy.sql.
-- entrypoint.sh §3 (jpintel migrate loop) excludes *_rollback.sql files
-- so this is operator-invoked only via scripts/migrate.py --rollback.
--
-- LLM call: 0. Pure DROP statements.

DROP INDEX IF EXISTS ix_ms_status_retrieved;
DROP INDEX IF EXISTS ix_ms_sha256;
DROP INDEX IF EXISTS ix_ms_pref_muni;
DROP TABLE IF EXISTS municipality_subsidy;
