-- q27_allwave_53_82_grand_aggregate.sql (Wave 80-82)
--
-- Grand aggregate row-count per wave_family across the full
-- Wave 53 → 82 corpus. Successor to wave67/q11 (Wave 53-67),
-- wave70/q21 (Wave 53-76 fy × jsic), and the Q23-Q26 family-shaped
-- queries above. This is the canonical "show me the footprint of
-- everything" surface — one row per (wave_family, packet_source)
-- with row count + approx_distinct(subject.id) for cardinality.
--
-- Wave families covered (only LIVE-in-Glue tables are listed; missing
-- generators stay out so the count is honest):
--   wave53     baseline       application_strategy / adoption_fiscal /
--                              cohort_program_recommendation
--   wave53_3   acceptance     packet_acceptance_probability
--   wave53_3+  cross deep     program_lineage_full_trace surface
--   wave60-65  finance        bond / green / sustainability / transition
--   wave69     entity_360     9 entity_360 facets
--   wave74-76  fintech / labor / startup growth
--   wave80     supply chain   commodity / supplier
--   wave81     esg            carbon / climate
--   wave82     ip             patent / trademark
--
-- Pattern: per-row aggregate (COUNT + approx_distinct on subject.id)
-- UNION ALL across all LIVE wave families. Honors the 50 GB PERF-14
-- cap; the output is a thin Top-N summary table.

WITH grand AS (
  -- Wave 53 baseline
  SELECT 'wave53' AS wave_family, 'application_strategy' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_application_strategy_v1
  UNION ALL
  SELECT 'wave53','adoption_fiscal_cycle', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_adoption_fiscal_cycle_v1
  UNION ALL
  -- packet_cohort_program_recommendation_v1 has cohort_definition, not subject
  SELECT 'wave53','cohort_program_recommendation', COUNT(*),
         approx_distinct(json_extract_scalar(cohort_definition, '$.cohort_id'))
  FROM jpcite_credit_2026_05.packet_cohort_program_recommendation_v1

  -- Wave 53.3 acceptance probability (note: this table has cohort_definition,
  -- not subject — keep the cohort_id as the distinct cardinality axis here)
  UNION ALL
  SELECT 'wave53_3' AS wave_family, 'acceptance_probability' AS src, COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(cohort_definition, '$.cohort_id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_acceptance_probability

  -- Wave 60-65 finance
  UNION ALL
  SELECT 'wave60_65_finance','bond_issuance_pattern', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_bond_issuance_pattern_v1
  UNION ALL
  SELECT 'wave60_65_finance','green_bond_issuance', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_green_bond_issuance_v1
  UNION ALL
  SELECT 'wave60_65_finance','sustainability_linked_loan', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_sustainability_linked_loan_v1
  UNION ALL
  SELECT 'wave60_65_finance','transition_finance_eligibility', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_transition_finance_eligibility_v1
  UNION ALL
  SELECT 'wave60_65_finance','finance_fintech_regulation', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_finance_fintech_regulation_v1

  -- Wave 69 entity_360 (9 facets; sample 4 to keep scan small)
  UNION ALL
  SELECT 'wave69_entity360','entity_360_summary', COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_360_summary_v1
  UNION ALL
  SELECT 'wave69_entity360','entity_subsidy_360', COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_subsidy_360_v1
  UNION ALL
  SELECT 'wave69_entity360','entity_certification_360', COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_certification_360_v1
  UNION ALL
  SELECT 'wave69_entity360','entity_risk_360', COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_risk_360_v1

  -- Wave 76 startup / scaleup
  UNION ALL
  SELECT 'wave76_startup','business_lifecycle_stage', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_business_lifecycle_stage_v1
  UNION ALL
  SELECT 'wave76_startup','capital_raising_history', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_capital_raising_history_v1
  UNION ALL
  SELECT 'wave76_startup','funding_to_revenue_ratio', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_funding_to_revenue_ratio_v1
  UNION ALL
  SELECT 'wave76_startup','kpi_funding_correlation', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_kpi_funding_correlation_v1

  -- Wave 80 supply chain
  UNION ALL
  SELECT 'wave80_supply','commodity_price_exposure', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_commodity_price_exposure_v1
  UNION ALL
  SELECT 'wave80_supply','secondary_supplier_resilience', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_secondary_supplier_resilience_v1
  UNION ALL
  SELECT 'wave80_supply','supplier_credit_rating_match', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_supplier_credit_rating_match_v1

  -- Wave 81 ESG materiality
  UNION ALL
  SELECT 'wave81_esg','carbon_credit_inventory', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_carbon_credit_inventory_v1
  UNION ALL
  SELECT 'wave81_esg','carbon_reporting_compliance', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_carbon_reporting_compliance_v1
  UNION ALL
  SELECT 'wave81_esg','climate_alignment_target', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_climate_alignment_target_v1
  UNION ALL
  SELECT 'wave81_esg','climate_transition_plan', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_climate_transition_plan_v1
  UNION ALL
  SELECT 'wave81_esg','physical_climate_risk_geo', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_physical_climate_risk_geo_v1

  -- Wave 82 IP / innovation
  UNION ALL
  SELECT 'wave82_ip','patent_corp_360', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_patent_corp_360_v1
  UNION ALL
  SELECT 'wave82_ip','patent_environmental_link', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1
  UNION ALL
  SELECT 'wave82_ip','patent_subsidy_intersection', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_patent_subsidy_intersection_v1
  UNION ALL
  SELECT 'wave82_ip','trademark_brand_protection', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1
  UNION ALL
  SELECT 'wave82_ip','trademark_industry_density', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1

  -- Foundation anchor (houjin_360)
  UNION ALL
  SELECT 'foundation','houjin_360', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_houjin_360
)
SELECT
  wave_family,
  COUNT(*) AS distinct_packet_sources,
  SUM(row_count) AS total_rows,
  SUM(approx_distinct_subjects) AS sum_approx_distinct_subjects
FROM grand
GROUP BY wave_family
ORDER BY total_rows DESC
LIMIT 100
