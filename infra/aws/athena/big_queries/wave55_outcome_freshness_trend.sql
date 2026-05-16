-- wave55_outcome_freshness_trend.sql
--
-- generated_at distribution per outcome bucketed into 24h windows.
-- Output: one row per (source_table, day_bucket) with doc count.

WITH all_gen AS (
  SELECT 'packet_houjin_360' AS source_table, generated_at FROM jpcite_credit_2026_05.packet_houjin_360
  UNION ALL SELECT 'packet_acceptance_probability', freshest_announced_at FROM jpcite_credit_2026_05.packet_acceptance_probability
  UNION ALL SELECT 'packet_program_lineage', json_extract_scalar(header, '$.generated_at') FROM jpcite_credit_2026_05.packet_program_lineage
  UNION ALL SELECT 'packet_patent_corp_360_v1', generated_at FROM jpcite_credit_2026_05.packet_patent_corp_360_v1
  UNION ALL SELECT 'packet_environmental_compliance_radar_v1', generated_at FROM jpcite_credit_2026_05.packet_environmental_compliance_radar_v1
  UNION ALL SELECT 'packet_statistical_cohort_proxy_v1', generated_at FROM jpcite_credit_2026_05.packet_statistical_cohort_proxy_v1
  UNION ALL SELECT 'packet_diet_question_program_link_v1', generated_at FROM jpcite_credit_2026_05.packet_diet_question_program_link_v1
  UNION ALL SELECT 'packet_edinet_finance_program_match_v1', generated_at FROM jpcite_credit_2026_05.packet_edinet_finance_program_match_v1
  UNION ALL SELECT 'packet_trademark_brand_protection_v1', generated_at FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1
  UNION ALL SELECT 'packet_statistics_market_size_v1', generated_at FROM jpcite_credit_2026_05.packet_statistics_market_size_v1
  UNION ALL SELECT 'packet_cross_administrative_timeline_v1', generated_at FROM jpcite_credit_2026_05.packet_cross_administrative_timeline_v1
  UNION ALL SELECT 'packet_public_procurement_trend_v1', generated_at FROM jpcite_credit_2026_05.packet_public_procurement_trend_v1
  UNION ALL SELECT 'packet_regulation_impact_simulator_v1', generated_at FROM jpcite_credit_2026_05.packet_regulation_impact_simulator_v1
  UNION ALL SELECT 'packet_patent_environmental_link_v1', generated_at FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1
  UNION ALL SELECT 'packet_diet_question_amendment_correlate_v1', generated_at FROM jpcite_credit_2026_05.packet_diet_question_amendment_correlate_v1
  UNION ALL SELECT 'packet_edinet_program_subsidy_compounding_v1', generated_at FROM jpcite_credit_2026_05.packet_edinet_program_subsidy_compounding_v1
  UNION ALL SELECT 'packet_kanpou_program_event_link_v1', generated_at FROM jpcite_credit_2026_05.packet_kanpou_program_event_link_v1
  UNION ALL SELECT 'packet_kfs_saiketsu_industry_radar_v1', generated_at FROM jpcite_credit_2026_05.packet_kfs_saiketsu_industry_radar_v1
  UNION ALL SELECT 'packet_municipal_budget_match_v1', generated_at FROM jpcite_credit_2026_05.packet_municipal_budget_match_v1
  UNION ALL SELECT 'packet_trademark_industry_density_v1', generated_at FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
  UNION ALL SELECT 'packet_environmental_disposal_radar_v1', generated_at FROM jpcite_credit_2026_05.packet_environmental_disposal_radar_v1
  UNION ALL SELECT 'packet_regulatory_change_industry_impact_v1', generated_at FROM jpcite_credit_2026_05.packet_regulatory_change_industry_impact_v1
  UNION ALL SELECT 'packet_gbiz_invoice_dispatch_match_v1', generated_at FROM jpcite_credit_2026_05.packet_gbiz_invoice_dispatch_match_v1
  -- Wave 53 16 slim packets use created_at as proxy for generated_at
  UNION ALL SELECT 'packet_application_strategy_v1', created_at FROM jpcite_credit_2026_05.packet_application_strategy_v1
  UNION ALL SELECT 'packet_bid_opportunity_matching_v1', created_at FROM jpcite_credit_2026_05.packet_bid_opportunity_matching_v1
  UNION ALL SELECT 'packet_cohort_program_recommendation_v1', created_at FROM jpcite_credit_2026_05.packet_cohort_program_recommendation_v1
  UNION ALL SELECT 'packet_company_public_baseline_v1', created_at FROM jpcite_credit_2026_05.packet_company_public_baseline_v1
  UNION ALL SELECT 'packet_enforcement_industry_heatmap_v1', created_at FROM jpcite_credit_2026_05.packet_enforcement_industry_heatmap_v1
  UNION ALL SELECT 'packet_invoice_houjin_cross_check_v1', created_at FROM jpcite_credit_2026_05.packet_invoice_houjin_cross_check_v1
  UNION ALL SELECT 'packet_invoice_registrant_public_check_v1', created_at FROM jpcite_credit_2026_05.packet_invoice_registrant_public_check_v1
  UNION ALL SELECT 'packet_kanpou_gazette_watch_v1', created_at FROM jpcite_credit_2026_05.packet_kanpou_gazette_watch_v1
  UNION ALL SELECT 'packet_local_government_subsidy_aggregator_v1', created_at FROM jpcite_credit_2026_05.packet_local_government_subsidy_aggregator_v1
  UNION ALL SELECT 'packet_permit_renewal_calendar_v1', created_at FROM jpcite_credit_2026_05.packet_permit_renewal_calendar_v1
  UNION ALL SELECT 'packet_program_law_amendment_impact_v1', created_at FROM jpcite_credit_2026_05.packet_program_law_amendment_impact_v1
  UNION ALL SELECT 'packet_regulatory_change_radar_v1', created_at FROM jpcite_credit_2026_05.packet_regulatory_change_radar_v1
  UNION ALL SELECT 'packet_subsidy_application_timeline_v1', created_at FROM jpcite_credit_2026_05.packet_subsidy_application_timeline_v1
  UNION ALL SELECT 'packet_succession_program_matching_v1', created_at FROM jpcite_credit_2026_05.packet_succession_program_matching_v1
  UNION ALL SELECT 'packet_tax_treaty_japan_inbound_v1', created_at FROM jpcite_credit_2026_05.packet_tax_treaty_japan_inbound_v1
  UNION ALL SELECT 'packet_vendor_due_diligence_v1', created_at FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1
)
SELECT
  source_table,
  substr(generated_at, 1, 10) AS day_bucket,
  COUNT(*) AS n_docs
FROM all_gen
WHERE generated_at IS NOT NULL AND length(generated_at) >= 10
GROUP BY source_table, substr(generated_at, 1, 10)
ORDER BY day_bucket DESC, n_docs DESC
LIMIT 2000;
