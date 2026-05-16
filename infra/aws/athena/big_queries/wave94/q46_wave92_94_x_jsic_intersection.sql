-- q46_wave92_94_x_jsic_intersection.sql (Wave 92-94)
--
-- Wave 92 (product safety / quality compliance) + Wave 93 (real estate
-- / property) + Wave 94 (insurance / risk transfer) × jsic_major
-- intersection. Three new wave families rolled up against the
-- canonical JSIC industry axis used by wave70/q21, wave82/q26,
-- wave85/q31, wave88/q36, wave91/q41. Tables without jsic_major are
-- bucketed to 'UNK' so the per-family row totals stay honest.
--
-- The 3-bucket Wave 92-94 surface this produces is the product-
-- safety + real-estate-footprint + risk-transfer cross-section
-- sliced on industry — the canonical "which JSIC sector carries the
-- most product-safety + property + insurance signal density" view.
--
-- Pattern: SELECT 1 per row with json_extract_scalar(subject,
-- '$.jsic_major') as the axis. Foundation packet_houjin_360 is added
-- so the baseline JSIC distribution is observable in the same output.
-- Honors the 50 GB PERF-14 cap.

WITH all_packets AS (
  -- Wave 92 product safety / quality compliance (live proxies)
  SELECT 'wave92_product_safety' AS wave_family, 'product_recall_intensity' AS src,
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK') AS jsic_major
  FROM jpcite_credit_2026_05.packet_product_recall_intensity_v1

  UNION ALL SELECT 'wave92_product_safety', 'product_safety_recall_intensity',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_product_safety_recall_intensity_v1

  UNION ALL SELECT 'wave92_product_safety', 'product_lifecycle_pulse',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_product_lifecycle_pulse_v1

  UNION ALL SELECT 'wave92_product_safety', 'product_diversification_intensity',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_product_diversification_intensity_v1

  UNION ALL SELECT 'wave92_product_safety', 'ai_safety_certification',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_ai_safety_certification_v1

  UNION ALL SELECT 'wave92_product_safety', 'consumer_protection_compliance',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_consumer_protection_compliance_v1

  UNION ALL SELECT 'wave92_product_safety', 'min_price_violation_history',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_min_price_violation_history_v1

  -- Wave 93 real estate / property (live proxies; full Wave 93 batch
  -- pre-Glue sync)
  UNION ALL SELECT 'wave93_real_estate', 'retail_inbound_subsidy',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_retail_inbound_subsidy_v1

  UNION ALL SELECT 'wave93_real_estate', 'landslide_geotechnical_risk',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_landslide_geotechnical_risk_v1

  UNION ALL SELECT 'wave93_real_estate', 'industry_x_prefecture_houjin',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_industry_x_prefecture_houjin_v1

  -- Wave 94 insurance / risk transfer (live proxies; full Wave 94
  -- batch pre-Glue sync)
  UNION ALL SELECT 'wave94_insurance', 'ai_safety_certification',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_ai_safety_certification_v1

  UNION ALL SELECT 'wave94_insurance', 'data_breach_event_history',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_data_breach_event_history_v1

  UNION ALL SELECT 'wave94_insurance', 'cybersecurity_certification',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_cybersecurity_certification_v1

  -- Foundation anchor (houjin_360) so the JSIC distribution baseline
  -- is observable in the same output
  UNION ALL SELECT 'foundation', 'houjin_360',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_houjin_360
)
SELECT
  wave_family,
  jsic_major,
  COUNT(*) AS row_count,
  COUNT(DISTINCT src) AS distinct_packet_sources
FROM all_packets
GROUP BY wave_family, jsic_major
ORDER BY wave_family, row_count DESC
LIMIT 500
