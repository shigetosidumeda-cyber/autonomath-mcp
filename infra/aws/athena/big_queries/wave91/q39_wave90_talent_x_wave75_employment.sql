-- q39_wave90_talent_x_wave75_employment.sql (Wave 89-91)
--
-- Wave 90 talent / workforce / leadership family × Wave 75 employment
-- / labor family cross-join. The talent × employment axis is the
-- canonical leadership-signal vs employment-program alignment surface:
-- when a corp has BOTH (a) talent / workforce / leadership signal
-- (Wave 90 — gender balance, training, employer brand, succession
-- planning) AND (b) employment program / labor compliance coverage
-- (Wave 75), the HR-side DD + 助成金 advisor can read the talent-
-- pipeline-to-employment-subsidy alignment density. Cross-join
-- produces the bilateral surface that 社労士 / 助成金 cohort needs.
--
-- Wave 90 (talent / workforce / leadership) tables in scope. Most
-- Wave 90 packets (employee_turnover_proxy, executive_tenure, wellness,
-- remote_work_adoption) are pre-sync; live proxies used today are
-- the workforce-shaped tables that ARE in Glue:
--   employer_brand_signal / gender_workforce_balance /
--   training_data_provenance (training-density proxy).
--
-- Wave 75 (employment / labor) tables in scope (all LIVE):
--   employment_program_eligibility / young_worker_concentration /
--   labor_dispute_event_rate / payroll_subsidy_intensity /
--   gender_workforce_balance (anchor reused for the labor axis).
--
-- Pattern: per-family rollup (COUNT + approx_distinct subject.id)
-- CROSS JOIN producing (talent_family, employment_family) pairs with
-- combined coverage density + talent-employment alignment ratio.
-- Honors the 50 GB PERF-14 cap.

WITH wave90_talent AS (
  SELECT 'employer_brand_signal' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_employer_brand_signal_v1

  UNION ALL
  SELECT 'gender_workforce_balance',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_gender_workforce_balance_v1

  UNION ALL
  SELECT 'training_data_provenance',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_training_data_provenance_v1
),
wave75_employment AS (
  SELECT 'employment_program_eligibility' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_employment_program_eligibility_v1

  UNION ALL
  SELECT 'young_worker_concentration',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_young_worker_concentration_v1

  UNION ALL
  SELECT 'labor_dispute_event_rate',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_labor_dispute_event_rate_v1

  UNION ALL
  SELECT 'payroll_subsidy_intensity',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_payroll_subsidy_intensity_v1
)
SELECT
  t.src AS wave90_talent_family,
  t.row_count AS talent_row_count,
  t.approx_distinct_subjects AS talent_distinct_subjects,
  e.src AS wave75_employment_family,
  e.row_count AS employment_row_count,
  e.approx_distinct_subjects AS employment_distinct_subjects,
  -- talent-employment alignment: distinct subjects ratio capped at
  -- 1.0. Reads as "% of employment-program-tracked subjects that
  -- also carry a talent / workforce / leadership signal" — proxy for
  -- HR DD pipeline density per employment program.
  CASE
    WHEN e.approx_distinct_subjects = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(t.approx_distinct_subjects AS DOUBLE)
               / CAST(e.approx_distinct_subjects AS DOUBLE))
  END AS talent_employment_alignment_density
FROM wave90_talent t
CROSS JOIN wave75_employment e
ORDER BY t.row_count DESC, e.row_count DESC
LIMIT 100
