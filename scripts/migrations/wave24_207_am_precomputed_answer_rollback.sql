-- target_db: autonomath
-- rollback: wave24_207_am_precomputed_answer
DROP TABLE IF EXISTS am_precomputed_answer_fts;
DROP INDEX IF EXISTS ix_am_precomputed_answer_cohort_qid;
DROP INDEX IF EXISTS ix_am_precomputed_answer_question_id;
DROP INDEX IF EXISTS ix_am_precomputed_answer_q_hash;
DROP INDEX IF EXISTS ix_am_precomputed_answer_composed_at;
DROP INDEX IF EXISTS ix_am_precomputed_answer_cite_count;
DROP INDEX IF EXISTS ix_am_precomputed_answer_freshness;
DROP INDEX IF EXISTS ix_am_precomputed_answer_cohort;
DROP TABLE IF EXISTS am_precomputed_answer;
