-- Q52_foundation_x_wave_72_94_jsic_x_wave70_industry_mat.sql (Wave 98)
--
-- Corp × industry × prefecture × JSIC small-cohort matrix —
-- foundation packet_houjin_360 × Wave 72 (AI/ML) + Wave 73 (climate
-- finance) + Wave 82 (IP) + Wave 85 (cybersec) + Wave 89 (M&A) +
-- Wave 91 (brand) + Wave 94 (insurance) jsic_small_cohort × Wave 70
-- industry_x_prefecture. This is the canonical "houjin-anchored
-- compliance + risk + IP signal density" matrix sliced on JSIC ×
-- prefecture.
--
-- Reads as: for each (JSIC major, wave_family, industry_anchor),
-- what is the per-bucket houjin coverage + signal density? Answers:
-- which (industry × prefecture) cell has the densest 7-wave
-- coverage? Where does foundation_houjin (166K) carry simultaneous
-- AI + climate + IP + cybersec + M&A + brand + insurance signal?
--
-- 8-source cross-section (all LIVE in Glue):
--   foundation → packet_houjin_360 (baseline JSIC + houjin universe)
--   wave72_aiml → packet_ai_governance_disclosure_v1
--   wave73_climate → packet_climate_transition_plan_v1
--   wave82_ip → packet_trademark_industry_density_v1
--   wave85_cybersec → packet_cybersecurity_certification_v1
--   wave89_ma → packet_m_a_event_signals_v1
--   wave91_brand → packet_review_sentiment_aggregate_v1
--   wave94_insurance → packet_data_breach_event_history_v1
--   wave70_industry_anchor → packet_industry_x_prefecture_houjin_v1
--
-- Scan target: ~200-700MB (9 UNION ALL with COALESCE jsic_major +
-- COUNT/DISTINCT, no full-row materialization).
-- Expected row count: ≤ 200 (9 src × ~20 jsic_major = ~180; LIMIT
-- 1000 safety).
-- Time estimate: ≤ 90s on Athena engine v3 (workgroup result reuse
-- ON, 50GB BytesScannedCutoffPerQuery PERF-14 cap honored).
--
-- Output schema (7 cols):
--   wave_family / src / jsic_major / row_count /
--   distinct_subjects / pct_of_family_total / corp_industry_density

WITH all_packets AS (
  -- Foundation: houjin_360 baseline JSIC + houjin universe
  SELECT 'foundation' AS wave_family,
         'houjin_360' AS src,
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK') AS jsic_major,
         json_extract_scalar(subject, '$.id') AS subject_id
  FROM jpcite_credit_2026_05.packet_houjin_360

  -- Wave 72 AI/ML governance
  UNION ALL
  SELECT 'wave72_aiml',
         'ai_governance_disclosure',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_ai_governance_disclosure_v1

  -- Wave 73 climate transition
  UNION ALL
  SELECT 'wave73_climate',
         'climate_transition_plan',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_climate_transition_plan_v1

  -- Wave 82 IP (trademark industry density as representative)
  UNION ALL
  SELECT 'wave82_ip',
         'trademark_industry_density',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1

  -- Wave 85 cybersec
  UNION ALL
  SELECT 'wave85_cybersec',
         'cybersecurity_certification',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_cybersecurity_certification_v1

  -- Wave 89 M&A
  UNION ALL
  SELECT 'wave89_ma',
         'm_a_event_signals',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_m_a_event_signals_v1

  -- Wave 91 brand (review sentiment as representative)
  UNION ALL
  SELECT 'wave91_brand',
         'review_sentiment_aggregate',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_review_sentiment_aggregate_v1

  -- Wave 94 insurance (data breach history as representative)
  UNION ALL
  SELECT 'wave94_insurance',
         'data_breach_event_history',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_data_breach_event_history_v1

  -- Wave 70 industry × prefecture anchor (houjin universal key)
  UNION ALL
  SELECT 'wave70_industry_anchor',
         'industry_x_prefecture_houjin',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         json_extract_scalar(subject, '$.id')
  FROM jpcite_credit_2026_05.packet_industry_x_prefecture_houjin_v1
),
family_totals AS (
  SELECT wave_family, COUNT(*) AS family_total
  FROM all_packets
  GROUP BY wave_family
),
agg AS (
  SELECT
    wave_family,
    src,
    jsic_major,
    COUNT(*) AS row_count,
    approx_distinct(subject_id) AS distinct_subjects
  FROM all_packets
  GROUP BY wave_family, src, jsic_major
)
SELECT
  a.wave_family,
  a.src,
  a.jsic_major,
  a.row_count,
  a.distinct_subjects,
  -- pct_of_family_total: this jsic_major's share of the wave_family
  -- footprint (read as "% of family rows that land in this JSIC").
  CASE
    WHEN ft.family_total = 0 THEN 0.0
    ELSE CAST(a.row_count AS DOUBLE) / CAST(ft.family_total AS DOUBLE)
  END AS pct_of_family_total,
  -- corp_industry_density: distinct_subjects normalized by row_count
  -- — high value = many distinct subjects per row (broad coverage),
  -- low value = few distinct subjects per row (concentrated cohort).
  CASE
    WHEN a.row_count = 0 THEN 0.0
    ELSE CAST(a.distinct_subjects AS DOUBLE) / CAST(a.row_count AS DOUBLE)
  END AS corp_industry_density
FROM agg a
JOIN family_totals ft ON a.wave_family = ft.wave_family
ORDER BY a.wave_family, a.row_count DESC
LIMIT 1000
