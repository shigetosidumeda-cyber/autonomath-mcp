-- target_db: autonomath
-- migration 166 rollback — am_canonical_vec_*

DROP TABLE IF EXISTS am_canonical_vec_program;
DROP TABLE IF EXISTS am_canonical_vec_program_map;
DROP TABLE IF EXISTS am_canonical_vec_enforcement;
DROP TABLE IF EXISTS am_canonical_vec_enforcement_map;
DROP TABLE IF EXISTS am_canonical_vec_corporate;
DROP TABLE IF EXISTS am_canonical_vec_corporate_map;
DROP TABLE IF EXISTS am_canonical_vec_statistic;
DROP TABLE IF EXISTS am_canonical_vec_statistic_map;
DROP TABLE IF EXISTS am_canonical_vec_case_study;
DROP TABLE IF EXISTS am_canonical_vec_case_study_map;
DROP TABLE IF EXISTS am_canonical_vec_law;
DROP TABLE IF EXISTS am_canonical_vec_law_map;
DROP TABLE IF EXISTS am_canonical_vec_tax_measure;
DROP TABLE IF EXISTS am_canonical_vec_tax_measure_map;
