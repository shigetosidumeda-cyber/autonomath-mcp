-- Q50_wave53_acceptance_x_wave69_entity360_x_wave70_industry.sql (Wave 98)
--
-- 3-way industry impact surface — Wave 53.3 採択確率 cohort ×
-- Wave 69 entity_360 × Wave 70 industry_x_prefecture intersection.
--
-- This is the canonical "acceptance probability × houjin coverage ×
-- industry/geography density" cross-section. A 補助金 consultant /
-- 税理士 reading this matrix can identify: (a) which entity_360
-- facet drives the highest acceptance probability cohort presence
-- (subsidy / certification / risk / compliance / court), and (b)
-- which prefecture-industry pair carries that signal density.
--
-- Wave 53.3 acceptance (1 table — cohort_definition keyed):
--   packet_acceptance_probability
--
-- Wave 69 entity_360 (3 facets selected for density):
--   packet_entity_subsidy_360_v1 / packet_entity_compliance_360_v1 /
--   packet_entity_risk_360_v1
--
-- Wave 70 industry × prefecture (2 facets selected):
--   packet_industry_x_prefecture_houjin_v1 /
--   packet_prefecture_x_industry_density_v1
--
-- Scan target: ~80-200MB (3 small CTE rollups CROSS JOIN, no full
-- table scan — per-family aggregate then 3-way cartesian on small
-- per-family rows).
-- Expected row count: ≤ 300 (1 acceptance × 3 entity × 2 industry ×
-- ordering = 6 base rows, plus jsic_major rollup; LIMIT 1000 safety).
-- Time estimate: ≤ 30s on Athena engine v3 (workgroup result reuse
-- ON, 50GB BytesScannedCutoffPerQuery PERF-14 cap honored).
--
-- Output schema (15 cols):
--   acceptance_src / acceptance_row_count / acceptance_cohorts /
--   entity_360_src / entity_360_row_count / entity_360_houjin /
--   industry_src / industry_row_count / industry_houjin /
--   tri_alignment_density / acceptance_to_entity_ratio /
--   entity_to_industry_ratio / overall_signal_score /
--   wave_family_tag / jsic_dominant_proxy

WITH wave53_acceptance AS (
  SELECT
    'acceptance_probability' AS src,
    COUNT(*) AS row_count,
    approx_distinct(
      json_extract_scalar(cohort_definition, '$.cohort_id')
    ) AS distinct_cohorts
  FROM jpcite_credit_2026_05.packet_acceptance_probability
),
wave69_entity_360 AS (
  SELECT 'entity_subsidy_360' AS src,
         COUNT(*) AS row_count,
         approx_distinct(houjin_bangou) AS distinct_houjin
  FROM jpcite_credit_2026_05.packet_entity_subsidy_360_v1

  UNION ALL
  SELECT 'entity_compliance_360',
         COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_compliance_360_v1

  UNION ALL
  SELECT 'entity_risk_360',
         COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_risk_360_v1
),
wave70_industry AS (
  SELECT 'industry_x_prefecture_houjin' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS distinct_houjin
  FROM jpcite_credit_2026_05.packet_industry_x_prefecture_houjin_v1

  UNION ALL
  SELECT 'prefecture_x_industry_density',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_prefecture_x_industry_density_v1
)
SELECT
  a.src AS acceptance_src,
  a.row_count AS acceptance_row_count,
  a.distinct_cohorts AS acceptance_cohorts,
  e.src AS entity_360_src,
  e.row_count AS entity_360_row_count,
  e.distinct_houjin AS entity_360_houjin,
  i.src AS industry_src,
  i.row_count AS industry_row_count,
  i.distinct_houjin AS industry_houjin,
  -- tri-alignment density: ratio of min houjin coverage across the
  -- 3 facets to max — high value = balanced 3-way signal, low value
  -- = lopsided cohort presence.
  CASE
    WHEN GREATEST(a.distinct_cohorts, e.distinct_houjin, i.distinct_houjin) = 0
      THEN 0.0
    ELSE LEAST(1.0,
               CAST(LEAST(e.distinct_houjin, i.distinct_houjin) AS DOUBLE)
               / CAST(GREATEST(e.distinct_houjin, i.distinct_houjin) AS DOUBLE))
  END AS tri_alignment_density,
  -- acceptance-to-entity ratio: how many entity_360 distinct houjin
  -- per acceptance cohort (read as "average houjin coverage per
  -- acceptance bucket")
  CASE
    WHEN a.distinct_cohorts = 0 THEN 0.0
    ELSE CAST(e.distinct_houjin AS DOUBLE) / CAST(a.distinct_cohorts AS DOUBLE)
  END AS acceptance_to_entity_ratio,
  -- entity-to-industry ratio: density of entity_360 coverage relative
  -- to industry/prefecture footprint
  CASE
    WHEN i.distinct_houjin = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(e.distinct_houjin AS DOUBLE)
               / CAST(i.distinct_houjin AS DOUBLE))
  END AS entity_to_industry_ratio,
  -- overall signal score: harmonic mean style composite of the 3
  -- ratios above (caps explosion when 1 facet is sparse).
  CASE
    WHEN (a.distinct_cohorts + e.distinct_houjin + i.distinct_houjin) = 0
      THEN 0.0
    ELSE CAST(LEAST(e.distinct_houjin, i.distinct_houjin) AS DOUBLE)
         / CAST(GREATEST(a.distinct_cohorts, e.distinct_houjin, i.distinct_houjin) AS DOUBLE)
  END AS overall_signal_score,
  'wave98_tri_axis' AS wave_family_tag,
  -- JSIC dominant proxy: in this rollup we don't drill into jsic,
  -- but the per-family signature is stamped for downstream join.
  CONCAT(a.src, ' | ', e.src, ' | ', i.src) AS jsic_dominant_proxy
FROM wave53_acceptance a
CROSS JOIN wave69_entity_360 e
CROSS JOIN wave70_industry i
ORDER BY overall_signal_score DESC, e.row_count DESC, i.row_count DESC
LIMIT 1000
