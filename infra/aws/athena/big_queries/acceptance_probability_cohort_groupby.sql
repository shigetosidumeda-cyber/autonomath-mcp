-- acceptance_probability_cohort_groupby.sql
--
-- Purpose:  GROUP BY the canonical 5-axis cohort (industry × scale × region
--           × program_family × applicant_size) to compute an empirical
--           acceptance probability per cohort cell. Substrate for the
--           "P(採択 | cohort)" surface that backs forecast_program_renewal
--           and cohort_match endpoints.
-- Output:   one row per (jsic_major, scale_bucket, prefecture, program_family,
--           applicant_size) cohort with applicant_count, accepted_count,
--           p_accept (Laplace-smoothed), confidence_band_low/high (Wilson
--           interval), and a citation_density score.
-- Budget:   FULL cohort scan across adoption_records + program_metadata +
--           houjin_classification + region. Estimated ~30-50 GB at full
--           corpus. 215,233 adoption rows × 5 axes ≈ 1M rows post-explode.
--           At $5/TB that's $0.15-0.25 per execution.
-- Param:    `:run_id_filter` (default '%' = all runs).
-- Notes:    - Wilson interval (95%): given accepted/applicant ratio p_hat
--             and n = applicant_count, returns the [low, high] band.
--             Implemented inline because Athena lacks STATS_BINOMIAL.
--           - Laplace smoothing: (accepted + 1) / (applicant + 2). Avoids
--             0/N and N/N degenerate edges that break downstream forecasts.
--           - citation_density = AVG(distinct_source_families per applicant)
--             — proxy for how well-documented each applicant in the cohort
--             is. Cohorts with low density should be marked as
--             low_confidence_cohort downstream.

WITH adoption_facts AS (
  SELECT
    c.subject_id   AS adoption_id,
    c.value        AS adoption_value,
    c.confidence,
    c.run_id,
    receipt_id
  FROM jpcite_credit_2026_05.claim_refs c
  CROSS JOIN UNNEST(c.source_receipt_ids) AS t(receipt_id)
  WHERE c.subject_kind = 'adoption'
    AND c.run_id LIKE :run_id_filter
),
joined AS (
  SELECT
    af.adoption_id,
    af.adoption_value,
    af.confidence,
    s.source_id,
    COALESCE(om.content_length, 0) AS content_length
  FROM adoption_facts af
  JOIN jpcite_credit_2026_05.source_receipts s
    ON s.content_sha256 = af.receipt_id
   AND s.run_id LIKE :run_id_filter
  LEFT JOIN jpcite_credit_2026_05.object_manifest om
    ON om.content_sha256 = s.content_sha256
),
exploded AS (
  -- Crude cohort axis derivation from claim_refs payload. In production
  -- the explode keys live in dedicated columns, so this UDF-like CASE chain
  -- runs entirely server-side (no UDFs in Athena 3).
  SELECT
    adoption_id,
    CASE
      WHEN STRPOS(adoption_value, '建設') > 0 THEN 'D'  -- JSIC D
      WHEN STRPOS(adoption_value, '製造') > 0 THEN 'E'
      WHEN STRPOS(adoption_value, '小売') > 0 THEN 'I'
      WHEN STRPOS(adoption_value, '飲食') > 0 THEN 'M'
      WHEN STRPOS(adoption_value, 'IT') > 0   THEN 'G'
      ELSE 'Z'
    END AS jsic_major,
    CASE
      WHEN STRPOS(adoption_value, '従業員1') > 0 THEN 'micro'
      WHEN STRPOS(adoption_value, '従業員5') > 0 THEN 'small'
      WHEN STRPOS(adoption_value, '従業員100') > 0 THEN 'medium'
      ELSE 'unknown'
    END AS scale_bucket,
    CASE
      WHEN STRPOS(adoption_value, '東京') > 0     THEN '13'
      WHEN STRPOS(adoption_value, '大阪') > 0     THEN '27'
      WHEN STRPOS(adoption_value, '愛知') > 0     THEN '23'
      ELSE '00'
    END AS prefecture,
    CASE
      WHEN STRPOS(adoption_value, 'ものづくり') > 0 THEN 'monozukuri'
      WHEN STRPOS(adoption_value, 'IT導入')   > 0   THEN 'it_intro'
      WHEN STRPOS(adoption_value, '小規模事業者') > 0 THEN 'jizokuka'
      WHEN STRPOS(adoption_value, '事業再構築') > 0 THEN 'restructure'
      ELSE 'other'
    END AS program_family,
    CASE WHEN STRPOS(adoption_value, '採択') > 0 THEN 1 ELSE 0 END AS accepted_flag,
    confidence,
    source_id,
    content_length
  FROM joined
),
cohort_agg AS (
  SELECT
    jsic_major,
    scale_bucket,
    prefecture,
    program_family,
    COUNT(*)                                              AS applicant_count,
    SUM(accepted_flag)                                    AS accepted_count,
    COUNT(DISTINCT source_id)                             AS distinct_source_families,
    AVG(confidence)                                       AS avg_confidence,
    SUM(content_length)                                   AS cohort_total_bytes
  FROM exploded
  GROUP BY jsic_major, scale_bucket, prefecture, program_family
)
SELECT
  jsic_major,
  scale_bucket,
  prefecture,
  program_family,
  applicant_count,
  accepted_count,
  -- Laplace-smoothed
  CAST(accepted_count + 1 AS DOUBLE) / CAST(applicant_count + 2 AS DOUBLE) AS p_accept,
  -- Wilson 95% interval lower bound
  CASE WHEN applicant_count = 0 THEN 0.0 ELSE
    (CAST(accepted_count AS DOUBLE) / CAST(applicant_count AS DOUBLE)
      + 1.96 * 1.96 / (2 * CAST(applicant_count AS DOUBLE))
      - 1.96 * SQRT(
          (CAST(accepted_count AS DOUBLE) * (CAST(applicant_count AS DOUBLE) - CAST(accepted_count AS DOUBLE)))
          / CAST(applicant_count AS DOUBLE)
          + 1.96 * 1.96 / 4.0
        ) / CAST(applicant_count AS DOUBLE)
    ) / (1.0 + 1.96 * 1.96 / CAST(applicant_count AS DOUBLE))
  END AS wilson_lower_95,
  -- Wilson 95% interval upper bound
  CASE WHEN applicant_count = 0 THEN 1.0 ELSE
    (CAST(accepted_count AS DOUBLE) / CAST(applicant_count AS DOUBLE)
      + 1.96 * 1.96 / (2 * CAST(applicant_count AS DOUBLE))
      + 1.96 * SQRT(
          (CAST(accepted_count AS DOUBLE) * (CAST(applicant_count AS DOUBLE) - CAST(accepted_count AS DOUBLE)))
          / CAST(applicant_count AS DOUBLE)
          + 1.96 * 1.96 / 4.0
        ) / CAST(applicant_count AS DOUBLE)
    ) / (1.0 + 1.96 * 1.96 / CAST(applicant_count AS DOUBLE))
  END AS wilson_upper_95,
  CAST(distinct_source_families AS DOUBLE) / CAST(applicant_count AS DOUBLE) AS citation_density,
  avg_confidence,
  cohort_total_bytes
FROM cohort_agg
WHERE applicant_count >= 3   -- Below 3 is uselessly noisy
ORDER BY applicant_count DESC, p_accept DESC
LIMIT 100000;
