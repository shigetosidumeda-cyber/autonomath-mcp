-- q12_industry_geographic_time_relationship_4axis.sql (Wave 67)
--
-- 4-axis cross-join: industry (wave60) × geographic (wave57) × time-series
-- (wave56) × relationship (wave58). For each combination of family-pairs,
-- compute the cohort intersection size = how many distinct join keys
-- appear in BOTH legs of the pair.
--
-- This is the canonical "deep moat" query: it surfaces cohorts that have
-- a non-empty footprint in 2+ orthogonal axes simultaneously, which is
-- exactly the unbeatable cross-source view a customer can't get from any
-- single registry.
--
-- Approach: instead of a true 4-way join (would explode O(N^4)), we
-- compute 6 pairwise intersection counts via INNER JOIN on the canonical
-- join_key, which keeps cardinality manageable.
--
-- Output schema: pair_legs (e.g. 'industry x geographic'),
-- intersection_distinct_keys, intersection_row_count.

WITH industry_keys AS (
  SELECT DISTINCT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             'UNKNOWN') AS jk
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'),
                 json_extract_scalar(cohort_definition, '$.cohort_id'),
                 'UNKNOWN') <> 'UNKNOWN'
  UNION
  SELECT DISTINCT COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN') <> 'UNKNOWN'
  UNION
  SELECT DISTINCT COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_succession_program_matching_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN') <> 'UNKNOWN'
),
geo_keys AS (
  SELECT DISTINCT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             'UNKNOWN') AS jk
  FROM jpcite_credit_2026_05.packet_prefecture_program_heatmap_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'),
                 json_extract_scalar(cohort_definition, '$.cohort_id'),
                 json_extract_scalar(cohort_definition, '$.prefecture'),
                 'UNKNOWN') <> 'UNKNOWN'
  UNION
  SELECT DISTINCT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_region_industry_match_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'),
                 json_extract_scalar(cohort_definition, '$.cohort_id'),
                 json_extract_scalar(cohort_definition, '$.prefecture'),
                 'UNKNOWN') <> 'UNKNOWN'
  UNION
  SELECT DISTINCT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_regional_enforcement_density_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'),
                 json_extract_scalar(cohort_definition, '$.cohort_id'),
                 json_extract_scalar(cohort_definition, '$.prefecture'),
                 'UNKNOWN') <> 'UNKNOWN'
),
time_keys AS (
  SELECT DISTINCT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             'UNKNOWN') AS jk
  FROM jpcite_credit_2026_05.packet_program_amendment_timeline_v2
  WHERE COALESCE(json_extract_scalar(subject, '$.id'),
                 json_extract_scalar(cohort_definition, '$.cohort_id'),
                 'UNKNOWN') <> 'UNKNOWN'
  UNION
  SELECT DISTINCT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_enforcement_seasonal_trend_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'),
                 json_extract_scalar(cohort_definition, '$.cohort_id'),
                 'UNKNOWN') <> 'UNKNOWN'
  UNION
  SELECT DISTINCT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_adoption_fiscal_cycle_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'),
                 json_extract_scalar(cohort_definition, '$.cohort_id'),
                 'UNKNOWN') <> 'UNKNOWN'
),
relationship_keys AS (
  SELECT DISTINCT
    COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN') AS jk
  FROM jpcite_credit_2026_05.packet_board_member_overlap_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN') <> 'UNKNOWN'
  UNION
  SELECT DISTINCT COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_business_partner_360_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN') <> 'UNKNOWN'
  UNION
  SELECT DISTINCT COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_houjin_parent_subsidiary_v1
  WHERE COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN') <> 'UNKNOWN'
)
SELECT pair_label, distinct_keys, total_rows FROM (
  -- industry × geographic
  SELECT 'industry_x_geographic' AS pair_label,
         COUNT(DISTINCT i.jk) AS distinct_keys,
         COUNT(*) AS total_rows
  FROM industry_keys i INNER JOIN geo_keys g ON i.jk = g.jk
  UNION ALL
  -- industry × time
  SELECT 'industry_x_time',
         COUNT(DISTINCT i.jk),
         COUNT(*)
  FROM industry_keys i INNER JOIN time_keys t ON i.jk = t.jk
  UNION ALL
  -- industry × relationship
  SELECT 'industry_x_relationship',
         COUNT(DISTINCT i.jk),
         COUNT(*)
  FROM industry_keys i INNER JOIN relationship_keys r ON i.jk = r.jk
  UNION ALL
  -- geographic × time
  SELECT 'geographic_x_time',
         COUNT(DISTINCT g.jk),
         COUNT(*)
  FROM geo_keys g INNER JOIN time_keys t ON g.jk = t.jk
  UNION ALL
  -- geographic × relationship
  SELECT 'geographic_x_relationship',
         COUNT(DISTINCT g.jk),
         COUNT(*)
  FROM geo_keys g INNER JOIN relationship_keys r ON g.jk = r.jk
  UNION ALL
  -- time × relationship
  SELECT 'time_x_relationship',
         COUNT(DISTINCT t.jk),
         COUNT(*)
  FROM time_keys t INNER JOIN relationship_keys r ON t.jk = r.jk
) pairwise
ORDER BY distinct_keys DESC
LIMIT 100
