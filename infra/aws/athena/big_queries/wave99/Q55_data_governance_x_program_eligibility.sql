-- Q55_data_governance_x_program_eligibility.sql (Wave 99)
--
-- Data governance × program eligibility — Wave 95-97 data governance
-- packet density × foundation_houjin_360 × employment program
-- eligibility (the only program_eligibility surface live in Glue).
-- Reads as: which houjin universe carries simultaneous data governance
-- signal AND program eligibility (補助金 / 助成金) footprint?
--
-- Strategic read: high-density cells = houjin who can both demonstrate
-- 個人情報保護法 §23 安全管理措置 (via data governance packets) AND
-- claim 助成金 eligibility (via employment_program_eligibility). These
-- are the "compliance-ready cohort" that a 補助金 consultant / 税理士
-- can fast-path for joint submission packages.
--
-- 6-source cross-section (all LIVE in Glue, Wave 95-97 governance +
-- foundation + program_eligibility):
--   wave95_classification → packet_data_classification_intensity_v1
--   wave96_master_data → packet_master_data_governance_v1
--   wave96_data_quality → packet_data_quality_audit_v1
--   wave97_breach_log → packet_data_breach_event_log_v1
--   foundation → packet_houjin_360 (houjin universe baseline)
--   program_eligibility → packet_employment_program_eligibility_v1
--
-- Scan target: ~100-500MB (6 sources, per-jsic_major aggregate then
-- 6-way overlay, no full-row materialization).
-- Expected row count: ≤ 240 (6 src × ~20 jsic_major + cross-source
-- overlay; LIMIT 1000 safety).
-- Time estimate: ≤ 75s on Athena engine v3 (workgroup result reuse
-- ON, 50GB BytesScannedCutoffPerQuery PERF-14 cap honored).
--
-- Output schema (9 cols):
--   wave_family / src / jsic_major / row_count /
--   distinct_subjects / governance_signal_present /
--   eligibility_signal_present / pct_of_family_total /
--   compliance_ready_proxy

WITH all_sources AS (
  -- wave95_classification: data classification intensity (governance)
  SELECT 'wave95_classification' AS wave_family,
         'data_classification_intensity' AS src,
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK') AS jsic_major,
         json_extract_scalar(subject, '$.id') AS subject_id,
         'governance' AS signal_class
  FROM jpcite_credit_2026_05.packet_data_classification_intensity_v1

  -- wave96_master_data: master data governance (governance)
  UNION ALL
  SELECT 'wave96_master_data',
         'master_data_governance',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'governance'
  FROM jpcite_credit_2026_05.packet_master_data_governance_v1

  -- wave96_data_quality: data quality audit (governance)
  UNION ALL
  SELECT 'wave96_data_quality',
         'data_quality_audit',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'governance'
  FROM jpcite_credit_2026_05.packet_data_quality_audit_v1

  -- wave97_breach_log: breach event log (governance — incident signal)
  UNION ALL
  SELECT 'wave97_breach_log',
         'data_breach_event_log',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'governance'
  FROM jpcite_credit_2026_05.packet_data_breach_event_log_v1

  -- foundation: houjin_360 baseline (universe anchor)
  UNION ALL
  SELECT 'foundation',
         'houjin_360',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'foundation'
  FROM jpcite_credit_2026_05.packet_houjin_360

  -- program_eligibility: employment program eligibility (eligibility arm)
  UNION ALL
  SELECT 'program_eligibility',
         'employment_program_eligibility',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id'),
         'eligibility'
  FROM jpcite_credit_2026_05.packet_employment_program_eligibility_v1
),
family_totals AS (
  SELECT wave_family, COUNT(*) AS family_total
  FROM all_sources
  GROUP BY wave_family
),
agg AS (
  SELECT
    wave_family,
    src,
    jsic_major,
    signal_class,
    COUNT(*) AS row_count,
    approx_distinct(subject_id) AS distinct_subjects
  FROM all_sources
  GROUP BY wave_family, src, jsic_major, signal_class
)
SELECT
  a.wave_family,
  a.src,
  a.jsic_major,
  a.row_count,
  a.distinct_subjects,
  -- governance_signal_present: 1 if this row is a governance arm with
  -- any observed signal — read as "this JSIC has ≥1 governance signal
  -- in this wave_family".
  CASE WHEN a.signal_class = 'governance' AND a.row_count > 0 THEN 1 ELSE 0 END
    AS governance_signal_present,
  -- eligibility_signal_present: 1 if this row is an eligibility arm
  -- with any observed signal — read as "this JSIC has ≥1 助成金
  -- eligibility signal in this wave_family".
  CASE WHEN a.signal_class = 'eligibility' AND a.row_count > 0 THEN 1 ELSE 0 END
    AS eligibility_signal_present,
  -- pct_of_family_total: this jsic_major's share of the wave_family
  -- footprint.
  CASE
    WHEN ft.family_total = 0 THEN 0.0
    ELSE CAST(a.row_count AS DOUBLE) / CAST(ft.family_total AS DOUBLE)
  END AS pct_of_family_total,
  -- compliance_ready_proxy: distinct_subjects normalized by row_count —
  -- governance arm high values = many distinct houjin per row (broad
  -- compliance cohort proxy); eligibility arm high values = many
  -- distinct houjin per eligibility row (broad eligibility cohort).
  CASE
    WHEN a.row_count = 0 THEN 0.0
    ELSE CAST(a.distinct_subjects AS DOUBLE) / CAST(a.row_count AS DOUBLE)
  END AS compliance_ready_proxy
FROM agg a
JOIN family_totals ft ON a.wave_family = ft.wave_family
ORDER BY a.signal_class, a.wave_family, a.row_count DESC
LIMIT 1000
