-- q37_allwave_53_88_grand_aggregate.sql (Wave 86-88)
--
-- Grand aggregate row-count per wave_family across the full Wave 53
-- → 88 corpus. Successor to wave67/q11 (Wave 53-67), wave70/q21
-- (Wave 53-76 fy × jsic), wave82/q27 (Wave 53-82), wave85/q32 (Wave
-- 53-85), and the Q33-Q36 family-shaped queries above. This is the
-- canonical "show me the footprint of everything through Wave 88"
-- surface — one row per (wave_family, packet_source) with row count
-- + approx_distinct(subject.id) for cardinality.
--
-- Wave families covered (only LIVE-in-Glue tables are listed; missing
-- generators stay out so the count is honest):
--   wave53     baseline       application_strategy / adoption_fiscal /
--                              cohort_program_recommendation
--   wave53_3   acceptance     packet_acceptance_probability
--   wave57     geographic     prefecture_program_heatmap and adjacent
--   wave60-65  finance        bond / green / sustainability / transition
--   wave67     tech_infra     api_uptime / cloud_dependency / data_center
--   wave69     entity_360     4 entity_360 facets (sampled)
--   wave76     startup        business_lifecycle / capital_raising /
--                              funding_to_revenue / kpi_funding_correlation
--   wave80     supply chain   commodity / supplier
--   wave81     esg            tcfd / scope1_2 / scope3
--   wave82     ip             patent / trademark
--   wave83     climate phys   physical_climate / carbon / climate align
--   wave84     demographic    city / prefecture / rural
--   wave85     cybersec       cybersecurity / fdi / data_breach
--   wave86     social media   community engagement + brand proxies
--   wave87     procurement    public_procurement / bid / construction
--   wave88     activism       industry_association + regulatory_change
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
  SELECT 'wave53','cohort_program_recommendation', COUNT(*),
         approx_distinct(json_extract_scalar(cohort_definition, '$.cohort_id'))
  FROM jpcite_credit_2026_05.packet_cohort_program_recommendation_v1

  -- Wave 53.3 acceptance probability
  UNION ALL
  SELECT 'wave53_3','acceptance_probability', COUNT(*),
         approx_distinct(json_extract_scalar(cohort_definition, '$.cohort_id'))
  FROM jpcite_credit_2026_05.packet_acceptance_probability

  -- Wave 57 geographic
  UNION ALL
  SELECT 'wave57_geographic','prefecture_program_heatmap', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_prefecture_program_heatmap_v1
  UNION ALL
  SELECT 'wave57_geographic','prefecture_x_industry_density', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_prefecture_x_industry_density_v1
  UNION ALL
  SELECT 'wave57_geographic','region_industry_match', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_region_industry_match_v1
  UNION ALL
  SELECT 'wave57_geographic','cross_prefecture_arbitrage', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_cross_prefecture_arbitrage_v1

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

  -- Wave 67 tech infra
  UNION ALL
  SELECT 'wave67_tech','api_uptime_sla_obligation', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_api_uptime_sla_obligation_v1
  UNION ALL
  SELECT 'wave67_tech','cloud_dependency_disclosure', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_cloud_dependency_disclosure_v1
  UNION ALL
  SELECT 'wave67_tech','data_center_location', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_data_center_location_v1
  UNION ALL
  SELECT 'wave67_tech','devops_maturity_signal', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_devops_maturity_signal_v1

  -- Wave 69 entity_360 (sample 4 to keep scan small)
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
  SELECT 'wave81_esg','tcfd_disclosure_completeness', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_tcfd_disclosure_completeness_v1
  UNION ALL
  SELECT 'wave81_esg','scope1_2_disclosure_completeness', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_scope1_2_disclosure_completeness_v1
  UNION ALL
  SELECT 'wave81_esg','scope3_emissions_disclosure', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_scope3_emissions_disclosure_v1

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

  -- Wave 83 climate physical
  UNION ALL
  SELECT 'wave83_climate','physical_climate_risk_geo', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_physical_climate_risk_geo_v1
  UNION ALL
  SELECT 'wave83_climate','carbon_credit_inventory', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_carbon_credit_inventory_v1
  UNION ALL
  SELECT 'wave83_climate','carbon_reporting_compliance', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_carbon_reporting_compliance_v1
  UNION ALL
  SELECT 'wave83_climate','climate_alignment_target', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_climate_alignment_target_v1
  UNION ALL
  SELECT 'wave83_climate','climate_transition_plan', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_climate_transition_plan_v1

  -- Wave 84 demographics
  UNION ALL
  SELECT 'wave84_demographic','city_industry_diversification', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_city_industry_diversification_v1
  UNION ALL
  SELECT 'wave84_demographic','prefecture_industry_inbound', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_prefecture_industry_inbound_v1
  UNION ALL
  SELECT 'wave84_demographic','city_size_subsidy_propensity', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_city_size_subsidy_propensity_v1
  UNION ALL
  SELECT 'wave84_demographic','rural_subsidy_coverage', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_rural_subsidy_coverage_v1

  -- Wave 85 cybersec
  UNION ALL
  SELECT 'wave85_cybersec','cybersecurity_certification', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_cybersecurity_certification_v1
  UNION ALL
  SELECT 'wave85_cybersec','fdi_security_review', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_fdi_security_review_v1
  UNION ALL
  SELECT 'wave85_cybersec','data_breach_event_history', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_data_breach_event_history_v1
  UNION ALL
  SELECT 'wave85_cybersec','mandatory_breach_notice_sla', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_mandatory_breach_notice_sla_v1
  UNION ALL
  SELECT 'wave85_cybersec','anonymization_method_disclosure', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_anonymization_method_disclosure_v1

  -- Wave 86 social media / digital presence (live proxies)
  UNION ALL
  SELECT 'wave86_social_media','community_engagement_intensity', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_community_engagement_intensity_v1

  -- Wave 87 procurement / public contracting (live proxies)
  UNION ALL
  SELECT 'wave87_procurement','public_procurement_trend', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_public_procurement_trend_v1
  UNION ALL
  SELECT 'wave87_procurement','bid_opportunity_matching', COUNT(*),
         approx_distinct(
           json_extract_scalar(cohort_definition, '$.cohort_id')
         )
  FROM jpcite_credit_2026_05.packet_bid_opportunity_matching_v1
  UNION ALL
  SELECT 'wave87_procurement','bid_announcement_seasonality', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_bid_announcement_seasonality_v1
  UNION ALL
  SELECT 'wave87_procurement','construction_public_works', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_construction_public_works_v1

  -- Wave 88 corporate activism / political (live proxies)
  UNION ALL
  SELECT 'wave88_activism','industry_association_link', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_industry_association_link_v1
  UNION ALL
  SELECT 'wave88_activism','regulatory_change_industry_impact', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_regulatory_change_industry_impact_v1

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
