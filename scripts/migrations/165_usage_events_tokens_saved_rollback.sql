-- target_db: jpintel
-- migration 165_usage_events_tokens_saved (rollback)
--
-- SQLite < 3.35 cannot DROP COLUMN. We leave `tokens_saved_estimated`
-- in place; the column is nullable and unindexed, so retaining it on
-- rollback is harmless. The /v1/usage rollup tolerates NULL via
-- COALESCE(SUM(tokens_saved_estimated), 0).
--
-- This file is a placeholder so the rollback companion exists alongside
-- the forward migration (entrypoint.sh §4 excludes *_rollback.sql from
-- the autonomath self-heal loop, but the convention is enforced for
-- jpintel-target migrations too).

SELECT 1;
