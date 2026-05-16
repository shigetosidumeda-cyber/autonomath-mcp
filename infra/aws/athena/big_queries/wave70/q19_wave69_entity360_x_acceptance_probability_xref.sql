-- q19_wave69_entity360_x_acceptance_probability_xref.sql (Wave 70-more)
--
-- Wave 69 entity_360 family × Wave 53.3 acceptance_probability cross-ref.
-- The entity_360_* family is 9 packet tables (summary / certification /
-- compliance / court / invoice / partner / risk / subsidy / succession),
-- each a per-entity rollup. Wave 53.3 acceptance_probability is the
-- cohort-shaped probability surface keyed by program × industry × size.
--
-- Goal: produce a per-entity_360_packet rollup of how many distinct
-- acceptance-probability cohort_definitions co-occur with each 360 facet,
-- so we can quantify the "entity rollup density × acceptance probability
-- depth" cross-axis. This is the canonical surface for the M&A advisor
-- + 採択コンサル audience: "give me a 360 view of this houjin AND the
-- acceptance probability cohorts they currently qualify for."
--
-- Pattern: per-table SELECT 1, anchored by the packet_acceptance_probability
-- approx_distinct(cohort_id) count so the cross-ref always has a baseline
-- denominator. Column-prune-friendly select list keeps scan small.

WITH e360 AS (
  SELECT 'entity_360_summary' AS facet, 1 AS r FROM jpcite_credit_2026_05.packet_entity_360_summary_v1
  UNION ALL SELECT 'entity_certification_360',1 FROM jpcite_credit_2026_05.packet_entity_certification_360_v1
  UNION ALL SELECT 'entity_compliance_360',1 FROM jpcite_credit_2026_05.packet_entity_compliance_360_v1
  UNION ALL SELECT 'entity_court_360',1 FROM jpcite_credit_2026_05.packet_entity_court_360_v1
  UNION ALL SELECT 'entity_invoice_360',1 FROM jpcite_credit_2026_05.packet_entity_invoice_360_v1
  UNION ALL SELECT 'entity_partner_360',1 FROM jpcite_credit_2026_05.packet_entity_partner_360_v1
  UNION ALL SELECT 'entity_risk_360',1 FROM jpcite_credit_2026_05.packet_entity_risk_360_v1
  UNION ALL SELECT 'entity_subsidy_360',1 FROM jpcite_credit_2026_05.packet_entity_subsidy_360_v1
  UNION ALL SELECT 'entity_succession_360',1 FROM jpcite_credit_2026_05.packet_entity_succession_360_v1
),
e360_rollup AS (
  SELECT facet, COUNT(*) AS row_count
  FROM e360
  GROUP BY facet
),
accept AS (
  SELECT
    'acceptance_probability' AS facet,
    COUNT(*) AS row_count,
    approx_distinct(json_extract_scalar(cohort_definition, '$.cohort_id')) AS approx_distinct_cohort_ids
  FROM jpcite_credit_2026_05.packet_acceptance_probability
)
SELECT
  e.facet AS entity_360_facet,
  e.row_count AS e360_row_count,
  a.row_count AS acceptance_total_rows,
  a.approx_distinct_cohort_ids AS acceptance_distinct_cohorts,
  -- density ratio = how many cohort definitions per 360 row, capped at 1.0
  CASE
    WHEN e.row_count = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(a.approx_distinct_cohort_ids AS DOUBLE) / CAST(e.row_count AS DOUBLE))
  END AS cohort_density_ratio
FROM e360_rollup e
CROSS JOIN accept a
ORDER BY e.row_count DESC
LIMIT 50
