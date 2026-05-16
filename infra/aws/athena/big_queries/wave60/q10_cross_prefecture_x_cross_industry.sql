-- q10_cross_prefecture_x_cross_industry.sql (Wave 60)
--
-- Cross-prefecture × cross-industry intersection: surface entities that
-- appear in BOTH a Wave 57 geographic (prefecture-anchored) packet AND a
-- Wave 60 industry-anchored packet. The intersection set is the "deep
-- moat" cohort — entities whose prefecture footprint + industry footprint
-- are both indexed, so jpcite can drive single-call cross-cohort
-- recommendations without any LLM.
--
-- Join surface = COALESCE of
--   * subject.id (houjin_bangou first, prefecture-code fallback)
--   * cohort_definition.cohort_id
--   * cohort_definition.prefecture
--   * cohort_definition.industry_jsic_major (Wave 60 industry packets
--     store the JSIC major code on the cohort)
-- normalised to a single string. The output is grouped by
-- (geo_source, industry_source) so each pair is a moat cell.
--
-- Wave 57 packets in scope (10 geographic):
--   city_jct_density / city_size_subsidy_propensity / cross_prefecture_arbitrage
--   municipality_subsidy_inventory / prefecture_court_decision_focus
--   prefecture_environmental_compliance / prefecture_program_heatmap
--   region_industry_match / regional_enforcement_density / rural_subsidy_coverage
--
-- Wave 60 packets in scope (industry-anchored macro; subset present in
-- the credit DB):
--   trademark_industry_density / vendor_due_diligence
--   succession_program_matching
-- Plus the Wave 53 enforcement_industry_heatmap (industry signal too).
--
-- Wave 57 uses `generated_at`; Wave 60 has a mix (heavy = generated_at,
-- light = created_at). Both are projected to a single `gen_ts` column
-- but the timestamp isn't joined on — only the cohort key is.

WITH wave57_geo AS (
  SELECT
    COALESCE(
      json_extract_scalar(subject, '$.id'),
      json_extract_scalar(cohort_definition, '$.cohort_id'),
      json_extract_scalar(cohort_definition, '$.prefecture'),
      'UNKNOWN'
    ) AS join_key,
    'packet_city_jct_density_v1' AS geo_source,
    generated_at AS geo_generated_at,
    json_extract_scalar(cohort_definition, '$.prefecture') AS geo_prefecture
  FROM jpcite_credit_2026_05.packet_city_jct_density_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_city_size_subsidy_propensity_v1', generated_at,
    json_extract_scalar(cohort_definition, '$.prefecture')
  FROM jpcite_credit_2026_05.packet_city_size_subsidy_propensity_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_cross_prefecture_arbitrage_v1', generated_at,
    json_extract_scalar(cohort_definition, '$.prefecture')
  FROM jpcite_credit_2026_05.packet_cross_prefecture_arbitrage_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_municipality_subsidy_inventory_v1', generated_at,
    json_extract_scalar(cohort_definition, '$.prefecture')
  FROM jpcite_credit_2026_05.packet_municipality_subsidy_inventory_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_prefecture_court_decision_focus_v1', generated_at,
    json_extract_scalar(cohort_definition, '$.prefecture')
  FROM jpcite_credit_2026_05.packet_prefecture_court_decision_focus_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_prefecture_environmental_compliance_v1', generated_at,
    json_extract_scalar(cohort_definition, '$.prefecture')
  FROM jpcite_credit_2026_05.packet_prefecture_environmental_compliance_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_prefecture_program_heatmap_v1', generated_at,
    json_extract_scalar(cohort_definition, '$.prefecture')
  FROM jpcite_credit_2026_05.packet_prefecture_program_heatmap_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_region_industry_match_v1', generated_at,
    json_extract_scalar(cohort_definition, '$.prefecture')
  FROM jpcite_credit_2026_05.packet_region_industry_match_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_regional_enforcement_density_v1', generated_at,
    json_extract_scalar(cohort_definition, '$.prefecture')
  FROM jpcite_credit_2026_05.packet_regional_enforcement_density_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_rural_subsidy_coverage_v1', generated_at,
    json_extract_scalar(cohort_definition, '$.prefecture')
  FROM jpcite_credit_2026_05.packet_rural_subsidy_coverage_v1
),
industry_packets AS (
  -- Wave 60 (industry-anchored macro; heavy = generated_at)
  SELECT
    COALESCE(
      json_extract_scalar(subject, '$.id'),
      json_extract_scalar(cohort_definition, '$.cohort_id'),
      json_extract_scalar(cohort_definition, '$.industry_jsic_major'),
      'UNKNOWN'
    ) AS join_key,
    'packet_trademark_industry_density_v1' AS industry_source,
    generated_at AS industry_generated_at,
    json_extract_scalar(cohort_definition, '$.industry_jsic_major') AS industry_code
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1

  -- Wave 60 light (subject only; vendor_due_diligence + succession_program_matching)
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
    'packet_vendor_due_diligence_v1', created_at,
    NULL
  FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN'),
    'packet_succession_program_matching_v1', created_at,
    NULL
  FROM jpcite_credit_2026_05.packet_succession_program_matching_v1

  -- Wave 53 enforcement_industry_heatmap as an industry-anchored signal.
  -- Schema note: this table has NO `subject` column (verified via
  -- get-table-metadata 2026-05-16) — it stores the industry-anchored
  -- join key on `cohort_definition` + `top_houjin`. Use
  -- cohort_definition.cohort_id as the join key.
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.industry_jsic_major'),
             'UNKNOWN'),
    'packet_enforcement_industry_heatmap_v1', created_at,
    json_extract_scalar(cohort_definition, '$.industry_jsic_major')
  FROM jpcite_credit_2026_05.packet_enforcement_industry_heatmap_v1
)
SELECT
  geo.geo_source,
  ind.industry_source,
  COUNT(*) AS intersection_row_count,
  COUNT(DISTINCT geo.join_key) AS distinct_join_keys,
  COUNT(DISTINCT geo.geo_prefecture) AS distinct_prefectures,
  COUNT(DISTINCT ind.industry_code) AS distinct_industry_codes,
  MIN(geo.geo_generated_at) AS earliest_geo,
  MAX(geo.geo_generated_at) AS latest_geo,
  MIN(ind.industry_generated_at) AS earliest_ind,
  MAX(ind.industry_generated_at) AS latest_ind
FROM wave57_geo geo
INNER JOIN industry_packets ind ON geo.join_key = ind.join_key
WHERE geo.join_key != 'UNKNOWN'
GROUP BY geo.geo_source, ind.industry_source
ORDER BY intersection_row_count DESC
LIMIT 5000
