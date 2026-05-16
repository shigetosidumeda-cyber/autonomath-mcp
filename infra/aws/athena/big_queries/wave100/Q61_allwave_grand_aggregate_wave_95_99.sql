-- Q61_allwave_grand_aggregate_wave_95_99.sql (Wave 100)
--
-- Full grand-aggregate across all newly-registered Wave 95-99 tables.
-- Successor to wave99/q57 (18 families + foundation) — this widens the
-- Wave 95-99 footprint from 3 representative tables (Wave 95-97
-- governance) to ALL 22 newer-family LIVE-in-Glue surfaces from Wave
-- 95 through Wave 99:
--   Wave 95-96 governance core: data_classification_intensity /
--     master_data_governance / data_quality_audit /
--     data_lineage_disclosure / consent_collection_record /
--     data_residency_disclosure / anonymization_method_disclosure /
--     cross_border_data_transfer / cross_border_pii_transfer /
--     pii_classification_compliance / mandatory_breach_notice_sla
--   Wave 97 DSR + vendor + audit: data_subject_request_handling /
--     data_breach_event_log / data_breach_event_history /
--     vendor_due_diligence / regulatory_audit_outcomes /
--     vendor_concentration_risk / vendor_screening_intensity /
--     vendor_security_audit / vendor_payment_history_match /
--     employment_program_eligibility
--   Wave 99 outcome-routing layer: ai_model_lineage /
--     third_party_breach_propagation / human_rights_due_diligence
--
-- Reads as: which Wave 95-99 newer-family arm has the densest cohort
-- after 1 month of FULL-SCALE generators landing? Answers the "post-
-- launch generator throughput audit" question that the Wave 99 outcome
-- routing layer + Wave 50 RC1 14 outcome contracts both need to gauge
-- whether outcomes are evidence-backed.
--
-- Strategic read: arms with row_count > 1000 = "production-ready
-- evidence layer"; arms with row_count in 1-1000 = "structurally
-- registered, evidence sparse"; arms with row_count = 0 = "Glue table
-- registered, FULL-SCALE generator still in flight" (NOT a defect — the
-- chain resolves at 0-rows and downstream consumers gracefully no-op).
--
-- 22-source cross-section (ALL LIVE in Glue, Wave 95-99 newer-family
-- surfaces — intentionally over 5-table minimum since this is the
-- canonical grand-aggregate):
--   See header above for the 11 Wave 95-96 governance arms,
--   10 Wave 97 DSR+vendor+audit arms, and 3 Wave 99 outcome-routing arms.
--
-- Scan target: ~400-1200MB (22 UNION ALL on representative tables,
-- COUNT + approx_distinct on subject.id only; Wave 95-99 arms are
-- mostly sparse at this snapshot → most scan is structural overhead).
-- Expected row count: 22 (1 per arm) + grand rollup; LIMIT 1000 safety.
-- Time estimate: ≤ 150s on Athena engine v3 (workgroup result reuse
-- ON, 50GB BytesScannedCutoffPerQuery PERF-14 cap honored).
--
-- Output schema (8 cols):
--   wave_family / src / row_count / approx_distinct_subjects /
--   pct_of_grand_total / coverage_rank / approx_houjin_density /
--   wave_generation

WITH grand AS (
  -- Wave 95 governance core ----------------------------------------
  SELECT 'wave95_classification' AS wave_family,
         'data_classification_intensity' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_data_classification_intensity_v1

  UNION ALL
  SELECT 'wave95_lineage', 'data_lineage_disclosure', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_data_lineage_disclosure_v1

  UNION ALL
  SELECT 'wave95_residency', 'data_residency_disclosure', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_data_residency_disclosure_v1

  UNION ALL
  SELECT 'wave95_anonymization', 'anonymization_method_disclosure', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_anonymization_method_disclosure_v1

  UNION ALL
  SELECT 'wave95_cross_border_data', 'cross_border_data_transfer', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_cross_border_data_transfer_v1

  UNION ALL
  SELECT 'wave95_cross_border_pii', 'cross_border_pii_transfer', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_cross_border_pii_transfer_v1

  -- Wave 96 governance / consent / quality -------------------------
  UNION ALL
  SELECT 'wave96_master', 'master_data_governance', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_master_data_governance_v1

  UNION ALL
  SELECT 'wave96_quality', 'data_quality_audit', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_data_quality_audit_v1

  UNION ALL
  SELECT 'wave96_consent', 'consent_collection_record', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_consent_collection_record_v1

  UNION ALL
  SELECT 'wave96_pii_class', 'pii_classification_compliance', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_pii_classification_compliance_v1

  UNION ALL
  SELECT 'wave96_breach_sla', 'mandatory_breach_notice_sla', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_mandatory_breach_notice_sla_v1

  -- Wave 97 DSR + breach + audit + vendor ---------------------------
  UNION ALL
  SELECT 'wave97_dsr', 'data_subject_request_handling', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_data_subject_request_handling_v1

  UNION ALL
  SELECT 'wave97_breach_log', 'data_breach_event_log', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_data_breach_event_log_v1

  UNION ALL
  SELECT 'wave97_breach_history', 'data_breach_event_history', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_data_breach_event_history_v1

  UNION ALL
  SELECT 'wave97_audit_outcome', 'regulatory_audit_outcomes', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_regulatory_audit_outcomes_v1

  UNION ALL
  SELECT 'wave97_vendor_dd', 'vendor_due_diligence', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1

  UNION ALL
  SELECT 'wave97_vendor_conc', 'vendor_concentration_risk', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_vendor_concentration_risk_v1

  UNION ALL
  SELECT 'wave97_vendor_screen', 'vendor_screening_intensity', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_vendor_screening_intensity_v1

  UNION ALL
  SELECT 'wave97_vendor_sec', 'vendor_security_audit', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_vendor_security_audit_v1

  UNION ALL
  SELECT 'wave97_vendor_pay_hist', 'vendor_payment_history_match', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_vendor_payment_history_match_v1

  UNION ALL
  SELECT 'wave97_employment_elig', 'employment_program_eligibility', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_employment_program_eligibility_v1

  -- Wave 99 outcome-routing layer (newer-family) -------------------
  UNION ALL
  SELECT 'wave99_ai_lineage', 'ai_model_lineage', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_ai_model_lineage_v1

  UNION ALL
  SELECT 'wave99_third_party_breach', 'third_party_breach_propagation', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_third_party_breach_propagation_v1

  UNION ALL
  SELECT 'wave99_human_rights_dd', 'human_rights_due_diligence', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_human_rights_due_diligence_v1
),
grand_total AS (
  SELECT SUM(row_count) AS total_rows
  FROM grand
)
SELECT
  g.wave_family,
  g.src,
  g.row_count,
  g.approx_distinct_subjects,
  -- pct_of_grand_total: this row's share of the Wave 95-99 grand
  -- total — reads as "% of the union footprint that lives in this
  -- newer-family arm".
  CASE
    WHEN gt.total_rows = 0 THEN 0.0
    ELSE CAST(g.row_count AS DOUBLE) / CAST(gt.total_rows AS DOUBLE)
  END AS pct_of_grand_total,
  -- coverage_rank: dense row rank by row_count DESC across the 24
  -- newer-family arms.
  DENSE_RANK() OVER (ORDER BY g.row_count DESC) AS coverage_rank,
  -- approx_houjin_density: distinct_subjects per 1000 rows — proxy
  -- for "how many distinct entities the arm covers per 1K rows".
  -- Higher = broader entity sweep at the cost of less per-entity depth.
  CASE
    WHEN g.row_count = 0 THEN 0.0
    ELSE CAST(g.approx_distinct_subjects AS DOUBLE)
         / (CAST(g.row_count AS DOUBLE) / 1000.0)
  END AS approx_houjin_density,
  -- wave_generation: ordinal bucket so downstream consumers can group
  -- by 'wave95' / 'wave96' / 'wave97' / 'wave99'. Foundation +
  -- baseline are intentionally OUT-OF-SCOPE here (Q57 covers them).
  CASE
    WHEN g.wave_family LIKE 'wave95_%' THEN 'wave95'
    WHEN g.wave_family LIKE 'wave96_%' THEN 'wave96'
    WHEN g.wave_family LIKE 'wave97_%' THEN 'wave97'
    WHEN g.wave_family LIKE 'wave99_%' THEN 'wave99'
    ELSE 'other'
  END AS wave_generation
FROM grand g
CROSS JOIN grand_total gt
ORDER BY g.row_count DESC
LIMIT 1000
