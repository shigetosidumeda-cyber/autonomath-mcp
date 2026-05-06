-- target_db: autonomath
-- migration 170_program_decision_layer (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_apdl_action_quality;
DROP INDEX IF EXISTS idx_apdl_overlay;
DROP INDEX IF EXISTS idx_apdl_program;
DROP INDEX IF EXISTS idx_apdl_subject_scores;
DROP INDEX IF EXISTS idx_apdl_subject_rank;
DROP INDEX IF EXISTS uq_apdl_subject_program_snapshot;
DROP TABLE IF EXISTS am_program_decision_layer;
