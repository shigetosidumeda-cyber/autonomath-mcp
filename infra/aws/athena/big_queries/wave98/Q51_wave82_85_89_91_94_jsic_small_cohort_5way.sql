-- Q51_wave82_85_89_91_94_jsic_small_cohort_5way.sql (Wave 98)
--
-- 5-way thin-but-recent newer-family JSIC small-cohort aggregate —
-- Wave 82 (IP / innovation) + Wave 85 (cybersec) + Wave 89 (M&A /
-- succession) + Wave 91 (brand / customer proxy) + Wave 94 (insurance
-- / risk transfer). 5 newer wave families sliced on the canonical
-- JSIC major axis, with foundation packet_houjin_360 as the baseline
-- distribution anchor.
--
-- This is the "recent-cohort signal density × industry" cross-section
-- — answers: which JSIC sector carries the most IP + cybersec + M&A
-- + brand + insurance signal density in the newer (post-Wave-80) wave
-- families? Reads as a 5-way risk-transfer-aware industry heatmap.
--
-- Wave families × 1 representative table each (LIVE in Glue):
--   wave82_ip → packet_patent_filing_velocity_v1
--   wave85_cybersec → packet_cybersecurity_certification_v1
--   wave89_ma → packet_m_a_event_signals_v1
--   wave91_brand → packet_trademark_brand_protection_v1
--   wave94_insurance → packet_ai_safety_certification_v1
--   foundation → packet_houjin_360 (baseline JSIC distribution)
--
-- Scan target: ~150-500MB (6 UNION ALL on representative tables,
-- jsic_major column read only, COUNT + DISTINCT aggregation).
-- Expected row count: ≤ 120 (6 wave_family × ~20 jsic_major buckets =
-- ~120; LIMIT 1000 safety).
-- Time estimate: ≤ 60s on Athena engine v3 (workgroup result reuse
-- ON, 50GB BytesScannedCutoffPerQuery PERF-14 cap honored).
--
-- Output schema (5 cols):
--   wave_family / jsic_major / row_count / distinct_packet_sources /
--   thin_recent_density_proxy

WITH all_packets AS (
  -- Wave 82 IP / innovation (representative: patent filing velocity)
  SELECT 'wave82_ip' AS wave_family,
         'patent_filing_velocity' AS src,
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK') AS jsic_major
  FROM jpcite_credit_2026_05.packet_patent_filing_velocity_v1

  -- Wave 85 cybersec (representative: cybersecurity certification)
  UNION ALL
  SELECT 'wave85_cybersec',
         'cybersecurity_certification',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_cybersecurity_certification_v1

  -- Wave 89 M&A / succession (representative: M&A event signals)
  UNION ALL
  SELECT 'wave89_ma',
         'm_a_event_signals',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_m_a_event_signals_v1

  -- Wave 91 brand (representative: trademark brand protection)
  UNION ALL
  SELECT 'wave91_brand',
         'trademark_brand_protection',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1

  -- Wave 94 insurance / risk transfer (representative: AI safety cert)
  UNION ALL
  SELECT 'wave94_insurance',
         'ai_safety_certification',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_ai_safety_certification_v1

  -- Foundation anchor (houjin_360) so the JSIC distribution baseline
  -- is observable in the same output
  UNION ALL
  SELECT 'foundation',
         'houjin_360',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_houjin_360
)
SELECT
  wave_family,
  jsic_major,
  COUNT(*) AS row_count,
  COUNT(DISTINCT src) AS distinct_packet_sources,
  -- thin_recent_density_proxy: log-scaled row_count proxy to surface
  -- thin-cohort sectors that still carry recent-wave signal density.
  -- Reads as "even small recent-wave footprint in a JSIC bucket is
  -- signal" — useful for niche-sector DD where the absolute count
  -- is low but presence in 3+ recent waves indicates focus.
  CAST(LN(CAST(COUNT(*) AS DOUBLE) + 1.0) AS DECIMAL(10, 4))
    AS thin_recent_density_proxy
FROM all_packets
GROUP BY wave_family, jsic_major
ORDER BY wave_family, row_count DESC
LIMIT 1000
