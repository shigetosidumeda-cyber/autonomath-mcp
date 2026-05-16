-- q29_wave84_demographics_x_wave57_geographic.sql (Wave 83-85)
--
-- Wave 84 demographics/population family × Wave 57 geographic family
-- cross-join. The demographic × geographic axis is the canonical
-- workforce-policy + regional-subsidy surface — when a prefecture has
-- demographic shift (aging / population decline) AND program coverage
-- (Wave 57 geographic heatmap), the local-government advisor can read
-- the policy-priority delta between demographic need and program supply.
--
-- Wave 84 (demographics/population family) — pending FULL-SCALE
-- generation (task #230). For this query we use the Wave 84 candidate
-- tables that exist in Glue today (city/industry diversification,
-- prefecture_industry_inbound as inbound-flow proxy, city_size_subsidy
-- as size-band proxy). Once the Wave 84 FULL-SCALE set lands, the
-- query can be re-pointed in place — column-prune-friendly projection
-- keeps the contract stable.
--
-- Wave 57 (geographic family) tables in scope:
--   prefecture_program_heatmap / prefecture_x_industry_density /
--   region_industry_match / cross_prefecture_arbitrage /
--   prefecture_industry_inbound / regional_industry_subsidy_match
--
-- Pattern: per-family rollup (COUNT + approx_distinct subject.id)
-- CROSS JOIN producing (demographic_family, geographic_family) pairs
-- with their combined regional coverage density. Honors the 50 GB
-- PERF-14 cap.

WITH wave84_demographic AS (
  SELECT 'city_industry_diversification' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_city_industry_diversification_v1

  UNION ALL
  SELECT 'prefecture_industry_inbound',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_prefecture_industry_inbound_v1

  UNION ALL
  SELECT 'city_size_subsidy_propensity',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_city_size_subsidy_propensity_v1

  UNION ALL
  SELECT 'rural_subsidy_coverage',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_rural_subsidy_coverage_v1
),
wave57_geographic AS (
  SELECT 'prefecture_program_heatmap' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_prefecture_program_heatmap_v1

  UNION ALL
  SELECT 'prefecture_x_industry_density',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_prefecture_x_industry_density_v1

  UNION ALL
  SELECT 'region_industry_match',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_region_industry_match_v1

  UNION ALL
  SELECT 'cross_prefecture_arbitrage',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_cross_prefecture_arbitrage_v1

  UNION ALL
  SELECT 'regional_industry_subsidy_match',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_regional_industry_subsidy_match_v1
)
SELECT
  d.src AS wave84_demographic_family,
  d.row_count AS demographic_row_count,
  d.approx_distinct_subjects AS demographic_distinct_subjects,
  g.src AS wave57_geographic_family,
  g.row_count AS geographic_row_count,
  g.approx_distinct_subjects AS geographic_distinct_subjects,
  -- regional alignment: ratio of geographic distinct subjects also
  -- covered by demographic axis. Capped at 1.0.
  CASE
    WHEN g.approx_distinct_subjects = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(d.approx_distinct_subjects AS DOUBLE)
               / CAST(g.approx_distinct_subjects AS DOUBLE))
  END AS demographic_geographic_density
FROM wave84_demographic d
CROSS JOIN wave57_geographic g
ORDER BY d.row_count DESC, g.row_count DESC
LIMIT 100
