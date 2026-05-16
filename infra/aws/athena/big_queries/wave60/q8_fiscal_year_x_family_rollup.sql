-- q8_fiscal_year_x_family_rollup.sql (Wave 60)
--
-- Time-series compression: roll up packets by Japanese fiscal year (FY,
-- 4/1-3/31 anchored) × wave_family.
--
-- FY definition:
--   FY(t) = year(t) if month(t) >= 4 else year(t) - 1
--   2026-04-01..2027-03-31 = FY 2026.
--
-- Per-table timestamp column resolution (varies across packet families):
--   wave53 packets use `created_at` (all)
--   wave53_3 / wave54 / wave55 / wave60 use `generated_at` when present,
--     otherwise fall back to `created_at`.
--   packet_acceptance_probability uses `freshest_announced_at`
--   packet_program_lineage uses header.generated_at (json scalar)
--   packet_houjin_360 uses `generated_at`.

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

  -- Wave 53 (created_at; subject-only)
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

  -- Wave 55 (mix: light tables only have created_at, heavy have generated_at)
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

  -- Wave 60 (mix: light tables have only created_at)
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
LIMIT 1000
