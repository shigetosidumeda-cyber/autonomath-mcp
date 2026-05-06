-- target_db: autonomath
-- ROLLBACK companion for wave24_130_am_case_study_similarity.sql
PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_acss_b_sim;
DROP INDEX IF EXISTS idx_acss_a_sim;
DROP TABLE IF EXISTS am_case_study_similarity;
PRAGMA foreign_keys = ON;
