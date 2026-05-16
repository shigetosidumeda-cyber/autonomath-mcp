-- q36_wave86_88_x_jsic_intersection.sql (Wave 86-88)
--
-- Wave 86 (social media / digital presence) + Wave 87 (procurement /
-- public contracting) + Wave 88 (corporate activism / political) ×
-- jsic_major intersection. Three new wave families rolled up against
-- the canonical JSIC industry axis used by wave70/q21, wave82/q26,
-- and wave85/q31. Tables without jsic_major are bucketed to 'UNK' so
-- the per-family row totals stay honest.
--
-- The 3-bucket Wave 86-88 surface this produces is the brand-
-- engagement + public-contracting + political-economic signal
-- cross-section, sliced on industry — the canonical "which JSIC
-- sector carries the most social media + procurement + activism
-- signal density" view.
--
-- Pattern: SELECT 1 per row with json_extract_scalar(subject,
-- '$.jsic_major') as the axis. Foundation packet_houjin_360 is added
-- so the baseline JSIC distribution is observable in the same output.
-- Tables missing in Glue catalog return 0 row; the bucket stays
-- visible but flat. Honors the 50 GB PERF-14 cap.

WITH all_packets AS (
  -- Wave 86 social media / digital presence (live proxies)
  SELECT 'wave86_social_media' AS wave_family, 'community_engagement_intensity' AS src,
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK') AS jsic_major
  FROM jpcite_credit_2026_05.packet_community_engagement_intensity_v1

  UNION ALL SELECT 'wave86_social_media', 'trademark_brand_protection',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1

  UNION ALL SELECT 'wave86_social_media', 'trademark_industry_density',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1

  -- Wave 87 procurement / public contracting (live proxies)
  UNION ALL SELECT 'wave87_procurement', 'public_procurement_trend',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_public_procurement_trend_v1

  UNION ALL SELECT 'wave87_procurement', 'bid_announcement_seasonality',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_bid_announcement_seasonality_v1

  UNION ALL SELECT 'wave87_procurement', 'construction_public_works',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_construction_public_works_v1

  -- Wave 88 corporate activism / political (live proxies)
  UNION ALL SELECT 'wave88_activism', 'industry_association_link',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_industry_association_link_v1

  UNION ALL SELECT 'wave88_activism', 'regulatory_change_industry_impact',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_regulatory_change_industry_impact_v1

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
