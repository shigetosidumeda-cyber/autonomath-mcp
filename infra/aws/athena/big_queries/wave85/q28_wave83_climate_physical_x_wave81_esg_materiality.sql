-- q28_wave83_climate_physical_x_wave81_esg_materiality.sql (Wave 83-85)
--
-- Wave 83 climate physical-risk family × Wave 81 ESG materiality family
-- cross-join. The climate × ESG axis is the canonical TCFD / IFRS S2
-- alignment surface — when a corp has BOTH physical climate exposure
-- (Wave 83) AND ESG materiality reporting (Wave 81), the auditor /
-- investor cohort can read the alignment delta between disclosed risk
-- and disclosed mitigation. The cross-join here produces the bilateral
-- coverage density that a sustainability advisor needs.
--
-- Wave 83 (climate physical-risk family) tables in scope:
--   physical_climate_risk_geo / carbon_credit_inventory /
--   carbon_reporting_compliance / climate_alignment_target /
--   climate_transition_plan / scope1_2_disclosure_completeness /
--   scope3_emissions_disclosure
--
-- Wave 81 (ESG materiality family) tables in scope:
--   green_bond_issuance / sustainability_linked_loan /
--   environmental_disclosure / biodiversity_disclosure /
--   tcfd_disclosure_completeness / environmental_compliance_radar
--
-- Pattern: per-family rollup (COUNT + approx_distinct subject.id)
-- CROSS JOIN producing (climate_family, esg_family) pairs with their
-- combined coverage density. Honors the 50 GB PERF-14 cap; expected
-- scan well under 1 GB since every projection is column-prune-friendly.

WITH wave83_climate AS (
  SELECT 'physical_climate_risk_geo' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_physical_climate_risk_geo_v1

  UNION ALL
  SELECT 'carbon_credit_inventory',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_carbon_credit_inventory_v1

  UNION ALL
  SELECT 'carbon_reporting_compliance',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_carbon_reporting_compliance_v1

  UNION ALL
  SELECT 'climate_alignment_target',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_climate_alignment_target_v1

  UNION ALL
  SELECT 'climate_transition_plan',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_climate_transition_plan_v1
),
wave81_esg AS (
  SELECT 'green_bond_issuance' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_green_bond_issuance_v1

  UNION ALL
  SELECT 'sustainability_linked_loan',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_sustainability_linked_loan_v1

  UNION ALL
  SELECT 'tcfd_disclosure_completeness',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_tcfd_disclosure_completeness_v1

  UNION ALL
  SELECT 'environmental_disclosure',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_environmental_disclosure_v1
)
SELECT
  c.src AS wave83_climate_family,
  c.row_count AS climate_row_count,
  c.approx_distinct_subjects AS climate_distinct_subjects,
  e.src AS wave81_esg_family,
  e.row_count AS esg_row_count,
  e.approx_distinct_subjects AS esg_distinct_subjects,
  -- alignment density: ratio of esg distinct subjects covered by climate
  -- distinct subjects. Capped at 1.0 (since climate cohort may exceed esg).
  CASE
    WHEN e.approx_distinct_subjects = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(c.approx_distinct_subjects AS DOUBLE)
               / CAST(e.approx_distinct_subjects AS DOUBLE))
  END AS climate_esg_alignment_density
FROM wave83_climate c
CROSS JOIN wave81_esg e
ORDER BY c.row_count DESC, e.row_count DESC
LIMIT 100
