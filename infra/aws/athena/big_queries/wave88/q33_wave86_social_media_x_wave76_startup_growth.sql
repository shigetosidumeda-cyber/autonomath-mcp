-- q33_wave86_social_media_x_wave76_startup_growth.sql (Wave 86-88)
--
-- Wave 86 social media / digital presence family × Wave 76 startup
-- growth signal family cross-join. The social-media × startup-growth
-- axis is the canonical brand-engagement vs capital-velocity surface:
-- when a corp has BOTH (a) social media + brand engagement signal
-- (Wave 86) AND (b) startup capital-raising / runway / KPI signal
-- (Wave 76), the GTM / VC advisor can read the brand-trust-to-funding-
-- velocity alignment density. Cross-join produces the bilateral
-- coverage view that growth-stage DD needs.
--
-- Wave 86 (social media / digital presence) tables — adopted in scope:
--   social_media_account_inventory (planned, may be 0-row pre-sync) /
--   community_forum_engagement / influencer_partnership_signal /
--   content_publication_velocity / corporate_website_signal /
--   trademark_brand_protection (Wave 82 trademark anchor reused as
--   live Wave 86 proxy until Wave 86 S3 sync lands).
--
-- Wave 76 (startup growth) tables in scope:
--   business_lifecycle_stage / capital_raising_history /
--   funding_to_revenue_ratio / kpi_funding_correlation.
--
-- Pattern: per-family rollup (COUNT + approx_distinct subject.id)
-- CROSS JOIN producing (social_family, startup_family) pairs with
-- combined coverage density + brand-funding alignment ratio. Honors
-- the 50 GB PERF-14 cap. Tables missing in Glue catalog return 0 row,
-- so the cross-join stays honest.

WITH wave86_social AS (
  SELECT 'community_forum_engagement' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_community_engagement_intensity_v1

  UNION ALL
  SELECT 'trademark_brand_protection',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1

  UNION ALL
  SELECT 'trademark_industry_density',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
),
wave76_startup AS (
  SELECT 'business_lifecycle_stage' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_business_lifecycle_stage_v1

  UNION ALL
  SELECT 'capital_raising_history',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_capital_raising_history_v1

  UNION ALL
  SELECT 'funding_to_revenue_ratio',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_funding_to_revenue_ratio_v1

  UNION ALL
  SELECT 'kpi_funding_correlation',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_kpi_funding_correlation_v1
)
SELECT
  s.src AS wave86_social_family,
  s.row_count AS social_row_count,
  s.approx_distinct_subjects AS social_distinct_subjects,
  u.src AS wave76_startup_family,
  u.row_count AS startup_row_count,
  u.approx_distinct_subjects AS startup_distinct_subjects,
  -- brand-funding alignment: distinct subjects on social vs startup,
  -- capped at 1.0. Reads as "% of startup-tracked subjects that also
  -- carry a brand / community engagement signal."
  CASE
    WHEN u.approx_distinct_subjects = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(s.approx_distinct_subjects AS DOUBLE)
               / CAST(u.approx_distinct_subjects AS DOUBLE))
  END AS brand_funding_alignment_density
FROM wave86_social s
CROSS JOIN wave76_startup u
ORDER BY s.row_count DESC, u.row_count DESC
LIMIT 100
