-- q24_wave81_esg_x_wave60_65_finance_intersection.sql (Wave 80-82)
--
-- Wave 81 ESG-materiality family × Wave 60-65 finance / green-finance
-- intersection. Wave 81 (catalog 292 → 302) carries the canonical ESG
-- surface: carbon credit inventory, carbon reporting compliance, climate
-- alignment target, climate transition plan, physical climate risk geo.
-- Wave 60-65 carries the bond / sustainability-linked-loan / green-bond /
-- transition-finance side. Together they form the canonical
-- "ESG disclosure × ESG financing instrument" intersection.
--
-- Goal: for each ESG axis, count rows on the ESG side AND on the matched
-- finance side. Report the implied "instrument density per ESG signal"
-- ratio. This is the surface a sustainability advisor / transition-loan
-- underwriter needs.
--
-- Pattern: per-family rollup (COUNT + json_extract_scalar denominator)
-- CROSS JOIN with the finance baseline. The finance baseline aggregates
-- 5 Wave 60-65 finance tables. Honors the 50 GB PERF-14 cap.

WITH wave81_esg AS (
  SELECT 'carbon_credit_inventory' AS src, COUNT(*) AS row_count
  FROM jpcite_credit_2026_05.packet_carbon_credit_inventory_v1

  UNION ALL SELECT 'carbon_reporting_compliance', COUNT(*)
  FROM jpcite_credit_2026_05.packet_carbon_reporting_compliance_v1

  UNION ALL SELECT 'climate_alignment_target', COUNT(*)
  FROM jpcite_credit_2026_05.packet_climate_alignment_target_v1

  UNION ALL SELECT 'climate_transition_plan', COUNT(*)
  FROM jpcite_credit_2026_05.packet_climate_transition_plan_v1

  UNION ALL SELECT 'physical_climate_risk_geo', COUNT(*)
  FROM jpcite_credit_2026_05.packet_physical_climate_risk_geo_v1
),
wave60_65_finance AS (
  -- Wave 60-65 green-finance + transition-finance instrument side
  SELECT 'bond_issuance_pattern' AS src, COUNT(*) AS row_count
  FROM jpcite_credit_2026_05.packet_bond_issuance_pattern_v1

  UNION ALL SELECT 'green_bond_issuance', COUNT(*)
  FROM jpcite_credit_2026_05.packet_green_bond_issuance_v1

  UNION ALL SELECT 'sustainability_linked_loan', COUNT(*)
  FROM jpcite_credit_2026_05.packet_sustainability_linked_loan_v1

  UNION ALL SELECT 'transition_finance_eligibility', COUNT(*)
  FROM jpcite_credit_2026_05.packet_transition_finance_eligibility_v1

  UNION ALL SELECT 'finance_fintech_regulation', COUNT(*)
  FROM jpcite_credit_2026_05.packet_finance_fintech_regulation_v1
),
esg_rollup AS (
  SELECT
    'wave81_esg' AS family,
    SUM(row_count) AS total_rows,
    COUNT(*) AS distinct_packet_sources
  FROM wave81_esg
),
fin_rollup AS (
  SELECT
    'wave60_65_finance' AS family,
    SUM(row_count) AS total_rows,
    COUNT(*) AS distinct_packet_sources
  FROM wave60_65_finance
)
SELECT
  e.family AS esg_family,
  e.total_rows AS esg_total_rows,
  e.distinct_packet_sources AS esg_packet_sources,
  f.family AS finance_family,
  f.total_rows AS finance_total_rows,
  f.distinct_packet_sources AS finance_packet_sources,
  -- intersection density: smaller side / larger side, capped at 1.0
  CASE
    WHEN GREATEST(e.total_rows, f.total_rows) = 0 THEN 0.0
    ELSE CAST(LEAST(e.total_rows, f.total_rows) AS DOUBLE)
         / CAST(GREATEST(e.total_rows, f.total_rows) AS DOUBLE)
  END AS esg_finance_intersection_density,
  -- per-family instrument density: finance rows per ESG row
  CASE
    WHEN e.total_rows = 0 THEN 0.0
    ELSE CAST(f.total_rows AS DOUBLE) / CAST(e.total_rows AS DOUBLE)
  END AS finance_instruments_per_esg_row
FROM esg_rollup e
CROSS JOIN fin_rollup f
LIMIT 50
