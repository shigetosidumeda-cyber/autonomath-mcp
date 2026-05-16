-- q5_allwave_grand_aggregate.sql (Wave 58)
--
-- Grand aggregate across **all 6 packet wave families** (Wave 53 / 53.3 /
-- 54 / 55 / 56 / 57 / 58). Counts how many distinct (subject_id,
-- wave_family) pairs the derived corpus carries, plus row-level stats per
-- family. This is the "how big is our packet universe" canonical query.
--
-- Wave family classification:
--   * Wave 53   = 16 original cross-source (application_strategy_v1, ...)
--   * Wave 53.3 = 10 deep cross-source (patent_corp_360_v1, ...)
--   * Wave 54   = 10 cross-source (patent_environmental_link_v1, ...)
--   * Wave 56   = 10 time-series (program_amendment_timeline_v2, ...)
--   * Wave 57   = 10 geographic (city_jct_density_v1, ...)
--   * Wave 58   = 10 relationship (board_member_overlap_v1, ...)
--   * Foundation = 3 source tables (houjin_360, acceptance_probability,
--                  program_lineage)
--
-- Join key = COALESCE(subject.id, cohort_definition.cohort_id,
--                     cohort_definition.prefecture). Per-family count
-- aggregates so the result is a 6+1-row roll-up + per-source breakdown
-- (LIMIT 1000 leaves headroom for ~70 (wave, source) cells).

WITH all_packets AS (
  -- Foundation (3 tables)
  SELECT 'foundation' AS wave_family, 'packet_houjin_360' AS src,
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN') AS jk,
         generated_at AS gen_at
  FROM jpcite_credit_2026_05.packet_houjin_360
  UNION ALL
  SELECT 'foundation', 'packet_acceptance_probability',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         freshest_announced_at
  FROM jpcite_credit_2026_05.packet_acceptance_probability
  UNION ALL
  SELECT 'foundation', 'packet_program_lineage',
         COALESCE(json_extract_scalar(program, '$.entity_id'), 'UNKNOWN'),
         json_extract_scalar(header, '$.generated_at')
  FROM jpcite_credit_2026_05.packet_program_lineage
  -- Wave 53 (16 tables, subset commonly populated)
  UNION ALL
  SELECT 'wave53', 'packet_application_strategy_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         created_at
  FROM jpcite_credit_2026_05.packet_application_strategy_v1
  UNION ALL
  SELECT 'wave53', 'packet_bid_opportunity_matching_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         created_at
  FROM jpcite_credit_2026_05.packet_bid_opportunity_matching_v1
  UNION ALL
  SELECT 'wave53', 'packet_company_public_baseline_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         created_at
  FROM jpcite_credit_2026_05.packet_company_public_baseline_v1
  UNION ALL
  SELECT 'wave53', 'packet_enforcement_industry_heatmap_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         created_at
  FROM jpcite_credit_2026_05.packet_enforcement_industry_heatmap_v1
  UNION ALL
  SELECT 'wave53', 'packet_invoice_houjin_cross_check_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         created_at
  FROM jpcite_credit_2026_05.packet_invoice_houjin_cross_check_v1
  UNION ALL
  SELECT 'wave53', 'packet_kanpou_gazette_watch_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         created_at
  FROM jpcite_credit_2026_05.packet_kanpou_gazette_watch_v1
  UNION ALL
  SELECT 'wave53', 'packet_subsidy_application_timeline_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         created_at
  FROM jpcite_credit_2026_05.packet_subsidy_application_timeline_v1
  -- Wave 53.3 (10 tables)
  UNION ALL
  SELECT 'wave53_3', 'packet_patent_corp_360_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_patent_corp_360_v1
  UNION ALL
  SELECT 'wave53_3', 'packet_environmental_compliance_radar_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_environmental_compliance_radar_v1
  UNION ALL
  SELECT 'wave53_3', 'packet_statistical_cohort_proxy_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_statistical_cohort_proxy_v1
  UNION ALL
  SELECT 'wave53_3', 'packet_edinet_finance_program_match_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_edinet_finance_program_match_v1
  -- Wave 54 (10 tables, subset)
  UNION ALL
  SELECT 'wave54', 'packet_patent_environmental_link_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1
  UNION ALL
  SELECT 'wave54', 'packet_municipal_budget_match_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_municipal_budget_match_v1
  UNION ALL
  SELECT 'wave54', 'packet_gbiz_invoice_dispatch_match_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_gbiz_invoice_dispatch_match_v1
  -- Wave 56 (10 tables, subset)
  UNION ALL
  SELECT 'wave56', 'packet_program_amendment_timeline_v2',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_program_amendment_timeline_v2
  UNION ALL
  SELECT 'wave56', 'packet_enforcement_seasonal_trend_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'),
                  json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_enforcement_seasonal_trend_v1
  UNION ALL
  SELECT 'wave56', 'packet_adoption_fiscal_cycle_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_adoption_fiscal_cycle_v1
  UNION ALL
  SELECT 'wave56', 'packet_tax_ruleset_phase_change_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_tax_ruleset_phase_change_v1
  UNION ALL
  SELECT 'wave56', 'packet_invoice_registration_velocity_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'),
                  json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_invoice_registration_velocity_v1
  UNION ALL
  SELECT 'wave56', 'packet_regulatory_q_over_q_diff_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_regulatory_q_over_q_diff_v1
  UNION ALL
  SELECT 'wave56', 'packet_subsidy_application_window_predict_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_subsidy_application_window_predict_v1
  UNION ALL
  SELECT 'wave56', 'packet_bid_announcement_seasonality_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_bid_announcement_seasonality_v1
  UNION ALL
  SELECT 'wave56', 'packet_succession_event_pulse_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_succession_event_pulse_v1
  UNION ALL
  SELECT 'wave56', 'packet_kanpou_event_burst_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_kanpou_event_burst_v1
  -- Wave 57 (10 tables)
  UNION ALL
  SELECT 'wave57', 'packet_city_jct_density_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_city_jct_density_v1
  UNION ALL
  SELECT 'wave57', 'packet_city_size_subsidy_propensity_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_city_size_subsidy_propensity_v1
  UNION ALL
  SELECT 'wave57', 'packet_cross_prefecture_arbitrage_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_cross_prefecture_arbitrage_v1
  UNION ALL
  SELECT 'wave57', 'packet_municipality_subsidy_inventory_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_municipality_subsidy_inventory_v1
  UNION ALL
  SELECT 'wave57', 'packet_prefecture_court_decision_focus_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_prefecture_court_decision_focus_v1
  UNION ALL
  SELECT 'wave57', 'packet_prefecture_environmental_compliance_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_prefecture_environmental_compliance_v1
  UNION ALL
  SELECT 'wave57', 'packet_prefecture_program_heatmap_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_prefecture_program_heatmap_v1
  UNION ALL
  SELECT 'wave57', 'packet_region_industry_match_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_region_industry_match_v1
  UNION ALL
  SELECT 'wave57', 'packet_regional_enforcement_density_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_regional_enforcement_density_v1
  UNION ALL
  SELECT 'wave57', 'packet_rural_subsidy_coverage_v1',
         COALESCE(json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_rural_subsidy_coverage_v1
  -- Wave 58 (10 tables)
  UNION ALL
  SELECT 'wave58', 'packet_board_member_overlap_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_board_member_overlap_v1
  UNION ALL
  SELECT 'wave58', 'packet_business_partner_360_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_business_partner_360_v1
  UNION ALL
  SELECT 'wave58', 'packet_certification_houjin_link_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_certification_houjin_link_v1
  UNION ALL
  SELECT 'wave58', 'packet_employment_program_eligibility_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_employment_program_eligibility_v1
  UNION ALL
  SELECT 'wave58', 'packet_founding_succession_chain_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_founding_succession_chain_v1
  UNION ALL
  SELECT 'wave58', 'packet_houjin_parent_subsidiary_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_houjin_parent_subsidiary_v1
  UNION ALL
  SELECT 'wave58', 'packet_industry_association_link_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_industry_association_link_v1
  UNION ALL
  SELECT 'wave58', 'packet_license_houjin_jurisdiction_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_license_houjin_jurisdiction_v1
  UNION ALL
  SELECT 'wave58', 'packet_public_listed_program_link_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_public_listed_program_link_v1
  UNION ALL
  SELECT 'wave58', 'packet_vendor_payment_history_match_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         generated_at
  FROM jpcite_credit_2026_05.packet_vendor_payment_history_match_v1
)
SELECT
  wave_family,
  src,
  COUNT(*) AS row_count,
  COUNT(DISTINCT jk) AS distinct_join_keys,
  MIN(gen_at) AS earliest_gen,
  MAX(gen_at) AS latest_gen
FROM all_packets
GROUP BY wave_family, src
ORDER BY wave_family, row_count DESC
LIMIT 1000
