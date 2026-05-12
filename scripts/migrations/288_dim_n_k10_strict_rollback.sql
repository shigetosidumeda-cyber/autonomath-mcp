-- target_db: autonomath
-- migration: 288_dim_n_k10_strict_rollback
-- generated_at: 2026-05-12
-- author: Wave 49 tick#7 — Dim N Phase 1 k=10 strict view rollback
-- idempotent: DROP IF EXISTS.
--
-- Rolls back ONLY the parallel k=10 strict view. The k=5 view
-- (v_anon_cohort_outcomes_latest) and the underlying table
-- (am_aggregated_outcome_view) from migration 274 are NOT touched.

PRAGMA foreign_keys = ON;

BEGIN;

DROP VIEW IF EXISTS v_anon_cohort_outcomes_k10_strict;

COMMIT;
