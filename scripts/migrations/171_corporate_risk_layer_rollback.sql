-- target_db: autonomath
-- migration 171_corporate_risk_layer (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_acrl_subject_time;
DROP INDEX IF EXISTS idx_acrl_quality_time;
DROP INDEX IF EXISTS idx_acrl_entity;
DROP INDEX IF EXISTS idx_acrl_houjin_computed;
DROP INDEX IF EXISTS uq_acrl_subject_houjin_snapshot;
DROP TABLE IF EXISTS am_corporate_risk_layer;
