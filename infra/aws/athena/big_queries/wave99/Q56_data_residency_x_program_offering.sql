-- Q56_data_residency_x_program_offering.sql (Wave 99)
--
-- Cross-prefecture data residency × program offering — Wave 95-97
-- data_residency_disclosure × Wave 70 industry_x_prefecture_houjin ×
-- prefecture_x_industry_density × Wave 95-97 cross_border_data_transfer
-- × Wave 97 third_party_data_transfer × foundation houjin_360.
--
-- Reads as: for each (jsic_major), what is the residency-signal density
-- vs the prefecture-anchored program-offering footprint? Answers the
-- "this houjin discloses 国内 vs 海外 residency AND ships data
-- cross-border AND has a prefecture-anchored program-offering shadow"
-- compliance-cohort question that foreign FDI + 補助金 consultant
-- cohorts both need.
--
-- Strategic read: high-residency-density × high-program-density cell =
-- "this prefecture × JSIC has compliance-ready foreign-data-handling
-- houjin who simultaneously carry program-offering footprint"; this
-- cohort is fast-path for 外国子会社合算税制 + 補助金 joint package.
--
-- 6-source cross-section (all LIVE in Glue, Wave 95-97 governance +
-- Wave 70 industry/prefecture intersection + foundation):
--   wave95_residency → packet_data_residency_disclosure_v1
--   wave95_cross_border → packet_cross_border_data_transfer_v1
--   wave97_third_party_xfer → packet_third_party_data_transfer_v1
--   wave70_industry → packet_industry_x_prefecture_houjin_v1
--   wave70_prefecture → packet_prefecture_x_industry_density_v1
--   foundation → packet_houjin_360
--
-- Scan target: ~150-600MB (6 sources, per-jsic_major aggregate then
-- overlay, residency arm sparsely populated at Wave 95-97 snapshot
-- so scan is dominated by Wave 70 + foundation).
-- Expected row count: ≤ 240 (6 src × ~20 jsic_major; LIMIT 1000
-- safety).
-- Time estimate: ≤ 90s on Athena engine v3 (workgroup result reuse
-- ON, 50GB BytesScannedCutoffPerQuery PERF-14 cap honored).
--
-- Output schema (9 cols):
--   wave_family / src / jsic_major / row_count /
--   distinct_subjects / residency_signal_present /
--   program_offering_signal_present /
--   residency_vs_program_density_ratio / signal_role

WITH all_sources AS (
  -- wave95_residency: data residency disclosure (国内 vs 海外 signal)
  SELECT 'wave95_residency' AS wave_family,
         'data_residency_disclosure' AS src,
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK') AS jsic_major,
         json_extract_scalar(subject, '$.id') AS subject_id,
         'residency' AS signal_role
  FROM jpcite_credit_2026_05.packet_data_residency_disclosure_v1

  -- wave95_cross_border: cross-border data transfer (海外移転 signal)
  UNION ALL
  SELECT 'wave95_cross_border',
         'cross_border_data_transfer',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'residency'
  FROM jpcite_credit_2026_05.packet_cross_border_data_transfer_v1

  -- wave97_third_party_xfer: third-party data transfer (委託先 signal)
  UNION ALL
  SELECT 'wave97_third_party_xfer',
         'third_party_data_transfer',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'residency'
  FROM jpcite_credit_2026_05.packet_third_party_data_transfer_v1

  -- wave70_industry: industry × prefecture houjin (program-offering anchor)
  UNION ALL
  SELECT 'wave70_industry',
         'industry_x_prefecture_houjin',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'program_offering'
  FROM jpcite_credit_2026_05.packet_industry_x_prefecture_houjin_v1

  -- wave70_prefecture: prefecture × industry density (program density)
  UNION ALL
  SELECT 'wave70_prefecture',
         'prefecture_x_industry_density',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'program_offering'
  FROM jpcite_credit_2026_05.packet_prefecture_x_industry_density_v1

  -- foundation: houjin_360 baseline (universe anchor)
  UNION ALL
  SELECT 'foundation',
         'houjin_360',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'foundation'
  FROM jpcite_credit_2026_05.packet_houjin_360
),
agg AS (
  SELECT
    wave_family,
    src,
    jsic_major,
    signal_role,
    COUNT(*) AS row_count,
    approx_distinct(subject_id) AS distinct_subjects
  FROM all_sources
  GROUP BY wave_family, src, jsic_major, signal_role
),
role_totals AS (
  SELECT
    signal_role,
    SUM(row_count) AS role_total_rows
  FROM agg
  GROUP BY signal_role
)
SELECT
  a.wave_family,
  a.src,
  a.jsic_major,
  a.row_count,
  a.distinct_subjects,
  -- residency_signal_present: 1 if this row is a residency arm with
  -- any observed signal — read as "this JSIC has ≥1 residency
  -- disclosure / cross-border / third-party-transfer signal in this
  -- wave_family".
  CASE WHEN a.signal_role = 'residency' AND a.row_count > 0 THEN 1 ELSE 0 END
    AS residency_signal_present,
  -- program_offering_signal_present: 1 if this row is a program-
  -- offering arm with any observed signal — read as "this JSIC has
  -- ≥1 prefecture-anchored program-offering footprint signal".
  CASE WHEN a.signal_role = 'program_offering' AND a.row_count > 0 THEN 1 ELSE 0 END
    AS program_offering_signal_present,
  -- residency_vs_program_density_ratio: this row's row_count normalized
  -- by the role total (residency / program_offering / foundation) —
  -- high values = this (wave_family, jsic_major) cell is a dominant
  -- contributor to its role's footprint.
  CASE
    WHEN rt.role_total_rows = 0 THEN 0.0
    ELSE CAST(a.row_count AS DOUBLE) / CAST(rt.role_total_rows AS DOUBLE)
  END AS residency_vs_program_density_ratio,
  a.signal_role
FROM agg a
JOIN role_totals rt ON a.signal_role = rt.signal_role
ORDER BY a.signal_role, a.row_count DESC, a.wave_family
LIMIT 1000
