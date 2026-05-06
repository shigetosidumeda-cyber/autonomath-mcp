-- target_db: autonomath
-- rollback: wave24_181_verify_log
-- WARNING: drops verify_log audit history. Only run after exporting to R2.

DROP INDEX IF EXISTS ix_verify_log_boundary_count;
DROP INDEX IF EXISTS ix_verify_log_score;
DROP INDEX IF EXISTS ix_verify_log_api_key_id;
DROP INDEX IF EXISTS ix_verify_log_answer_hash;
DROP INDEX IF EXISTS ix_verify_log_created_at;
DROP TABLE IF EXISTS verify_log;
