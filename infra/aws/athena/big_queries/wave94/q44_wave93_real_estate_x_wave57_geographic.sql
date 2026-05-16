-- q44_wave93_real_estate_x_wave57_geographic.sql (Wave 92-94)
--
-- Wave 93 real estate / property family × Wave 57 geographic family
-- cross-join. The real-estate × geographic axis is the canonical
-- physical-asset vs prefecture-density alignment surface: when a corp
-- has BOTH (a) real-estate / property footprint signal (Wave 93 —
-- commercial real estate, headquarters lease, property tax, office
-- relocation, manufacturing facility, warehouse logistics, retail
-- store, real-estate broker / investment) AND (b) prefecture / region
-- geographic signal (Wave 57), the M&A real-asset DD + 拠点強化税制
-- advisor can read the property-footprint-to-prefecture-density
-- alignment ratio.
--
-- Wave 93 (real estate / property) tables in scope (live proxies in
-- Glue; full Wave 93 batch like commercial_real_estate_footprint /
-- headquarters_lease_signal / property_tax_signal /
-- office_relocation_event / manufacturing_facility_inventory /
-- warehouse_logistics_node / retail_store_footprint /
-- real_estate_broker_license / real_estate_investment_signal /
-- lease_obligation_disclosure are smoke-only generators pre-Glue
-- sync — they will fold in once the Glue catalog registration lands):
--   retail_inbound_subsidy (Wave 71 anchor reused as live Wave 93
--   proxy for retail footprint until Wave 93 S3 sync) /
--   landslide_geotechnical_risk (Wave 83 anchor reused as live Wave
--   93 proxy for physical-property risk overlay) /
--   industry_x_prefecture_houjin (Wave 70 anchor reused as live Wave
--   93 proxy for property-by-industry density).
--
-- Wave 57 (geographic) tables in scope (all LIVE):
--   prefecture_program_heatmap / prefecture_x_industry_density /
--   region_industry_match / cross_prefecture_arbitrage /
--   prefecture_procurement_match / prefecture_industry_inbound /
--   prefecture_environmental_compliance.
--
-- Pattern: per-family rollup (COUNT + approx_distinct subject.id)
-- CROSS JOIN producing (real_estate_family, geographic_family) pairs
-- with combined coverage density + property-to-prefecture alignment
-- ratio. Honors the 50 GB PERF-14 cap.

WITH wave93_real_estate AS (
  SELECT 'retail_inbound_subsidy' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_retail_inbound_subsidy_v1

  UNION ALL
  SELECT 'landslide_geotechnical_risk',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_landslide_geotechnical_risk_v1

  UNION ALL
  SELECT 'industry_x_prefecture_houjin',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_industry_x_prefecture_houjin_v1
),
wave57_geographic AS (
  SELECT 'prefecture_program_heatmap' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_prefecture_program_heatmap_v1

  UNION ALL
  SELECT 'prefecture_x_industry_density',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_prefecture_x_industry_density_v1

  UNION ALL
  SELECT 'region_industry_match',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_region_industry_match_v1

  UNION ALL
  SELECT 'cross_prefecture_arbitrage',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_cross_prefecture_arbitrage_v1

  UNION ALL
  SELECT 'prefecture_procurement_match',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_prefecture_procurement_match_v1

  UNION ALL
  SELECT 'prefecture_industry_inbound',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_prefecture_industry_inbound_v1

  UNION ALL
  SELECT 'prefecture_environmental_compliance',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_prefecture_environmental_compliance_v1
)
SELECT
  r.src AS wave93_real_estate_family,
  r.row_count AS real_estate_row_count,
  r.approx_distinct_subjects AS real_estate_distinct_subjects,
  g.src AS wave57_geographic_family,
  g.row_count AS geographic_row_count,
  g.approx_distinct_subjects AS geographic_distinct_subjects,
  -- real-estate to geographic alignment: distinct subjects ratio
  -- capped at 1.0. Reads as "% of prefecture-tracked subjects that
  -- also carry a property / real-estate footprint signal" — proxy
  -- for property-by-prefecture density.
  CASE
    WHEN g.approx_distinct_subjects = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(r.approx_distinct_subjects AS DOUBLE)
               / CAST(g.approx_distinct_subjects AS DOUBLE))
  END AS real_estate_geographic_alignment_density
FROM wave93_real_estate r
CROSS JOIN wave57_geographic g
ORDER BY r.row_count DESC, g.row_count DESC
LIMIT 200
