-- q15_allwave_fy_x_family_rollup_with_ci.sql (Wave 67)
--
-- All-Wave fiscal-year × family rollup WITH confidence intervals on the
-- row_count per FY×family bucket. Extends wave60/q9 to add:
--   * approx_distinct_keys = approximate distinct join keys per bucket
--                            (cheap HLL estimator, no exact COUNT(DISTINCT))
--   * lo / hi              = Poisson-style 95% CI on the row count
--     (lo = max(0, count - 1.96 * sqrt(count)),
--      hi = count + 1.96 * sqrt(count))
--
-- FY definition (matches q8/q9):
--   FY(t) = year(t) if month(t) >= 4 else year(t) - 1
--   2026-04-01..2027-03-31 = FY 2026.
--
-- Per-table timestamp resolution unchanged from q9 — wave53 uses
-- created_at, wave53_3/54/55/60 use generated_at when present,
-- foundation packets use their canonical timestamps.

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

  -- Wave 53 (created_at, subject-only)
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

  -- Wave 55 (mix)
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

  -- Wave 56 (time-series, all generated_at)
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

  -- Wave 57 (geographic, generated_at)
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

  -- Wave 58 (relationship, generated_at)
  UNION ALL SELECT 'wave58','packet_board_member_overlap_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_board_member_overlap_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave58','packet_business_partner_360_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_business_partner_360_v1
  WHERE generated_at IS NOT NULL

  -- Wave 60 (industry, mix)
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
),
rolled AS (
  SELECT
    CASE
      WHEN month(gen_ts) >= 4 THEN year(gen_ts)
      ELSE year(gen_ts) - 1
    END AS fiscal_year_jp,
    wave_family,
    COUNT(*) AS row_count,
    approx_distinct(jk) AS approx_distinct_keys
  FROM dated_packets
  GROUP BY
    CASE WHEN month(gen_ts) >= 4 THEN year(gen_ts) ELSE year(gen_ts) - 1 END,
    wave_family
)
SELECT
  fiscal_year_jp,
  wave_family,
  row_count,
  approx_distinct_keys,
  GREATEST(0, CAST(row_count - 1.96 * sqrt(row_count) AS BIGINT)) AS ci_lo_95,
  CAST(row_count + 1.96 * sqrt(row_count) AS BIGINT) AS ci_hi_95
FROM rolled
ORDER BY fiscal_year_jp DESC, row_count DESC
LIMIT 500
