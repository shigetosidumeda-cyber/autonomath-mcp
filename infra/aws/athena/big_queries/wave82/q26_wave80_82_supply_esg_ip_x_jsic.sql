-- q26_wave80_82_supply_esg_ip_x_jsic.sql (Wave 80-82)
--
-- All-Wave-80-82 (supply chain + ESG + IP) × jsic_major rollup.
-- Wave 80 supply chain (catalog 282 → 292), Wave 81 ESG (catalog 292
-- → 302), Wave 82 IP (catalog 302 → 312) are all 282 → 312 cohort.
-- This query rolls them up against the canonical jsic_major axis used
-- by wave70/q21 (FY × wave_family × jsic_major). Tables without
-- jsic_major are bucketed to 'UNK' so the per-family row totals stay
-- honest. The 5-bucket Wave 80-82 surface this produces is the
-- procurement + sustainability + IP-advisor cross-section, sliced
-- on industry.
--
-- Pattern: SELECT 1 per row with json_extract_scalar(subject,
-- '$.jsic_major') as the axis. Foundation packet_houjin_360 is added
-- so the baseline jsic_major distribution is observable in the same
-- output. Honors the 50 GB PERF-14 cap.

WITH all_packets AS (
  -- Wave 80 supply chain
  SELECT 'wave80_supply' AS wave_family, 'commodity_price_exposure' AS src,
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK') AS jsic_major
  FROM jpcite_credit_2026_05.packet_commodity_price_exposure_v1

  UNION ALL SELECT 'wave80_supply','secondary_supplier_resilience',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_secondary_supplier_resilience_v1

  UNION ALL SELECT 'wave80_supply','supplier_credit_rating_match',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_supplier_credit_rating_match_v1

  -- Wave 81 ESG materiality
  UNION ALL SELECT 'wave81_esg','carbon_credit_inventory',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_carbon_credit_inventory_v1

  UNION ALL SELECT 'wave81_esg','carbon_reporting_compliance',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_carbon_reporting_compliance_v1

  UNION ALL SELECT 'wave81_esg','climate_alignment_target',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_climate_alignment_target_v1

  UNION ALL SELECT 'wave81_esg','climate_transition_plan',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_climate_transition_plan_v1

  UNION ALL SELECT 'wave81_esg','physical_climate_risk_geo',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_physical_climate_risk_geo_v1

  -- Wave 82 IP / innovation
  UNION ALL SELECT 'wave82_ip','patent_corp_360',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_patent_corp_360_v1

  UNION ALL SELECT 'wave82_ip','patent_environmental_link',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1

  UNION ALL SELECT 'wave82_ip','patent_subsidy_intersection',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_patent_subsidy_intersection_v1

  UNION ALL SELECT 'wave82_ip','trademark_brand_protection',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1

  UNION ALL SELECT 'wave82_ip','trademark_industry_density',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1

  -- Foundation anchor (houjin_360) so the JSIC distribution baseline
  -- is observable in the same output
  UNION ALL SELECT 'foundation','houjin_360',
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
