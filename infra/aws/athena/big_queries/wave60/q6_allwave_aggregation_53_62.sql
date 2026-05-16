-- q6_allwave_aggregation_53_62.sql (Wave 60)
--
-- Grand all-Wave aggregation across Waves 53/53.3/54/55/56/57/58/60 (and
-- foundation). Counts packets per (wave_family, source) so the operator
-- can see one canonical "how big is each family" roll-up.
--
-- This query is a sister to wave58/q5 but extended to Wave 55 (the cross-
-- 3-source analytics layer) and Wave 60 (cross-industry macro layer) and
-- removes the joinkey aggregation (q5 already does that). Q6 focuses on
-- pure row counts so it remains cheap even when scan footprint balloons
-- across Wave 56-58 once those prefixes are populated.
--
-- Wave family classification (matches q5 + Wave 55/60 extensions):
--   * foundation = packet_houjin_360 / acceptance_probability / program_lineage
--   * wave53     = 16 cross-source baseline packets
--   * wave53_3   = 10 cross-source deep packets
--   * wave54     = 10 cross-source packets
--   * wave55     = 10 cross-3-source analytics (cohort_program_recommendation_v1 …)
--   * wave56     = 10 time-series packets
--   * wave57     = 10 geographic packets
--   * wave58     = 10 relationship packets
--   * wave60     = 10 cross-industry macro packets (subset already in catalog)

WITH all_packets AS (
  -- foundation
  SELECT 'foundation' AS wave_family, 'packet_houjin_360' AS src, 1 AS row_cnt
  FROM jpcite_credit_2026_05.packet_houjin_360
  UNION ALL
  SELECT 'foundation', 'packet_acceptance_probability', 1
  FROM jpcite_credit_2026_05.packet_acceptance_probability
  UNION ALL
  SELECT 'foundation', 'packet_program_lineage', 1
  FROM jpcite_credit_2026_05.packet_program_lineage

  -- wave53 (core 7 commonly populated)
  UNION ALL SELECT 'wave53','packet_application_strategy_v1',1 FROM jpcite_credit_2026_05.packet_application_strategy_v1
  UNION ALL SELECT 'wave53','packet_bid_opportunity_matching_v1',1 FROM jpcite_credit_2026_05.packet_bid_opportunity_matching_v1
  UNION ALL SELECT 'wave53','packet_company_public_baseline_v1',1 FROM jpcite_credit_2026_05.packet_company_public_baseline_v1
  UNION ALL SELECT 'wave53','packet_enforcement_industry_heatmap_v1',1 FROM jpcite_credit_2026_05.packet_enforcement_industry_heatmap_v1
  UNION ALL SELECT 'wave53','packet_invoice_houjin_cross_check_v1',1 FROM jpcite_credit_2026_05.packet_invoice_houjin_cross_check_v1
  UNION ALL SELECT 'wave53','packet_kanpou_gazette_watch_v1',1 FROM jpcite_credit_2026_05.packet_kanpou_gazette_watch_v1
  UNION ALL SELECT 'wave53','packet_subsidy_application_timeline_v1',1 FROM jpcite_credit_2026_05.packet_subsidy_application_timeline_v1

  -- wave53_3 (4 commonly populated)
  UNION ALL SELECT 'wave53_3','packet_patent_corp_360_v1',1 FROM jpcite_credit_2026_05.packet_patent_corp_360_v1
  UNION ALL SELECT 'wave53_3','packet_environmental_compliance_radar_v1',1 FROM jpcite_credit_2026_05.packet_environmental_compliance_radar_v1
  UNION ALL SELECT 'wave53_3','packet_statistical_cohort_proxy_v1',1 FROM jpcite_credit_2026_05.packet_statistical_cohort_proxy_v1
  UNION ALL SELECT 'wave53_3','packet_edinet_finance_program_match_v1',1 FROM jpcite_credit_2026_05.packet_edinet_finance_program_match_v1

  -- wave54 (3 commonly populated)
  UNION ALL SELECT 'wave54','packet_patent_environmental_link_v1',1 FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1
  UNION ALL SELECT 'wave54','packet_municipal_budget_match_v1',1 FROM jpcite_credit_2026_05.packet_municipal_budget_match_v1
  UNION ALL SELECT 'wave54','packet_gbiz_invoice_dispatch_match_v1',1 FROM jpcite_credit_2026_05.packet_gbiz_invoice_dispatch_match_v1

  -- wave55 (cross-3-source analytics, Wave 55 mega-join surface)
  UNION ALL SELECT 'wave55','packet_cohort_program_recommendation_v1',1 FROM jpcite_credit_2026_05.packet_cohort_program_recommendation_v1
  UNION ALL SELECT 'wave55','packet_cross_administrative_timeline_v1',1 FROM jpcite_credit_2026_05.packet_cross_administrative_timeline_v1
  UNION ALL SELECT 'wave55','packet_diet_question_amendment_correlate_v1',1 FROM jpcite_credit_2026_05.packet_diet_question_amendment_correlate_v1
  UNION ALL SELECT 'wave55','packet_diet_question_program_link_v1',1 FROM jpcite_credit_2026_05.packet_diet_question_program_link_v1
  UNION ALL SELECT 'wave55','packet_edinet_program_subsidy_compounding_v1',1 FROM jpcite_credit_2026_05.packet_edinet_program_subsidy_compounding_v1
  UNION ALL SELECT 'wave55','packet_environmental_disposal_radar_v1',1 FROM jpcite_credit_2026_05.packet_environmental_disposal_radar_v1
  UNION ALL SELECT 'wave55','packet_invoice_registrant_public_check_v1',1 FROM jpcite_credit_2026_05.packet_invoice_registrant_public_check_v1
  UNION ALL SELECT 'wave55','packet_kanpou_program_event_link_v1',1 FROM jpcite_credit_2026_05.packet_kanpou_program_event_link_v1
  UNION ALL SELECT 'wave55','packet_kfs_saiketsu_industry_radar_v1',1 FROM jpcite_credit_2026_05.packet_kfs_saiketsu_industry_radar_v1
  UNION ALL SELECT 'wave55','packet_program_law_amendment_impact_v1',1 FROM jpcite_credit_2026_05.packet_program_law_amendment_impact_v1

  -- wave56 (time-series, Wave 56 surface)
  UNION ALL SELECT 'wave56','packet_program_amendment_timeline_v2',1 FROM jpcite_credit_2026_05.packet_program_amendment_timeline_v2
  UNION ALL SELECT 'wave56','packet_enforcement_seasonal_trend_v1',1 FROM jpcite_credit_2026_05.packet_enforcement_seasonal_trend_v1
  UNION ALL SELECT 'wave56','packet_adoption_fiscal_cycle_v1',1 FROM jpcite_credit_2026_05.packet_adoption_fiscal_cycle_v1
  UNION ALL SELECT 'wave56','packet_tax_ruleset_phase_change_v1',1 FROM jpcite_credit_2026_05.packet_tax_ruleset_phase_change_v1
  UNION ALL SELECT 'wave56','packet_invoice_registration_velocity_v1',1 FROM jpcite_credit_2026_05.packet_invoice_registration_velocity_v1
  UNION ALL SELECT 'wave56','packet_regulatory_q_over_q_diff_v1',1 FROM jpcite_credit_2026_05.packet_regulatory_q_over_q_diff_v1
  UNION ALL SELECT 'wave56','packet_subsidy_application_window_predict_v1',1 FROM jpcite_credit_2026_05.packet_subsidy_application_window_predict_v1
  UNION ALL SELECT 'wave56','packet_bid_announcement_seasonality_v1',1 FROM jpcite_credit_2026_05.packet_bid_announcement_seasonality_v1
  UNION ALL SELECT 'wave56','packet_succession_event_pulse_v1',1 FROM jpcite_credit_2026_05.packet_succession_event_pulse_v1
  UNION ALL SELECT 'wave56','packet_kanpou_event_burst_v1',1 FROM jpcite_credit_2026_05.packet_kanpou_event_burst_v1

  -- wave57 (geographic)
  UNION ALL SELECT 'wave57','packet_city_jct_density_v1',1 FROM jpcite_credit_2026_05.packet_city_jct_density_v1
  UNION ALL SELECT 'wave57','packet_city_size_subsidy_propensity_v1',1 FROM jpcite_credit_2026_05.packet_city_size_subsidy_propensity_v1
  UNION ALL SELECT 'wave57','packet_cross_prefecture_arbitrage_v1',1 FROM jpcite_credit_2026_05.packet_cross_prefecture_arbitrage_v1
  UNION ALL SELECT 'wave57','packet_municipality_subsidy_inventory_v1',1 FROM jpcite_credit_2026_05.packet_municipality_subsidy_inventory_v1
  UNION ALL SELECT 'wave57','packet_prefecture_court_decision_focus_v1',1 FROM jpcite_credit_2026_05.packet_prefecture_court_decision_focus_v1
  UNION ALL SELECT 'wave57','packet_prefecture_environmental_compliance_v1',1 FROM jpcite_credit_2026_05.packet_prefecture_environmental_compliance_v1
  UNION ALL SELECT 'wave57','packet_prefecture_program_heatmap_v1',1 FROM jpcite_credit_2026_05.packet_prefecture_program_heatmap_v1
  UNION ALL SELECT 'wave57','packet_region_industry_match_v1',1 FROM jpcite_credit_2026_05.packet_region_industry_match_v1
  UNION ALL SELECT 'wave57','packet_regional_enforcement_density_v1',1 FROM jpcite_credit_2026_05.packet_regional_enforcement_density_v1
  UNION ALL SELECT 'wave57','packet_rural_subsidy_coverage_v1',1 FROM jpcite_credit_2026_05.packet_rural_subsidy_coverage_v1

  -- wave58 (relationship)
  UNION ALL SELECT 'wave58','packet_board_member_overlap_v1',1 FROM jpcite_credit_2026_05.packet_board_member_overlap_v1
  UNION ALL SELECT 'wave58','packet_business_partner_360_v1',1 FROM jpcite_credit_2026_05.packet_business_partner_360_v1
  UNION ALL SELECT 'wave58','packet_certification_houjin_link_v1',1 FROM jpcite_credit_2026_05.packet_certification_houjin_link_v1
  UNION ALL SELECT 'wave58','packet_employment_program_eligibility_v1',1 FROM jpcite_credit_2026_05.packet_employment_program_eligibility_v1
  UNION ALL SELECT 'wave58','packet_founding_succession_chain_v1',1 FROM jpcite_credit_2026_05.packet_founding_succession_chain_v1
  UNION ALL SELECT 'wave58','packet_houjin_parent_subsidiary_v1',1 FROM jpcite_credit_2026_05.packet_houjin_parent_subsidiary_v1
  UNION ALL SELECT 'wave58','packet_industry_association_link_v1',1 FROM jpcite_credit_2026_05.packet_industry_association_link_v1
  UNION ALL SELECT 'wave58','packet_license_houjin_jurisdiction_v1',1 FROM jpcite_credit_2026_05.packet_license_houjin_jurisdiction_v1
  UNION ALL SELECT 'wave58','packet_public_listed_program_link_v1',1 FROM jpcite_credit_2026_05.packet_public_listed_program_link_v1
  UNION ALL SELECT 'wave58','packet_vendor_payment_history_match_v1',1 FROM jpcite_credit_2026_05.packet_vendor_payment_history_match_v1

  -- wave60 (cross-industry macro — subset already in catalog: trademark, permit, etc.)
  UNION ALL SELECT 'wave60','packet_trademark_industry_density_v1',1 FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
  UNION ALL SELECT 'wave60','packet_trademark_brand_protection_v1',1 FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1
  UNION ALL SELECT 'wave60','packet_permit_renewal_calendar_v1',1 FROM jpcite_credit_2026_05.packet_permit_renewal_calendar_v1
  UNION ALL SELECT 'wave60','packet_statistics_market_size_v1',1 FROM jpcite_credit_2026_05.packet_statistics_market_size_v1
  UNION ALL SELECT 'wave60','packet_regulation_impact_simulator_v1',1 FROM jpcite_credit_2026_05.packet_regulation_impact_simulator_v1
  UNION ALL SELECT 'wave60','packet_regulatory_change_industry_impact_v1',1 FROM jpcite_credit_2026_05.packet_regulatory_change_industry_impact_v1
  UNION ALL SELECT 'wave60','packet_regulatory_change_radar_v1',1 FROM jpcite_credit_2026_05.packet_regulatory_change_radar_v1
  UNION ALL SELECT 'wave60','packet_public_procurement_trend_v1',1 FROM jpcite_credit_2026_05.packet_public_procurement_trend_v1
  UNION ALL SELECT 'wave60','packet_succession_program_matching_v1',1 FROM jpcite_credit_2026_05.packet_succession_program_matching_v1
  UNION ALL SELECT 'wave60','packet_tax_treaty_japan_inbound_v1',1 FROM jpcite_credit_2026_05.packet_tax_treaty_japan_inbound_v1
  UNION ALL SELECT 'wave60','packet_vendor_due_diligence_v1',1 FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1
  UNION ALL SELECT 'wave60','packet_local_government_subsidy_aggregator_v1',1 FROM jpcite_credit_2026_05.packet_local_government_subsidy_aggregator_v1
)
SELECT
  wave_family,
  src,
  SUM(row_cnt) AS row_count
FROM all_packets
GROUP BY wave_family, src
ORDER BY wave_family, row_count DESC
LIMIT 1000
