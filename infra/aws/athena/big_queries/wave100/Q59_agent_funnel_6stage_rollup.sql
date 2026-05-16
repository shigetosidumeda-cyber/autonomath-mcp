-- Q59_agent_funnel_6stage_rollup.sql (Wave 100)
--
-- Agent funnel 6-stage rollup — Discoverability / Justifiability /
-- Trustability / Accessibility / Payability / Retainability. Each stage
-- is mapped to a LIVE-in-Glue representative table that carries the
-- stage's canonical signal (memory feedback_agent_funnel_6_stages
-- 2026-05-12 — "agent funnel 6 段"):
--   * Discoverability — corporate_website_signal (site is discoverable
--     to agent crawlers; baseline organic surface).
--   * Justifiability  — application_strategy + statistical_cohort_proxy
--     (the outcome can be JUSTIFIED with a cohort-anchored stats trail).
--   * Trustability    — regulatory_audit_outcomes + data_lineage_disclosure
--     (third-party attestation + transparent data chain — Wave 95-97
--     governance arms carry the trust signal).
--   * Accessibility   — accessibility_compliance_signal +
--     api_uptime_sla_obligation (WCAG + SLA = the agent's access path
--     is reliable).
--   * Payability      — acceptance_probability (cost-band fence; proxy
--     for "can this outcome be priced at ¥3?") +
--     cohort_program_recommendation (the "recommended for payment" arm).
--   * Retainability   — customer_acquisition_velocity +
--     customer_satisfaction_proxy (proxy for "do agents come back?").
--
-- Reads as: for each (jsic_major × stage), what is the row-density at
-- that funnel stage? Answers the "where in the 6-stage funnel does my
-- JSIC drop off?" question that organic Wave 49 G1 RUM beacon
-- aggregator + Wave 50 RC1 14 outcome contracts both need.
--
-- Strategic read: high-density at Discoverability + steep drop at
-- Justifiability = "organic crawls succeed but the justify-cost step
-- fails" → bias next-tick effort toward outcome contract evidence;
-- high-density at all 6 stages = "this JSIC has full-funnel coverage,
-- agent monetization works end-to-end".
--
-- 11-source cross-section (all LIVE in Glue, 1-2 representative tables
-- per funnel stage; intentionally over 5-table minimum to make the
-- 6-stage rollup non-trivial):
--   discoverability       → packet_corporate_website_signal_v1
--   justifiability_1      → packet_application_strategy_v1
--   justifiability_2      → packet_statistical_cohort_proxy_v1
--   trustability_audit    → packet_regulatory_audit_outcomes_v1
--   trustability_lineage  → packet_data_lineage_disclosure_v1
--   accessibility_wcag    → packet_accessibility_compliance_signal_v1
--   accessibility_sla     → packet_api_uptime_sla_obligation_v1
--   payability_cohort     → packet_acceptance_probability
--   payability_recommend  → packet_cohort_program_recommendation_v1
--   retainability_acq     → packet_customer_acquisition_velocity_v1
--   retainability_sat     → packet_customer_satisfaction_proxy_v1
--
-- Scan target: ~150-700MB (11 UNION ALL, COUNT + approx_distinct;
-- Wave 95-97 arms remain sparse → most scan in Wave 53 baseline +
-- Wave 76 customer-acq arm).
-- Expected row count: ≤ 230 (11 src × ~20 jsic_major; LIMIT 1000
-- safety).
-- Time estimate: ≤ 90s on Athena engine v3 (workgroup result reuse
-- ON, 50GB BytesScannedCutoffPerQuery PERF-14 cap honored).
--
-- Output schema (8 cols):
--   funnel_stage / wave_family / src / jsic_major / row_count /
--   distinct_subjects / pct_of_stage_total / stage_index

WITH funnel_sources AS (
  -- Stage 1 — Discoverability
  SELECT 'Discoverability' AS funnel_stage,
         1 AS stage_index,
         'discoverability' AS wave_family,
         'corporate_website_signal' AS src,
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK') AS jsic_major,
         json_extract_scalar(subject, '$.id') AS subject_id
  FROM jpcite_credit_2026_05.packet_corporate_website_signal_v1

  -- Stage 2 — Justifiability (cohort-anchored stats trail)
  UNION ALL
  SELECT 'Justifiability', 2,
         'justifiability_1', 'application_strategy',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_application_strategy_v1

  UNION ALL
  SELECT 'Justifiability', 2,
         'justifiability_2', 'statistical_cohort_proxy',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_statistical_cohort_proxy_v1

  -- Stage 3 — Trustability (third-party attestation + lineage)
  UNION ALL
  SELECT 'Trustability', 3,
         'trustability_audit', 'regulatory_audit_outcomes',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_regulatory_audit_outcomes_v1

  UNION ALL
  SELECT 'Trustability', 3,
         'trustability_lineage', 'data_lineage_disclosure',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_data_lineage_disclosure_v1

  -- Stage 4 — Accessibility (WCAG + SLA)
  UNION ALL
  SELECT 'Accessibility', 4,
         'accessibility_wcag', 'accessibility_compliance_signal',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_accessibility_compliance_signal_v1

  UNION ALL
  SELECT 'Accessibility', 4,
         'accessibility_sla', 'api_uptime_sla_obligation',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_api_uptime_sla_obligation_v1

  -- Stage 5 — Payability (cost-band + recommendation)
  UNION ALL
  SELECT 'Payability', 5,
         'payability_cohort', 'acceptance_probability',
         COALESCE(json_extract_scalar(cohort_definition, '$.jsic_major'), 'UNK'),
         json_extract_scalar(cohort_definition, '$.cohort_id')
  FROM jpcite_credit_2026_05.packet_acceptance_probability

  UNION ALL
  SELECT 'Payability', 5,
         'payability_recommend', 'cohort_program_recommendation',
         COALESCE(json_extract_scalar(cohort_definition, '$.jsic_major'), 'UNK'),
         json_extract_scalar(cohort_definition, '$.cohort_id')
  FROM jpcite_credit_2026_05.packet_cohort_program_recommendation_v1

  -- Stage 6 — Retainability (customer-acq + sat proxy)
  UNION ALL
  SELECT 'Retainability', 6,
         'retainability_acq', 'customer_acquisition_velocity',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_customer_acquisition_velocity_v1

  UNION ALL
  SELECT 'Retainability', 6,
         'retainability_sat', 'customer_satisfaction_proxy',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_customer_satisfaction_proxy_v1
),
agg AS (
  SELECT
    funnel_stage,
    stage_index,
    wave_family,
    src,
    jsic_major,
    COUNT(*) AS row_count,
    approx_distinct(subject_id) AS distinct_subjects
  FROM funnel_sources
  GROUP BY funnel_stage, stage_index, wave_family, src, jsic_major
),
stage_totals AS (
  SELECT
    funnel_stage,
    SUM(row_count) AS stage_total_rows
  FROM agg
  GROUP BY funnel_stage
)
SELECT
  a.funnel_stage,
  a.wave_family,
  a.src,
  a.jsic_major,
  a.row_count,
  a.distinct_subjects,
  -- pct_of_stage_total: this (wave_family, src, jsic_major) cell's
  -- share of the funnel stage's footprint. 0% = drop-off; close to
  -- the stage's "fair share" = healthy.
  CASE
    WHEN st.stage_total_rows = 0 THEN 0.0
    ELSE CAST(a.row_count AS DOUBLE) / CAST(st.stage_total_rows AS DOUBLE)
  END AS pct_of_stage_total,
  -- stage_index: 1-6 ordinal so downstream consumers can render the
  -- funnel left-to-right without recomputing the stage order.
  a.stage_index
FROM agg a
JOIN stage_totals st ON a.funnel_stage = st.funnel_stage
ORDER BY a.stage_index, a.row_count DESC, a.wave_family
LIMIT 1000
