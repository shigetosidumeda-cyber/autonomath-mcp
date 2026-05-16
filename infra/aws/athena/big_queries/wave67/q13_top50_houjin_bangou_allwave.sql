-- q13_top50_houjin_bangou_allwave.sql (Wave 67)
--
-- Top-50 most-referenced houjin_bangou (entity id) across all Wave 53-67
-- families. For each houjin id, count:
--   * distinct_wave_families  = how many wave families carry a row
--   * distinct_packet_sources = how many distinct packet tables
--   * total_outcome_rows      = sum across all tables
--
-- An entity that appears in N >= 4 wave families is a deep moat candidate
-- (i.e. cross-source view that nobody else has). Sorted by family depth
-- first, then total volume.
--
-- Per-table projection picks the canonical entity key — `subject.id`
-- (most common) with `cohort_definition.cohort_id` fallback when the
-- table is cohort-anchored.

WITH entity_packets AS (
  -- foundation
  SELECT 'foundation' AS wave_family, 'packet_houjin_360' AS src,
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN') AS jk
  FROM jpcite_credit_2026_05.packet_houjin_360
  UNION ALL
  SELECT 'foundation', 'packet_acceptance_probability',
         COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_acceptance_probability

  -- Wave 53 (subject-only)
  UNION ALL SELECT 'wave53','packet_application_strategy_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_application_strategy_v1
  UNION ALL SELECT 'wave53','packet_company_public_baseline_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_company_public_baseline_v1
  UNION ALL SELECT 'wave53','packet_invoice_houjin_cross_check_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_invoice_houjin_cross_check_v1
  UNION ALL SELECT 'wave53','packet_kanpou_gazette_watch_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_kanpou_gazette_watch_v1

  -- Wave 53.3 (subject + cohort fallback)
  UNION ALL SELECT 'wave53_3','packet_patent_corp_360_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_patent_corp_360_v1
  UNION ALL SELECT 'wave53_3','packet_environmental_compliance_radar_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_environmental_compliance_radar_v1
  UNION ALL SELECT 'wave53_3','packet_edinet_finance_program_match_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_edinet_finance_program_match_v1

  -- Wave 54
  UNION ALL SELECT 'wave54','packet_patent_environmental_link_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1
  UNION ALL SELECT 'wave54','packet_gbiz_invoice_dispatch_match_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_gbiz_invoice_dispatch_match_v1

  -- Wave 55
  UNION ALL SELECT 'wave55','packet_invoice_registrant_public_check_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_invoice_registrant_public_check_v1
  UNION ALL SELECT 'wave55','packet_kfs_saiketsu_industry_radar_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_kfs_saiketsu_industry_radar_v1
  UNION ALL SELECT 'wave55','packet_edinet_program_subsidy_compounding_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_edinet_program_subsidy_compounding_v1

  -- Wave 56 (time-series)
  UNION ALL SELECT 'wave56','packet_program_amendment_timeline_v2',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_program_amendment_timeline_v2
  UNION ALL SELECT 'wave56','packet_enforcement_seasonal_trend_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_enforcement_seasonal_trend_v1

  -- Wave 57 (geographic)
  UNION ALL SELECT 'wave57','packet_prefecture_program_heatmap_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_prefecture_program_heatmap_v1
  UNION ALL SELECT 'wave57','packet_region_industry_match_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_region_industry_match_v1

  -- Wave 58 (relationship)
  UNION ALL SELECT 'wave58','packet_board_member_overlap_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_board_member_overlap_v1
  UNION ALL SELECT 'wave58','packet_business_partner_360_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_business_partner_360_v1
  UNION ALL SELECT 'wave58','packet_houjin_parent_subsidiary_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_houjin_parent_subsidiary_v1

  -- Wave 60 (industry)
  UNION ALL SELECT 'wave60','packet_trademark_industry_density_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
  UNION ALL SELECT 'wave60','packet_vendor_due_diligence_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1
  UNION ALL SELECT 'wave60','packet_succession_program_matching_v1',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_succession_program_matching_v1
)
SELECT
  jk AS houjin_bangou_or_cohort,
  COUNT(DISTINCT wave_family) AS distinct_wave_families,
  COUNT(DISTINCT src) AS distinct_packet_sources,
  COUNT(*) AS total_outcome_rows
FROM entity_packets
WHERE jk <> 'UNKNOWN'
GROUP BY jk
HAVING COUNT(DISTINCT wave_family) >= 1
ORDER BY distinct_wave_families DESC, total_outcome_rows DESC
LIMIT 50
