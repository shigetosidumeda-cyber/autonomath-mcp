-- q25_wave82_ip_x_wave76_startup_growth.sql (Wave 80-82)
--
-- Wave 82 IP/innovation family × Wave 76 startup/scaleup growth signal
-- cross-reference. Wave 82 (catalog 302 → 312) carries the IP surface:
-- patent_corp_360, patent_environmental_link, patent_subsidy_intersection,
-- trademark_brand_protection, trademark_industry_density. Wave 76
-- (catalog 242 → 252) carries the startup signal: business_lifecycle_stage,
-- capital_raising_history, funding_to_revenue_ratio, kpi_funding_correlation.
--
-- Goal: produce a per-IP-family row count and a parallel startup-side
-- row count, plus the implied "patent density per growth signal" ratio.
-- This is the canonical surface a startup / scale-up M&A advisor needs:
-- "given growth signal X, how many IP rights does this entity already
-- protect?"
--
-- Pattern: per-family rollup (COUNT) CROSS JOIN with the startup baseline.
-- Honors the 50 GB PERF-14 cap; expected scan well under 1 GB.

WITH wave82_ip AS (
  SELECT 'patent_corp_360' AS src, COUNT(*) AS row_count
  FROM jpcite_credit_2026_05.packet_patent_corp_360_v1

  UNION ALL SELECT 'patent_environmental_link', COUNT(*)
  FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1

  UNION ALL SELECT 'patent_subsidy_intersection', COUNT(*)
  FROM jpcite_credit_2026_05.packet_patent_subsidy_intersection_v1

  UNION ALL SELECT 'trademark_brand_protection', COUNT(*)
  FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1

  UNION ALL SELECT 'trademark_industry_density', COUNT(*)
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
),
wave76_startup AS (
  SELECT 'business_lifecycle_stage' AS src, COUNT(*) AS row_count
  FROM jpcite_credit_2026_05.packet_business_lifecycle_stage_v1

  UNION ALL SELECT 'capital_raising_history', COUNT(*)
  FROM jpcite_credit_2026_05.packet_capital_raising_history_v1

  UNION ALL SELECT 'funding_to_revenue_ratio', COUNT(*)
  FROM jpcite_credit_2026_05.packet_funding_to_revenue_ratio_v1

  UNION ALL SELECT 'kpi_funding_correlation', COUNT(*)
  FROM jpcite_credit_2026_05.packet_kpi_funding_correlation_v1
),
ip_rollup AS (
  SELECT 'wave82_ip' AS family, SUM(row_count) AS total_rows,
         COUNT(*) AS distinct_packet_sources
  FROM wave82_ip
),
startup_rollup AS (
  SELECT 'wave76_startup' AS family, SUM(row_count) AS total_rows,
         COUNT(*) AS distinct_packet_sources
  FROM wave76_startup
)
SELECT
  i.family AS ip_family,
  i.total_rows AS ip_total_rows,
  i.distinct_packet_sources AS ip_packet_sources,
  s.family AS startup_family,
  s.total_rows AS startup_total_rows,
  s.distinct_packet_sources AS startup_packet_sources,
  -- patent density per growth signal: IP rows per startup row, capped at 50
  CASE
    WHEN s.total_rows = 0 THEN 0.0
    ELSE LEAST(50.0, CAST(i.total_rows AS DOUBLE) / CAST(s.total_rows AS DOUBLE))
  END AS patent_density_per_growth_signal,
  -- intersection density: smaller / larger, capped at 1.0
  CASE
    WHEN GREATEST(i.total_rows, s.total_rows) = 0 THEN 0.0
    ELSE CAST(LEAST(i.total_rows, s.total_rows) AS DOUBLE)
         / CAST(GREATEST(i.total_rows, s.total_rows) AS DOUBLE)
  END AS ip_startup_intersection_density
FROM ip_rollup i
CROSS JOIN startup_rollup s
LIMIT 50
