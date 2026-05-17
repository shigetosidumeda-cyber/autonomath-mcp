-- target_db: autonomath
-- rollback: wave24_221_am_outcome_cohort_variant
-- generated_at: 2026-05-17
--
-- Rollback drops the view, indexes, then the table. Zero data loss
-- on the rest of the schema; the cohort-variant fan-out can be rebuilt
-- from scratch by re-running
-- scripts/aws_credit_ops/generate_cohort_outcome_variants_2026_05_17.py.

PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_outcome_cohort_variant_top;
DROP INDEX IF EXISTS ix_outcome_cohort_variant_computed_at;
DROP INDEX IF EXISTS ix_outcome_cohort_variant_cohort;
DROP INDEX IF EXISTS ix_outcome_cohort_variant_outcome_id;
DROP INDEX IF EXISTS ux_outcome_cohort_variant_tuple;
DROP TABLE IF EXISTS am_outcome_cohort_variant;
