-- q7_houjin_bangou_entity_resolution.sql (Wave 60)
--
-- Cross-family entity resolution: given a houjin_bangou (subject.id), how
-- many distinct packet families carry an outcome row for it? This is the
-- "what's the longitudinal footprint per entity" canonical query.
--
-- For each houjin id, count distinct (wave_family, src) pairs. Result is
-- sorted by footprint DESC so the top of the result is the entity with
-- the deepest cross-family coverage. A houjin with N >= 4 cross-family
-- packets is a deep moat candidate.
--
-- Per-table column projection: not every packet has cohort_definition;
-- light Wave 53 packets only have subject.id. Heavy Wave 53.3 / 54 / 55
-- packets carry both. Per-table SELECT keeps Athena type-safe.

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

  -- Wave 54 (subject + cohort fallback)
  UNION ALL SELECT 'wave54','packet_patent_environmental_link_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1
  UNION ALL SELECT 'wave54','packet_gbiz_invoice_dispatch_match_v1',
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_gbiz_invoice_dispatch_match_v1

  -- Wave 55 (subject-only for light tables)
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

  -- Wave 60 (mix; subject-only for light tables)
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
  COUNT(*) AS total_outcome_rows,
  array_agg(DISTINCT wave_family ORDER BY wave_family) AS wave_families,
  array_agg(DISTINCT src ORDER BY src) AS packet_sources
FROM entity_packets
WHERE jk <> 'UNKNOWN'
GROUP BY jk
HAVING COUNT(DISTINCT wave_family) >= 1
ORDER BY distinct_wave_families DESC, total_outcome_rows DESC
LIMIT 1000
