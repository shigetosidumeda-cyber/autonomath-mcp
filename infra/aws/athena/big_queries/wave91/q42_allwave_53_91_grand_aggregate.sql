-- q42_allwave_53_91_grand_aggregate.sql (Wave 89-91)
--
-- Grand aggregate row-count per wave_family across the full Wave 53
-- → 91 corpus. Successor to wave67/q11 (Wave 53-67), wave70/q21
-- (Wave 53-76 fy × jsic), wave82/q27 (Wave 53-82), wave85/q32 (Wave
-- 53-85), wave88/q37 (Wave 53-88), and the Q38-Q41 family-shaped
-- queries above. This is the canonical "show me the footprint of
-- everything through Wave 91" surface — one row per (wave_family,
-- packet_source) with row count + approx_distinct(subject.id) for
-- cardinality.
--
-- Wave families covered (only LIVE-in-Glue tables are listed; missing
-- generators stay out so the count is honest):
--   wave53     baseline       application_strategy / adoption_fiscal /
--                              cohort_program_recommendation
--   wave53_3   acceptance     packet_acceptance_probability
--   wave57     geographic     prefecture_program_heatmap and adjacent
--   wave60-65  finance        bond / green / sustainability / transition
--   wave67     tech_infra     api_uptime / cloud_dependency / data_center
--   wave69     entity_360     7 entity_360 facets
--   wave75     employment     employment_program / payroll / labor
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
--   wave89     m_and_a        m_a_event_signals + succession + board
--   wave90     talent         employer_brand + gender_workforce + training
--   wave91     brand          trademark + review_sentiment + IR + press
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

  -- Wave 69 entity_360 (7 facets)
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
  UNION ALL
  SELECT 'wave69_entity360','entity_compliance_360', COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_compliance_360_v1
  UNION ALL
  SELECT 'wave69_entity360','entity_invoice_360', COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_invoice_360_v1
  UNION ALL
  SELECT 'wave69_entity360','entity_partner_360', COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_partner_360_v1

  -- Wave 75 employment / labor
  UNION ALL
  SELECT 'wave75_employment','employment_program_eligibility', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_employment_program_eligibility_v1
  UNION ALL
  SELECT 'wave75_employment','payroll_subsidy_intensity', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_payroll_subsidy_intensity_v1
  UNION ALL
  SELECT 'wave75_employment','labor_dispute_event_rate', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_labor_dispute_event_rate_v1
  UNION ALL
  SELECT 'wave75_employment','young_worker_concentration', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_young_worker_concentration_v1

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

  -- Wave 84 demographics
  UNION ALL
  SELECT 'wave84_demographic','city_industry_diversification', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_city_industry_diversification_v1
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

  -- Wave 86 social media / digital presence
  UNION ALL
  SELECT 'wave86_social_media','community_engagement_intensity', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_community_engagement_intensity_v1
  UNION ALL
  SELECT 'wave86_social_media','corporate_website_signal', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_corporate_website_signal_v1
  UNION ALL
  SELECT 'wave86_social_media','content_publication_velocity', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_content_publication_velocity_v1

  -- Wave 87 procurement / public contracting
  UNION ALL
  SELECT 'wave87_procurement','public_procurement_trend', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_public_procurement_trend_v1
  UNION ALL
  SELECT 'wave87_procurement','construction_public_works', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_construction_public_works_v1

  -- Wave 88 corporate activism / political
  UNION ALL
  SELECT 'wave88_activism','industry_association_link', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_industry_association_link_v1
  UNION ALL
  SELECT 'wave88_activism','regulatory_change_industry_impact', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_regulatory_change_industry_impact_v1

  -- Wave 89 M&A / succession / governance (NEW)
  UNION ALL
  SELECT 'wave89_ma','m_a_event_signals', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_m_a_event_signals_v1
  UNION ALL
  SELECT 'wave89_ma','entity_succession_360', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_entity_succession_360_v1
  UNION ALL
  SELECT 'wave89_ma','founding_succession_chain', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_founding_succession_chain_v1
  UNION ALL
  SELECT 'wave89_ma','succession_event_pulse', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_succession_event_pulse_v1
  UNION ALL
  SELECT 'wave89_ma','succession_program_matching', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_succession_program_matching_v1
  UNION ALL
  SELECT 'wave89_ma','board_member_overlap', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_board_member_overlap_v1
  UNION ALL
  SELECT 'wave89_ma','executive_compensation_disclosure', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_executive_compensation_disclosure_v1
  UNION ALL
  SELECT 'wave89_ma','board_diversity_signal', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_board_diversity_signal_v1
  UNION ALL
  SELECT 'wave89_ma','anti_trust_settlement_history', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_anti_trust_settlement_history_v1

  -- Wave 90 talent / workforce / leadership (live proxies; NEW family)
  UNION ALL
  SELECT 'wave90_talent','employer_brand_signal', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_employer_brand_signal_v1
  UNION ALL
  SELECT 'wave90_talent','gender_workforce_balance', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_gender_workforce_balance_v1
  UNION ALL
  SELECT 'wave90_talent','training_data_provenance', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_training_data_provenance_v1

  -- Wave 91 brand / customer proxy (NEW family)
  UNION ALL
  SELECT 'wave91_brand','trademark_registration_intensity', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_trademark_registration_intensity_v1
  UNION ALL
  SELECT 'wave91_brand','review_sentiment_aggregate', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_review_sentiment_aggregate_v1
  UNION ALL
  SELECT 'wave91_brand','investor_relations_intensity', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_investor_relations_intensity_v1
  UNION ALL
  SELECT 'wave91_brand','press_release_pulse', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_press_release_pulse_v1
  UNION ALL
  SELECT 'wave91_brand','media_relations_pattern', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_media_relations_pattern_v1
  UNION ALL
  SELECT 'wave91_brand','influencer_partnership_signal', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_influencer_partnership_signal_v1

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
