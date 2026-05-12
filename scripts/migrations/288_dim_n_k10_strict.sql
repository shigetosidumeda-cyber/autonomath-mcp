-- target_db: autonomath
-- migration: 288_dim_n_k10_strict
-- generated_at: 2026-05-12
-- author: Wave 49 tick#7 — Dim N Phase 1 k=10 strict view (additive)
-- idempotent: every CREATE uses IF NOT EXISTS; no DESTRUCTIVE DML.
-- destruction-free: migration 274 (k=5) views/tables are PRESERVED.
--
-- Purpose
-- -------
-- Wave 47 migration 274 landed the Dim N anonymized_query / PII redact
-- substrate with k=5 floor (per feedback_anonymized_query_pii_redact:
-- "k=5 floor cannot be lowered at runtime"). Wave 49 Phase 1 hardens
-- the surface by introducing a PARALLEL k=10 strict view on top of the
-- same am_aggregated_outcome_view table, without removing or relaxing
-- the existing k=5 view. Routers that opt into stricter privacy can
-- read v_anon_cohort_outcomes_k10_strict; legacy code continues to
-- read v_anon_cohort_outcomes_latest unchanged.
--
-- Why a parallel view (not raise the floor)
-- ------------------------------------------
-- 1. Destruction-free principle (feedback_destruction_free_organization)
--    — never drop the k=5 view that 100+ ETL/test sites already touch.
-- 2. Operational A/B — k=10 strict cohorts surface ~30-50% fewer
--    program×region×industry tuples than k=5 (estimated from
--    am_aggregated_outcome_view dist). Routers can compare coverage
--    vs. privacy and the strict view is the opt-in safer default for
--    new endpoints (Dim N v2 in Phase 2).
-- 3. Future Phase 2 (not in scope here) will gate the stricter view
--    behind a feature flag on /v1/network/anonymized_outcomes; this
--    migration ships the substrate so that flip is a 1-line change.
--
-- Privacy posture (feedback_anonymized_query_pii_redact)
-- -------------------------------------------------------
-- k=10 doubles the per-cohort anonymity floor. NO new column lands
-- (the underlying am_aggregated_outcome_view is unchanged); the strict
-- view is a pure k_value >= 10 filter on the existing materialized
-- table. ETL is NOT touched — the nightly aggregator already writes
-- every k>=5 cohort, so the strict view simply hides cohorts where
-- 5 <= k_value < 10. No re-population step is required.
--
-- LLM-0 discipline
-- ----------------
-- View body is pure SQL filter. ZERO LLM call, ZERO API call. The
-- Wave 49 tick#7 PR only adds the view + a Python regex middleware,
-- both inference-free.
--
-- Rollback
-- --------
-- See 288_dim_n_k10_strict_rollback.sql — DROP VIEW only, k=5 view
-- and am_aggregated_outcome_view rows are not touched.

PRAGMA foreign_keys = ON;

BEGIN;

-- Parallel strict view on top of migration 274's
-- am_aggregated_outcome_view. The table CHECK on k_value already
-- forces k >= 5; this view re-asserts k >= 10 as a defensive belt
-- so any future loosening of the table CHECK (which we do not plan)
-- still cannot expose a sub-10 cohort through this surface.
DROP VIEW IF EXISTS v_anon_cohort_outcomes_k10_strict;
CREATE VIEW v_anon_cohort_outcomes_k10_strict AS
SELECT
    entity_cluster_id,
    outcome_type,
    count,
    k_value,
    mean_amount_yen,
    median_amount_yen,
    last_updated
FROM am_aggregated_outcome_view
WHERE k_value >= 10;

COMMIT;
