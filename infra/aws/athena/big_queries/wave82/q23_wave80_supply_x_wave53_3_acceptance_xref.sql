-- q23_wave80_supply_x_wave53_3_acceptance_xref.sql (Wave 80-82)
--
-- Wave 80 supply-chain-risk family × Wave 53.3 acceptance-probability
-- cohort cross-reference. The Wave 80 catalog (282 → 292) carries the
-- supply-side externality surface: commodity price exposure, secondary
-- supplier resilience, and supplier credit-rating match. Wave 53.3's
-- packet_acceptance_probability is the cohort-shaped probability of
-- program adoption keyed by program × industry × size — the canonical
-- back-ref denominator for any cross-family density question.
--
-- Goal: for each Wave 80 supply-chain packet that is LIVE in Glue,
-- produce a row count and the implied "acceptance density ratio" —
-- how many distinct acceptance-probability cohorts co-occur per
-- supply-chain-risk row, capped at 1.0. This is the surface a
-- procurement / sourcing advisor needs: "given supply-chain risk
-- signal, what is the program-adoption coverage I can quote?"
--
-- Pattern: per-supply-family rollup (COUNT + COUNT DISTINCT subject.id)
-- CROSS JOIN with the acceptance_probability baseline. Honors the 50 GB
-- PERF-14 cap; expected scan well under 1 GB because every projection
-- is column-prune-friendly.

WITH wave80_supply AS (
  SELECT 'commodity_price_exposure' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_commodity_price_exposure_v1

  UNION ALL
  SELECT 'secondary_supplier_resilience',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_secondary_supplier_resilience_v1

  UNION ALL
  SELECT 'supplier_credit_rating_match',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_supplier_credit_rating_match_v1
),
accept AS (
  SELECT
    COUNT(*) AS accept_row_count,
    approx_distinct(json_extract_scalar(cohort_definition, '$.cohort_id')) AS approx_distinct_cohorts
  FROM jpcite_credit_2026_05.packet_acceptance_probability
)
SELECT
  s.src AS wave80_supply_family,
  s.row_count AS supply_row_count,
  s.approx_distinct_subjects AS supply_distinct_subjects,
  a.accept_row_count AS acceptance_total_rows,
  a.approx_distinct_cohorts AS acceptance_distinct_cohorts,
  CASE
    WHEN s.row_count = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(a.approx_distinct_cohorts AS DOUBLE) / CAST(s.row_count AS DOUBLE))
  END AS acceptance_density_ratio
FROM wave80_supply s
CROSS JOIN accept a
ORDER BY s.row_count DESC
LIMIT 50
