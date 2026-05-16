-- q9_allwave_fiscal_year_aggregation_53_62.sql (Wave 60)
--
-- Sister of q8_fiscal_year_x_family_rollup.sql, **extended to include the
-- Wave 56-58 time-series + geographic + relationship families** which were
-- empty when q8 was authored. With the Wave 56-58 packets now synced into
-- S3 (post 2026-05-16 18:35 sync, commit f2ce90755), the FY x family
-- rollup can finally see the full 53-62 footprint in one query.
--
-- FY definition (matches q8):
--   FY(t) = year(t) if month(t) >= 4 else year(t) - 1
--   2026-04-01..2027-03-31 = FY 2026.
--
-- Per-table timestamp resolution (varies across packet families):
--   wave53 packets     use `created_at`
--   wave53_3/54/55     use `generated_at` for heavy tables, `created_at`
--                       for light tables (matches q8)
--   wave56/57/58       use `generated_at` (all populated via
--                       _packet_base in the 2026-05-16 sync)
--   wave60             use the q8 pattern (mix)
--   foundation         use `generated_at` (houjin_360) /
--                       `freshest_announced_at` (acceptance_probability)
--
-- Output row count is small (FY x family bucket), even though the UNION
-- ALL touches all 50+ tables -- per-row projection is cheap (only the
-- timestamp column + join key) so the scan cost is dominated by parquet
-- column reads, not output row volume.

WITH dated_packets AS (
  -- Foundation
  SELECT 'foundation' AS wave_family, 'packet_houjin_360' AS src,
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN') AS jk,
         CAST(from_iso8601_timestamp(generated_at) AS timestamp) AS gen_ts
  FROM jpcite_credit_2026_05.packet_houjin_360
  WHERE generated_at IS NOT NULL
  UNION ALL
  SELECT 'foundation', 'packet_acceptance_probability',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(freshest_announced_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_acceptance_probability
  WHERE freshest_announced_at IS NOT NULL

  -- Wave 53 (subject-only, created_at)
  UNION ALL SELECT 'wave53','packet_application_strategy_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(created_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_application_strategy_v1
  WHERE created_at IS NOT NULL
  UNION ALL SELECT 'wave53','packet_company_public_baseline_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(created_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_company_public_baseline_v1
  WHERE created_at IS NOT NULL
  UNION ALL SELECT 'wave53','packet_invoice_houjin_cross_check_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(created_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_invoice_houjin_cross_check_v1
  WHERE created_at IS NOT NULL
  UNION ALL SELECT 'wave53','packet_kanpou_gazette_watch_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(created_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_kanpou_gazette_watch_v1
  WHERE created_at IS NOT NULL

  -- Wave 53.3 (generated_at)
  UNION ALL SELECT 'wave53_3','packet_patent_corp_360_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_patent_corp_360_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave53_3','packet_environmental_compliance_radar_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_environmental_compliance_radar_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave53_3','packet_edinet_finance_program_match_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_edinet_finance_program_match_v1
  WHERE generated_at IS NOT NULL

  -- Wave 54 (generated_at)
  UNION ALL SELECT 'wave54','packet_patent_environmental_link_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave54','packet_gbiz_invoice_dispatch_match_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_gbiz_invoice_dispatch_match_v1
  WHERE generated_at IS NOT NULL

  -- Wave 55 (mix: light tables only have created_at)
  UNION ALL SELECT 'wave55','packet_invoice_registrant_public_check_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(created_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_invoice_registrant_public_check_v1
  WHERE created_at IS NOT NULL
  UNION ALL SELECT 'wave55','packet_kfs_saiketsu_industry_radar_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_kfs_saiketsu_industry_radar_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave55','packet_edinet_program_subsidy_compounding_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_edinet_program_subsidy_compounding_v1
  WHERE generated_at IS NOT NULL

  -- Wave 56 (time-series; generated_at, populated 2026-05-16 sync)
  UNION ALL SELECT 'wave56','packet_program_amendment_timeline_v2',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_program_amendment_timeline_v2
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave56','packet_enforcement_seasonal_trend_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_enforcement_seasonal_trend_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave56','packet_adoption_fiscal_cycle_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_adoption_fiscal_cycle_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave56','packet_tax_ruleset_phase_change_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_tax_ruleset_phase_change_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave56','packet_invoice_registration_velocity_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_invoice_registration_velocity_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave56','packet_regulatory_q_over_q_diff_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_regulatory_q_over_q_diff_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave56','packet_subsidy_application_window_predict_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_subsidy_application_window_predict_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave56','packet_bid_announcement_seasonality_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_bid_announcement_seasonality_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave56','packet_succession_event_pulse_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_succession_event_pulse_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave56','packet_kanpou_event_burst_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_kanpou_event_burst_v1
  WHERE generated_at IS NOT NULL

  -- Wave 57 (geographic; generated_at)
  UNION ALL SELECT 'wave57','packet_city_jct_density_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_city_jct_density_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave57','packet_city_size_subsidy_propensity_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_city_size_subsidy_propensity_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave57','packet_cross_prefecture_arbitrage_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_cross_prefecture_arbitrage_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave57','packet_municipality_subsidy_inventory_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_municipality_subsidy_inventory_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave57','packet_prefecture_court_decision_focus_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_prefecture_court_decision_focus_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave57','packet_prefecture_environmental_compliance_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_prefecture_environmental_compliance_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave57','packet_prefecture_program_heatmap_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_prefecture_program_heatmap_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave57','packet_region_industry_match_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_region_industry_match_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave57','packet_regional_enforcement_density_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_regional_enforcement_density_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave57','packet_rural_subsidy_coverage_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_rural_subsidy_coverage_v1
  WHERE generated_at IS NOT NULL

  -- Wave 58 (relationship; generated_at)
  UNION ALL SELECT 'wave58','packet_board_member_overlap_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_board_member_overlap_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave58','packet_business_partner_360_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_business_partner_360_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave58','packet_certification_houjin_link_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_certification_houjin_link_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave58','packet_employment_program_eligibility_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_employment_program_eligibility_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave58','packet_founding_succession_chain_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_founding_succession_chain_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave58','packet_houjin_parent_subsidiary_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_houjin_parent_subsidiary_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave58','packet_industry_association_link_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_industry_association_link_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave58','packet_license_houjin_jurisdiction_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_license_houjin_jurisdiction_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave58','packet_public_listed_program_link_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_public_listed_program_link_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave58','packet_vendor_payment_history_match_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_vendor_payment_history_match_v1
  WHERE generated_at IS NOT NULL

  -- Wave 60 (mix: light tables have only created_at; matches q8)
  UNION ALL SELECT 'wave60','packet_trademark_industry_density_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave60','packet_vendor_due_diligence_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(created_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1
  WHERE created_at IS NOT NULL
  UNION ALL SELECT 'wave60','packet_succession_program_matching_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(created_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_succession_program_matching_v1
  WHERE created_at IS NOT NULL
)
SELECT
  CASE
    WHEN month(gen_ts) >= 4 THEN year(gen_ts)
    ELSE year(gen_ts) - 1
  END AS fiscal_year_jp,
  wave_family,
  COUNT(*) AS row_count,
  COUNT(DISTINCT jk) AS distinct_join_keys,
  MIN(gen_ts) AS earliest_gen,
  MAX(gen_ts) AS latest_gen
FROM dated_packets
GROUP BY
  CASE WHEN month(gen_ts) >= 4 THEN year(gen_ts) ELSE year(gen_ts) - 1 END,
  wave_family
ORDER BY fiscal_year_jp DESC, row_count DESC
LIMIT 2000
