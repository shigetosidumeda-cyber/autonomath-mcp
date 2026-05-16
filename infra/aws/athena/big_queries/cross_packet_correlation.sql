-- cross_packet_correlation.sql
--
-- Purpose:  Correlate three populated packet families on shared keys:
--             1. packet_houjin_360       (~86,849 JSON docs)
--             2. packet_acceptance_probability (~225,600 cohort JSON)
--             3. packet_enforcement_industry_heatmap_v1 (~47 cohort JSON)
--           Each packet exposes a different identity / cohort signal,
--           and this query joins them on the prefecture × jsic_major
--           axis (the only field common to all three packet kinds).
--
-- Output:   one row per (prefecture, jsic_major) cohort with:
--             - n_houjin                  count of houjin360 docs in this cohort
--             - avg_houjin_coverage_score average coverage score across the cohort
--             - avg_acceptance_prob       average acceptance_probability.probability_estimate
--             - n_acceptance_cohorts      count of acceptance_probability cohort docs
--             - total_enforcements        sum of enforcement_industry_heatmap.total_enforcements
--             - n_enforcement_cohorts     count of enforcement heatmap docs
--             - cohort_density_score      composite (n_houjin * 0.5 + avg_acceptance_prob * 100 + total_enforcements / 1000)
--
-- Budget:   ~300-500 MB scan across 3 packet tables (real population).
-- Notes:    Uses ``json_extract_scalar(records, '$[0].prefecture')`` to
--           pull the first record's prefecture from packet_houjin_360,
--           since that table stores nested arrays as JSON STRING for
--           schema simplicity.

WITH houjin AS (
  SELECT
    COALESCE(
      json_extract_scalar(records, '$[0].prefecture'),
      'UNKNOWN'
    ) AS prefecture,
    COALESCE(
      json_extract_scalar(records, '$[0].industry_jsic_major'),
      'UNKNOWN'
    ) AS jsic_major,
    CAST(json_extract_scalar(coverage, '$.coverage_score') AS DOUBLE) AS coverage_score
  FROM jpcite_credit_2026_05.packet_houjin_360
),
acc AS (
  SELECT
    COALESCE(json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN') AS prefecture,
    COALESCE(json_extract_scalar(cohort_definition, '$.jsic_major'), 'UNKNOWN') AS jsic_major,
    probability_estimate
  FROM jpcite_credit_2026_05.packet_acceptance_probability
),
enf AS (
  SELECT
    COALESCE(json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN') AS prefecture,
    COALESCE(json_extract_scalar(cohort_definition, '$.jsic_major'), 'UNKNOWN') AS jsic_major,
    CAST(json_extract_scalar(metrics, '$.total_enforcements') AS BIGINT) AS total_enforcements
  FROM jpcite_credit_2026_05.packet_enforcement_industry_heatmap_v1
),
houjin_agg AS (
  SELECT prefecture, jsic_major,
         COUNT(*) AS n_houjin,
         AVG(coverage_score) AS avg_houjin_coverage_score
  FROM houjin
  GROUP BY prefecture, jsic_major
),
acc_agg AS (
  SELECT prefecture, jsic_major,
         AVG(probability_estimate) AS avg_acceptance_prob,
         COUNT(*) AS n_acceptance_cohorts
  FROM acc
  GROUP BY prefecture, jsic_major
),
enf_agg AS (
  SELECT prefecture, jsic_major,
         SUM(total_enforcements) AS total_enforcements,
         COUNT(*) AS n_enforcement_cohorts
  FROM enf
  GROUP BY prefecture, jsic_major
)
SELECT
  COALESCE(h.prefecture, a.prefecture, e.prefecture) AS prefecture,
  COALESCE(h.jsic_major, a.jsic_major, e.jsic_major) AS jsic_major,
  COALESCE(h.n_houjin, 0)                    AS n_houjin,
  h.avg_houjin_coverage_score                AS avg_houjin_coverage_score,
  a.avg_acceptance_prob                      AS avg_acceptance_prob,
  COALESCE(a.n_acceptance_cohorts, 0)        AS n_acceptance_cohorts,
  COALESCE(e.total_enforcements, 0)          AS total_enforcements,
  COALESCE(e.n_enforcement_cohorts, 0)       AS n_enforcement_cohorts,
  (
    COALESCE(h.n_houjin, 0) * 0.5
    + COALESCE(a.avg_acceptance_prob, 0) * 100
    + COALESCE(e.total_enforcements, 0) / 1000.0
  ) AS cohort_density_score
FROM houjin_agg h
FULL OUTER JOIN acc_agg a
  ON h.prefecture = a.prefecture AND h.jsic_major = a.jsic_major
FULL OUTER JOIN enf_agg e
  ON COALESCE(h.prefecture, a.prefecture) = e.prefecture
 AND COALESCE(h.jsic_major, a.jsic_major) = e.jsic_major
ORDER BY cohort_density_score DESC
LIMIT 1000;
