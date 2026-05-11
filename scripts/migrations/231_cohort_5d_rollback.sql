-- migration 231_cohort_5d — ROLLBACK
PRAGMA foreign_keys = ON;

DROP VIEW   IF EXISTS v_cohort_5d_top;
DROP INDEX  IF EXISTS ux_cohort_5d_tuple;
DROP INDEX  IF EXISTS idx_cohort_5d_refresh;
DROP INDEX  IF EXISTS idx_cohort_5d_houjin;
DROP INDEX  IF EXISTS idx_cohort_5d_jbp;
DROP TABLE  IF EXISTS am_cohort_5d;
