-- target_db: autonomath
-- migration: 264_personalization_score_rollback
-- generated_at: 2026-05-12

BEGIN;

DROP VIEW IF EXISTS v_personalization_top10;

DROP INDEX IF EXISTS idx_pers_refresh_log_started;
DROP TABLE IF EXISTS am_personalization_refresh_log;

DROP INDEX IF EXISTS idx_pers_program;
DROP INDEX IF EXISTS idx_pers_refresh;
DROP INDEX IF EXISTS idx_pers_key_client_score;
DROP TABLE IF EXISTS am_personalization_score;

COMMIT;
