-- wave55_cross_packet_entity_unique.sql
--
-- Count DISTINCT subject_id values per outcome_type across all 39
-- packet tables. Output is one row per packet table with the unique
-- entity count + total document count + uniqueness ratio.

WITH all_subjects AS (
  -- Foundation 3
  SELECT json_extract_scalar(subject, '$.id') AS subject_id, 'packet_houjin_360' AS source_table
    FROM jpcite_credit_2026_05.packet_houjin_360
  UNION ALL
  SELECT json_extract_scalar(cohort_definition, '$.cohort_id'), 'packet_acceptance_probability'
    FROM jpcite_credit_2026_05.packet_acceptance_probability
  UNION ALL
  SELECT json_extract_scalar(program, '$.entity_id'), 'packet_program_lineage'
    FROM jpcite_credit_2026_05.packet_program_lineage
  -- Wave 53.3 + 54 (subject-bearing)
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_patent_corp_360_v1' FROM jpcite_credit_2026_05.packet_patent_corp_360_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_environmental_compliance_radar_v1' FROM jpcite_credit_2026_05.packet_environmental_compliance_radar_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_statistical_cohort_proxy_v1' FROM jpcite_credit_2026_05.packet_statistical_cohort_proxy_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_diet_question_program_link_v1' FROM jpcite_credit_2026_05.packet_diet_question_program_link_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_edinet_finance_program_match_v1' FROM jpcite_credit_2026_05.packet_edinet_finance_program_match_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_trademark_brand_protection_v1' FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_statistics_market_size_v1' FROM jpcite_credit_2026_05.packet_statistics_market_size_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_cross_administrative_timeline_v1' FROM jpcite_credit_2026_05.packet_cross_administrative_timeline_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_public_procurement_trend_v1' FROM jpcite_credit_2026_05.packet_public_procurement_trend_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_regulation_impact_simulator_v1' FROM jpcite_credit_2026_05.packet_regulation_impact_simulator_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_patent_environmental_link_v1' FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_diet_question_amendment_correlate_v1' FROM jpcite_credit_2026_05.packet_diet_question_amendment_correlate_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_edinet_program_subsidy_compounding_v1' FROM jpcite_credit_2026_05.packet_edinet_program_subsidy_compounding_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_kanpou_program_event_link_v1' FROM jpcite_credit_2026_05.packet_kanpou_program_event_link_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_kfs_saiketsu_industry_radar_v1' FROM jpcite_credit_2026_05.packet_kfs_saiketsu_industry_radar_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_municipal_budget_match_v1' FROM jpcite_credit_2026_05.packet_municipal_budget_match_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_trademark_industry_density_v1' FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_environmental_disposal_radar_v1' FROM jpcite_credit_2026_05.packet_environmental_disposal_radar_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_regulatory_change_industry_impact_v1' FROM jpcite_credit_2026_05.packet_regulatory_change_industry_impact_v1
  UNION ALL SELECT json_extract_scalar(subject, '$.id'), 'packet_gbiz_invoice_dispatch_match_v1' FROM jpcite_credit_2026_05.packet_gbiz_invoice_dispatch_match_v1
  -- Wave 53 (16 slim)
  UNION ALL SELECT COALESCE(json_extract_scalar(subject, '$.id'), object_id), 'packet_application_strategy_v1' FROM jpcite_credit_2026_05.packet_application_strategy_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), object_id), 'packet_bid_opportunity_matching_v1' FROM jpcite_credit_2026_05.packet_bid_opportunity_matching_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), object_id), 'packet_cohort_program_recommendation_v1' FROM jpcite_credit_2026_05.packet_cohort_program_recommendation_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(subject, '$.id'), object_id), 'packet_company_public_baseline_v1' FROM jpcite_credit_2026_05.packet_company_public_baseline_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), object_id), 'packet_enforcement_industry_heatmap_v1' FROM jpcite_credit_2026_05.packet_enforcement_industry_heatmap_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(subject, '$.id'), object_id), 'packet_invoice_houjin_cross_check_v1' FROM jpcite_credit_2026_05.packet_invoice_houjin_cross_check_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(subject, '$.id'), object_id), 'packet_invoice_registrant_public_check_v1' FROM jpcite_credit_2026_05.packet_invoice_registrant_public_check_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(subject, '$.id'), object_id), 'packet_kanpou_gazette_watch_v1' FROM jpcite_credit_2026_05.packet_kanpou_gazette_watch_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), object_id), 'packet_local_government_subsidy_aggregator_v1' FROM jpcite_credit_2026_05.packet_local_government_subsidy_aggregator_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(subject, '$.id'), object_id), 'packet_permit_renewal_calendar_v1' FROM jpcite_credit_2026_05.packet_permit_renewal_calendar_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(subject, '$.id'), object_id), 'packet_program_law_amendment_impact_v1' FROM jpcite_credit_2026_05.packet_program_law_amendment_impact_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), object_id), 'packet_regulatory_change_radar_v1' FROM jpcite_credit_2026_05.packet_regulatory_change_radar_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), object_id), 'packet_subsidy_application_timeline_v1' FROM jpcite_credit_2026_05.packet_subsidy_application_timeline_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(subject, '$.id'), object_id), 'packet_succession_program_matching_v1' FROM jpcite_credit_2026_05.packet_succession_program_matching_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(subject, '$.id'), object_id), 'packet_tax_treaty_japan_inbound_v1' FROM jpcite_credit_2026_05.packet_tax_treaty_japan_inbound_v1
  UNION ALL SELECT COALESCE(json_extract_scalar(subject, '$.id'), object_id), 'packet_vendor_due_diligence_v1' FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1
)
SELECT
  source_table,
  COUNT(*)                                       AS total_documents,
  COUNT(DISTINCT subject_id)                     AS distinct_subject_ids,
  CAST(COUNT(DISTINCT subject_id) AS DOUBLE)
    / NULLIF(COUNT(*), 0)                        AS uniqueness_ratio
FROM all_subjects
WHERE subject_id IS NOT NULL
GROUP BY source_table
ORDER BY distinct_subject_ids DESC
LIMIT 100;
