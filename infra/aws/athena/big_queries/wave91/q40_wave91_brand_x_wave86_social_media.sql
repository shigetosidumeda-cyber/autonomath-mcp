-- q40_wave91_brand_x_wave86_social_media.sql (Wave 89-91)
--
-- Wave 91 brand / customer-proxy family × Wave 86 social media /
-- digital presence family cross-join. The brand × social-media axis
-- is the canonical brand-equity vs digital-engagement alignment
-- surface: when a corp has BOTH (a) brand / customer-proxy signal
-- (Wave 91 — trademark protection, review sentiment, IR intensity,
-- press release pulse) AND (b) social media / digital presence
-- signal (Wave 86 — community engagement, corporate website, content
-- publication velocity, influencer partnership), the brand-equity /
-- GTM advisor can read the brand-trust-to-digital-engagement
-- alignment density. Cross-join produces the bilateral surface that
-- brand DD + marketing-spend efficacy review needs.
--
-- Wave 91 (brand metrics / customer proxy) tables in scope (live
-- proxies in Glue; smoke-only Wave 91 packets like NPS_proxy /
-- pricing_power / market_share are pre-sync):
--   trademark_brand_protection / trademark_industry_density /
--   trademark_registration_intensity / review_sentiment_aggregate /
--   investor_relations_intensity / press_release_pulse /
--   media_relations_pattern.
--
-- Wave 86 (social media / digital presence) tables in scope:
--   community_engagement_intensity / corporate_website_signal /
--   content_publication_velocity / influencer_partnership_signal.
--
-- Pattern: per-family rollup (COUNT + approx_distinct subject.id)
-- CROSS JOIN producing (brand_family, social_family) pairs with
-- combined coverage density + brand-social alignment ratio. Honors
-- the 50 GB PERF-14 cap.

WITH wave91_brand AS (
  SELECT 'trademark_brand_protection' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1

  UNION ALL
  SELECT 'trademark_industry_density',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1

  UNION ALL
  SELECT 'trademark_registration_intensity',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_trademark_registration_intensity_v1

  UNION ALL
  SELECT 'review_sentiment_aggregate',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_review_sentiment_aggregate_v1

  UNION ALL
  SELECT 'investor_relations_intensity',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_investor_relations_intensity_v1

  UNION ALL
  SELECT 'press_release_pulse',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_press_release_pulse_v1

  UNION ALL
  SELECT 'media_relations_pattern',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_media_relations_pattern_v1
),
wave86_social AS (
  SELECT 'community_engagement_intensity' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_community_engagement_intensity_v1

  UNION ALL
  SELECT 'corporate_website_signal',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_corporate_website_signal_v1

  UNION ALL
  SELECT 'content_publication_velocity',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_content_publication_velocity_v1

  UNION ALL
  SELECT 'influencer_partnership_signal',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_influencer_partnership_signal_v1
)
SELECT
  b.src AS wave91_brand_family,
  b.row_count AS brand_row_count,
  b.approx_distinct_subjects AS brand_distinct_subjects,
  s.src AS wave86_social_family,
  s.row_count AS social_row_count,
  s.approx_distinct_subjects AS social_distinct_subjects,
  -- brand-social alignment: distinct subjects ratio capped at 1.0.
  -- Reads as "% of social-media-tracked subjects that also carry a
  -- brand / customer-proxy signal" — proxy for brand-equity vs
  -- digital-engagement coherence.
  CASE
    WHEN s.approx_distinct_subjects = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(b.approx_distinct_subjects AS DOUBLE)
               / CAST(s.approx_distinct_subjects AS DOUBLE))
  END AS brand_social_alignment_density
FROM wave91_brand b
CROSS JOIN wave86_social s
ORDER BY b.row_count DESC, s.row_count DESC
LIMIT 200
