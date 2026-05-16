-- q43_wave92_product_safety_x_wave81_esg_materiality.sql (Wave 92-94)
--
-- Wave 92 product safety / quality compliance family × Wave 81 ESG
-- materiality family cross-join. The product-safety × ESG-materiality
-- axis is the canonical consumer-protection vs sustainability-
-- disclosure alignment surface: when a corp has BOTH (a) product
-- safety / recall / quality signal (Wave 92 — product recall, AI
-- safety, consumer protection, min-price violation history) AND
-- (b) ESG materiality disclosure coverage (Wave 81 — TCFD, Scope1_2,
-- Scope3 + adjacent material disclosures), the consumer-DD + ESG
-- analyst can read the product-safety-to-ESG-disclosure alignment
-- density. Cross-join produces the bilateral surface that consumer
-- + sustainability DD needs.
--
-- Wave 92 (product safety / quality compliance) tables in scope (live
-- proxies in Glue; full Wave 92 batch like food_label_compliance /
-- drug_pharmaceutical_audit / medical_device_compliance /
-- cosmetic_safety_signal / toy_safety_certification /
-- chemical_substance_disclosure / electrical_safety_audit /
-- consumer_complaint_pulse are smoke-only generators pre-Glue sync —
-- they will fold in once the Glue catalog registration lands):
--   product_recall_intensity / product_safety_recall_intensity /
--   product_lifecycle_pulse / product_diversification_intensity /
--   ai_safety_certification / consumer_protection_compliance /
--   min_price_violation_history.
--
-- Wave 81 (ESG materiality) tables in scope (all LIVE):
--   tcfd_disclosure_completeness / scope1_2_disclosure_completeness /
--   scope3_emissions_disclosure / environmental_disclosure /
--   environmental_compliance_radar / biodiversity_disclosure /
--   conflict_mineral_disclosure / human_rights_due_diligence /
--   water_stewardship_signal.
--
-- Pattern: per-family rollup (COUNT + approx_distinct subject.id)
-- CROSS JOIN producing (product_safety_family, esg_family) pairs
-- with combined coverage density + safety-to-ESG alignment ratio.
-- Honors the 50 GB PERF-14 cap.

WITH wave92_product_safety AS (
  SELECT 'product_recall_intensity' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_product_recall_intensity_v1

  UNION ALL
  SELECT 'product_safety_recall_intensity',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_product_safety_recall_intensity_v1

  UNION ALL
  SELECT 'product_lifecycle_pulse',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_product_lifecycle_pulse_v1

  UNION ALL
  SELECT 'product_diversification_intensity',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_product_diversification_intensity_v1

  UNION ALL
  SELECT 'ai_safety_certification',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_ai_safety_certification_v1

  UNION ALL
  SELECT 'consumer_protection_compliance',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_consumer_protection_compliance_v1

  UNION ALL
  SELECT 'min_price_violation_history',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_min_price_violation_history_v1
),
wave81_esg AS (
  SELECT 'tcfd_disclosure_completeness' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_tcfd_disclosure_completeness_v1

  UNION ALL
  SELECT 'scope1_2_disclosure_completeness',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_scope1_2_disclosure_completeness_v1

  UNION ALL
  SELECT 'scope3_emissions_disclosure',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_scope3_emissions_disclosure_v1

  UNION ALL
  SELECT 'environmental_disclosure',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_environmental_disclosure_v1

  UNION ALL
  SELECT 'biodiversity_disclosure',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_biodiversity_disclosure_v1

  UNION ALL
  SELECT 'conflict_mineral_disclosure',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_conflict_mineral_disclosure_v1

  UNION ALL
  SELECT 'human_rights_due_diligence',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_human_rights_due_diligence_v1

  UNION ALL
  SELECT 'water_stewardship_signal',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_water_stewardship_signal_v1
)
SELECT
  p.src AS wave92_product_safety_family,
  p.row_count AS safety_row_count,
  p.approx_distinct_subjects AS safety_distinct_subjects,
  e.src AS wave81_esg_family,
  e.row_count AS esg_row_count,
  e.approx_distinct_subjects AS esg_distinct_subjects,
  -- product-safety to ESG alignment: distinct subjects ratio capped
  -- at 1.0. Reads as "% of ESG-disclosing subjects that also carry a
  -- product-safety / recall signal" — proxy for consumer-protection
  -- + ESG materiality joint coverage.
  CASE
    WHEN e.approx_distinct_subjects = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(p.approx_distinct_subjects AS DOUBLE)
               / CAST(e.approx_distinct_subjects AS DOUBLE))
  END AS safety_esg_alignment_density
FROM wave92_product_safety p
CROSS JOIN wave81_esg e
ORDER BY p.row_count DESC, e.row_count DESC
LIMIT 200
