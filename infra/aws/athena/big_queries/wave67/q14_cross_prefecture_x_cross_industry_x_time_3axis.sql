-- q14_cross_prefecture_x_cross_industry_x_time_3axis.sql (Wave 67)
--
-- 3-axis cross pulse: prefecture × industry × time. For each
-- (prefecture, industry_jsic_major, fiscal_year_jp) tuple, count distinct
-- packets and distinct join keys.
--
-- Inputs:
--   * Wave 57 geographic packets: prefecture from cohort_definition.prefecture
--   * Wave 60 industry packets: industry_jsic_major from cohort_definition
--   * Wave 56 time-series packets: gen_ts for fiscal_year_jp
--
-- Join surface = the canonical join_key (subject.id or cohort_id),
-- intersection requires the same key in all 3 axes.
--
-- Output schema: prefecture, industry_jsic, fiscal_year_jp,
--                cohort_intersection, packet_pair_count
--
-- This is the canonical "spatio-temporal-sectoral" cube — the kind of
-- query no single jurisdiction-bound registry can deliver. Used for
-- regional industry policy heatmaps + temporal trend overlay.

WITH geo_keys AS (
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             'UNKNOWN') AS jk,
    json_extract_scalar(cohort_definition, '$.prefecture') AS prefecture
  FROM jpcite_credit_2026_05.packet_prefecture_program_heatmap_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'),
                 json_extract_scalar(cohort_definition, '$.cohort_id'),
                 json_extract_scalar(cohort_definition, '$.prefecture'),
                 'UNKNOWN') <> 'UNKNOWN'
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             'UNKNOWN'),
    json_extract_scalar(cohort_definition, '$.prefecture')
  FROM jpcite_credit_2026_05.packet_region_industry_match_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'),
                 json_extract_scalar(cohort_definition, '$.cohort_id'),
                 json_extract_scalar(cohort_definition, '$.prefecture'),
                 'UNKNOWN') <> 'UNKNOWN'
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             'UNKNOWN'),
    json_extract_scalar(cohort_definition, '$.prefecture')
  FROM jpcite_credit_2026_05.packet_regional_enforcement_density_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'),
                 json_extract_scalar(cohort_definition, '$.cohort_id'),
                 json_extract_scalar(cohort_definition, '$.prefecture'),
                 'UNKNOWN') <> 'UNKNOWN'
),
industry_keys AS (
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             'UNKNOWN') AS jk,
    json_extract_scalar(cohort_definition, '$.industry_jsic_major') AS industry_jsic
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'),
                 json_extract_scalar(cohort_definition, '$.cohort_id'),
                 'UNKNOWN') <> 'UNKNOWN'
),
time_keys AS (
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             'UNKNOWN') AS jk,
    CASE
      WHEN month(CAST(from_iso8601_timestamp(generated_at) AS timestamp)) >= 4
      THEN year(CAST(from_iso8601_timestamp(generated_at) AS timestamp))
      ELSE year(CAST(from_iso8601_timestamp(generated_at) AS timestamp)) - 1
    END AS fiscal_year_jp
  FROM jpcite_credit_2026_05.packet_program_amendment_timeline_v2
  WHERE generated_at IS NOT NULL
    AND COALESCE(json_extract_scalar(subject, '$.id'),
                 json_extract_scalar(cohort_definition, '$.cohort_id'),
                 'UNKNOWN') <> 'UNKNOWN'
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             'UNKNOWN'),
    CASE
      WHEN month(CAST(from_iso8601_timestamp(generated_at) AS timestamp)) >= 4
      THEN year(CAST(from_iso8601_timestamp(generated_at) AS timestamp))
      ELSE year(CAST(from_iso8601_timestamp(generated_at) AS timestamp)) - 1
    END
  FROM jpcite_credit_2026_05.packet_adoption_fiscal_cycle_v1
  WHERE generated_at IS NOT NULL
    AND COALESCE(json_extract_scalar(subject, '$.id'),
                 json_extract_scalar(cohort_definition, '$.cohort_id'),
                 'UNKNOWN') <> 'UNKNOWN'
)
SELECT
  g.prefecture,
  i.industry_jsic,
  t.fiscal_year_jp,
  COUNT(DISTINCT g.jk) AS cohort_intersection,
  COUNT(*) AS packet_pair_count
FROM geo_keys g
INNER JOIN industry_keys i ON g.jk = i.jk
INNER JOIN time_keys t ON i.jk = t.jk
GROUP BY g.prefecture, i.industry_jsic, t.fiscal_year_jp
ORDER BY cohort_intersection DESC, packet_pair_count DESC
LIMIT 500
