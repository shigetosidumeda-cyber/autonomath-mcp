-- q34_wave87_procurement_x_wave53_3_acceptance.sql (Wave 86-88)
--
-- Wave 87 procurement / public contracting family × Wave 53.3
-- acceptance probability cross-join. The procurement × acceptance axis
-- is the canonical "win-rate vs application probability" surface: when
-- a corp has BOTH (a) public procurement / prequalification / bid
-- footprint (Wave 87) AND (b) acceptance probability cohort signal
-- (Wave 53.3), the subsidy / 入札 advisor can read the procurement-
-- footprint-to-application-probability lift density. This is the
-- canonical bid-strategy DD slice that maps "this corp is already in
-- the procurement pool → its acceptance probability on adjacent 補助
-- 金 should rebase up."
--
-- Wave 87 (procurement / public contracting) tables in scope (only
-- LIVE-in-Glue listed; missing tables return 0 row):
--   public_procurement_trend / bid_opportunity_matching /
--   bid_announcement_seasonality / prefecture_procurement_match
--   (planned; pre-sync may be 0-row).
--
-- Wave 53.3 (acceptance probability) table:
--   packet_acceptance_probability (full-scale 225K rows).
--
-- Pattern: per-family rollup (COUNT + approx_distinct cohort_id) CROSS
-- JOIN producing (procurement_family, acceptance_proxy) pairs with
-- combined coverage density + procurement-acceptance lift ratio.
-- Honors the 50 GB PERF-14 cap.

WITH wave87_procurement AS (
  SELECT 'public_procurement_trend' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_public_procurement_trend_v1

  UNION ALL
  SELECT 'bid_opportunity_matching',
         COUNT(*),
         approx_distinct(
           json_extract_scalar(cohort_definition, '$.cohort_id')
         )
  FROM jpcite_credit_2026_05.packet_bid_opportunity_matching_v1

  UNION ALL
  SELECT 'bid_announcement_seasonality',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_bid_announcement_seasonality_v1

  UNION ALL
  SELECT 'construction_public_works',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_construction_public_works_v1
),
wave53_3_acceptance AS (
  SELECT 'acceptance_probability' AS src,
         COUNT(*) AS row_count,
         approx_distinct(
           json_extract_scalar(cohort_definition, '$.cohort_id')
         ) AS approx_distinct_cohorts
  FROM jpcite_credit_2026_05.packet_acceptance_probability
)
SELECT
  p.src AS wave87_procurement_family,
  p.row_count AS procurement_row_count,
  p.approx_distinct_subjects AS procurement_distinct_subjects,
  a.src AS wave53_3_acceptance_proxy,
  a.row_count AS acceptance_row_count,
  a.approx_distinct_cohorts AS acceptance_distinct_cohorts,
  -- procurement-acceptance lift: ratio of procurement distinct
  -- subjects vs acceptance distinct cohorts, capped at 1.0. Reads
  -- as "% of acceptance cohorts that overlap a procurement-active
  -- subject pool" — proxy for bid-pool-to-application-probability.
  CASE
    WHEN a.approx_distinct_cohorts = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(p.approx_distinct_subjects AS DOUBLE)
               / CAST(a.approx_distinct_cohorts AS DOUBLE))
  END AS procurement_acceptance_lift_density
FROM wave87_procurement p
CROSS JOIN wave53_3_acceptance a
ORDER BY p.row_count DESC, a.row_count DESC
LIMIT 100
