-- cohort_acceptance_probability.sql
--
-- Purpose:  Build the 採択確率 (acceptance probability) cohort model from
--           jpi_adoption_records mirrored into the derived Glue catalog.
--           The cohort is the 5-axis product:
--               (prefecture × industry_jsic_major × scale_band ×
--                program_kind × fiscal_year)
--
--           For each cohort we compute:
--             * n_sample             — distinct approved adoption rows
--             * n_eligible_programs  — distinct programs targeting the cohort
--             * acceptance_rate      — n_sample / max(n_eligible_programs,1)
--             * Wilson 95% CI low / high (binomial proportion, k=2)
--           and surface a stable cohort_id so the downstream packet
--           generator can join 1-to-1 with the offline cohort skeleton.
--
-- Output:   cohort_id, prefecture, jsic_major, scale_band, program_kind,
--           fiscal_year, n_sample, n_eligible_programs, acceptance_rate,
--           ci_low_wilson_95, ci_high_wilson_95, freshest_announced_at.
-- Budget:   single-partition scan ~20-60 MB.
-- Notes:    Wilson formula handles the n_sample=0 case by clamping to a
--           CI of [0, 1] in the downstream packet renderer; the SQL keeps
--           the raw p_hat = 0 row so empty cohorts are still emitted
--           (no_hit_not_absence semantics).

WITH base AS (
  SELECT
    UPPER(COALESCE(prefecture, 'UNKNOWN'))                AS prefecture,
    UPPER(SUBSTR(COALESCE(industry_jsic_medium, ''), 1, 1)) AS jsic_major,
    CASE
      WHEN amount_granted_yen IS NULL                THEN 'unknown'
      WHEN amount_granted_yen < 1000000              THEN 'micro'
      WHEN amount_granted_yen < 10000000             THEN 'small'
      WHEN amount_granted_yen < 100000000            THEN 'mid'
      ELSE                                                 'large'
    END                                                   AS scale_band,
    COALESCE(NULLIF(program_id_hint, ''), 'unknown')      AS program_kind,
    SUBSTR(COALESCE(announced_at, ''), 1, 4)              AS fiscal_year,
    program_id                                            AS program_id,
    announced_at
  FROM jpcite_credit_2026_05.jpi_adoption_records
  WHERE run_id = :run_id
)
SELECT
  -- Stable cohort_id for the JPCIR packet generator to bind against.
  CONCAT_WS('.',
    prefecture,
    jsic_major,
    scale_band,
    program_kind,
    fiscal_year
  )                                                       AS cohort_id,
  prefecture,
  jsic_major,
  scale_band,
  program_kind,
  fiscal_year,
  COUNT(*)                                                AS n_sample,
  COUNT(DISTINCT program_id)                              AS n_eligible_programs,
  CAST(COUNT(*) AS DOUBLE)
    / GREATEST(COUNT(DISTINCT program_id), 1)             AS acceptance_rate,
  -- Wilson 95% CI lower bound (z = 1.96, k = z^2 = 3.8416).
  -- p_hat = n_sample / max(n_sample + n_failures, 1); we treat
  -- (n_eligible_programs - 1) as the implicit "failure" bag.
  ( (CAST(COUNT(*) AS DOUBLE)
       / GREATEST(COUNT(DISTINCT program_id), 1))
    + 3.8416 / (2.0 * GREATEST(COUNT(DISTINCT program_id), 1))
    - 1.96 * SQRT(
        ( (CAST(COUNT(*) AS DOUBLE)
            / GREATEST(COUNT(DISTINCT program_id), 1))
        * (1.0 - (CAST(COUNT(*) AS DOUBLE)
            / GREATEST(COUNT(DISTINCT program_id), 1)))
        + 3.8416 / (4.0 * GREATEST(COUNT(DISTINCT program_id), 1)))
        / GREATEST(COUNT(DISTINCT program_id), 1)
      )
  ) / (1.0 + 3.8416 / GREATEST(COUNT(DISTINCT program_id), 1))
                                                          AS ci_low_wilson_95,
  ( (CAST(COUNT(*) AS DOUBLE)
       / GREATEST(COUNT(DISTINCT program_id), 1))
    + 3.8416 / (2.0 * GREATEST(COUNT(DISTINCT program_id), 1))
    + 1.96 * SQRT(
        ( (CAST(COUNT(*) AS DOUBLE)
            / GREATEST(COUNT(DISTINCT program_id), 1))
        * (1.0 - (CAST(COUNT(*) AS DOUBLE)
            / GREATEST(COUNT(DISTINCT program_id), 1)))
        + 3.8416 / (4.0 * GREATEST(COUNT(DISTINCT program_id), 1)))
        / GREATEST(COUNT(DISTINCT program_id), 1)
      )
  ) / (1.0 + 3.8416 / GREATEST(COUNT(DISTINCT program_id), 1))
                                                          AS ci_high_wilson_95,
  MAX(announced_at)                                       AS freshest_announced_at
FROM base
WHERE fiscal_year <> ''
GROUP BY 2, 3, 4, 5, 6
HAVING fiscal_year >= '2020'
ORDER BY n_sample DESC, prefecture, jsic_major, scale_band, program_kind, fiscal_year;
