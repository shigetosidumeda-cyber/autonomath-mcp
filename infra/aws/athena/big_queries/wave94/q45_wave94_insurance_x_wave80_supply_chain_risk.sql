-- q45_wave94_insurance_x_wave80_supply_chain_risk.sql (Wave 92-94)
--
-- Wave 94 insurance / risk transfer family × Wave 80 supply chain
-- risk family cross-join. The insurance × supply-chain-risk axis is
-- the canonical risk-transfer vs supplier-exposure alignment surface:
-- when a corp has BOTH (a) insurance coverage / risk transfer signal
-- (Wave 94 — D&O, cyber insurance, BI, EPLI, PL, E&O, earthquake,
-- captive, risk management cert) AND (b) supply chain risk signal
-- (Wave 80 — commodity exposure, supplier credit rating, secondary
-- supplier resilience, JIT failure proxy, single-source dependency),
-- the credit + insurance broker DD can read the insurance-coverage-
-- to-supply-chain-risk alignment density.
--
-- Wave 94 (insurance / risk transfer) tables in scope (live proxies
-- in Glue; full Wave 94 batch like liability_insurance_coverage /
-- directors_officers_insurance / cyber_insurance_uptake /
-- business_interruption_coverage / employer_practices_liability /
-- product_liability_insurance / professional_indemnity_insurance /
-- earthquake_insurance_uptake / captive_insurance_signal /
-- risk_management_certification are smoke-only generators pre-Glue
-- sync — they will fold in once the Glue catalog registration lands):
--   ai_safety_certification (used as live Wave 94 proxy for safety /
--   risk certification anchor) / data_breach_event_history (Wave 85
--   anchor reused as live Wave 94 proxy for cyber-insurance precursor
--   risk signal) / cybersecurity_certification (Wave 85 anchor reused
--   as live Wave 94 proxy for risk-mgmt cert).
--
-- Wave 80 (supply chain risk) tables in scope (all LIVE):
--   commodity_price_exposure / commodity_concentration_risk /
--   secondary_supplier_resilience / supplier_credit_rating_match /
--   supplier_lifecycle_risk / supplier_certification_overlap /
--   geographic_supplier_concentration / single_source_dependency_signal /
--   just_in_time_failure_proxy / just_in_time_intensity /
--   inventory_turnover_pattern / supplier_subsidy_inheritance /
--   trade_credit_terms / supply_chain_attack_vector.
--
-- Pattern: per-family rollup (COUNT + approx_distinct subject.id)
-- CROSS JOIN producing (insurance_family, supply_chain_risk_family)
-- pairs with combined coverage density + risk-transfer-to-supply-
-- chain-risk alignment ratio. Honors the 50 GB PERF-14 cap.

WITH wave94_insurance AS (
  SELECT 'ai_safety_certification' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_ai_safety_certification_v1

  UNION ALL
  SELECT 'data_breach_event_history',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_data_breach_event_history_v1

  UNION ALL
  SELECT 'cybersecurity_certification',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_cybersecurity_certification_v1
),
wave80_supply_chain_risk AS (
  SELECT 'commodity_price_exposure' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_commodity_price_exposure_v1

  UNION ALL
  SELECT 'commodity_concentration_risk',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_commodity_concentration_risk_v1

  UNION ALL
  SELECT 'secondary_supplier_resilience',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_secondary_supplier_resilience_v1

  UNION ALL
  SELECT 'supplier_credit_rating_match',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_supplier_credit_rating_match_v1

  UNION ALL
  SELECT 'supplier_lifecycle_risk',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_supplier_lifecycle_risk_v1

  UNION ALL
  SELECT 'geographic_supplier_concentration',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_geographic_supplier_concentration_v1

  UNION ALL
  SELECT 'single_source_dependency_signal',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_single_source_dependency_signal_v1

  UNION ALL
  SELECT 'just_in_time_failure_proxy',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_just_in_time_failure_proxy_v1

  UNION ALL
  SELECT 'inventory_turnover_pattern',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_inventory_turnover_pattern_v1

  UNION ALL
  SELECT 'supply_chain_attack_vector',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_supply_chain_attack_vector_v1
)
SELECT
  i.src AS wave94_insurance_family,
  i.row_count AS insurance_row_count,
  i.approx_distinct_subjects AS insurance_distinct_subjects,
  s.src AS wave80_supply_chain_risk_family,
  s.row_count AS supply_chain_row_count,
  s.approx_distinct_subjects AS supply_chain_distinct_subjects,
  -- insurance-to-supply-chain-risk alignment: distinct subjects
  -- ratio capped at 1.0. Reads as "% of supply-chain-risk-tracked
  -- subjects that also carry an insurance / risk-transfer signal" —
  -- proxy for risk-mitigation coverage vs. supplier-exposure
  -- density.
  CASE
    WHEN s.approx_distinct_subjects = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(i.approx_distinct_subjects AS DOUBLE)
               / CAST(s.approx_distinct_subjects AS DOUBLE))
  END AS insurance_supply_chain_alignment_density
FROM wave94_insurance i
CROSS JOIN wave80_supply_chain_risk s
ORDER BY i.row_count DESC, s.row_count DESC
LIMIT 200
