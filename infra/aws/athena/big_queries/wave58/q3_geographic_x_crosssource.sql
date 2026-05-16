-- q3_geographic_x_crosssource.sql (Wave 58)
--
-- Cross-join Wave 57 (geographic) × Wave 55 cross-source cohort.
-- Wave 55 cross-source = Wave 53 + 53.3 + 54 packet families that link
-- houjin/program to multiple source families (EDINET / 特許 / 国税 /
-- 公益法人 / 行政処分 / 入札). The join surface: city/prefecture/region
-- dimension × multi-source entity activity.
--
-- Join key normalization:
--   * cohort_definition.prefecture (Wave 57 primary)
--   * cohort_definition.cohort_id
--   * subject.id

WITH wave57_geo AS (
  SELECT
    COALESCE(
      json_extract_scalar(subject, '$.id'),
      json_extract_scalar(cohort_definition, '$.prefecture'),
      json_extract_scalar(cohort_definition, '$.cohort_id'),
      'UNKNOWN'
    ) AS join_key,
    'packet_city_jct_density_v1' AS geo_source,
    generated_at AS geo_generated_at,
    CAST(json_extract_scalar(metrics, '$.total_municipalities') AS DOUBLE) AS geo_metric
  FROM jpcite_credit_2026_05.packet_city_jct_density_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_city_size_subsidy_propensity_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_municipalities') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_city_size_subsidy_propensity_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_cross_prefecture_arbitrage_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.top_adoptions') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_cross_prefecture_arbitrage_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_municipality_subsidy_inventory_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_programs') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_municipality_subsidy_inventory_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_prefecture_court_decision_focus_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_decisions') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_prefecture_court_decision_focus_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_prefecture_environmental_compliance_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.compliance_score') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_prefecture_environmental_compliance_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_prefecture_program_heatmap_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_programs') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_prefecture_program_heatmap_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_region_industry_match_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_programs') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_region_industry_match_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_regional_enforcement_density_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_cases') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_regional_enforcement_density_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.prefecture'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_rural_subsidy_coverage_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.rural_municipality_total') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_rural_subsidy_coverage_v1
),
wave55_cross AS (
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN') AS join_key,
    'packet_patent_corp_360_v1' AS cs_source,
    generated_at AS cs_generated_at,
    CAST(json_extract_scalar(metrics, '$.patent_signal_count') AS DOUBLE) AS cs_metric
  FROM jpcite_credit_2026_05.packet_patent_corp_360_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_environmental_compliance_radar_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.env_enforcement_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_environmental_compliance_radar_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_statistical_cohort_proxy_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.cohort_houjin_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_statistical_cohort_proxy_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_edinet_finance_program_match_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.adoption_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_edinet_finance_program_match_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_cross_administrative_timeline_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.event_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_cross_administrative_timeline_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_gbiz_invoice_dispatch_match_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.match_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_gbiz_invoice_dispatch_match_v1
)
SELECT
  geo.join_key,
  geo.geo_source,
  cs.cs_source,
  COUNT(*) AS triple_count,
  AVG(geo.geo_metric) AS avg_geo_metric,
  AVG(cs.cs_metric) AS avg_cs_metric,
  MAX(geo.geo_generated_at) AS latest_geo,
  MAX(cs.cs_generated_at) AS latest_cs
FROM wave57_geo geo
LEFT JOIN wave55_cross cs ON geo.join_key = cs.join_key
WHERE geo.join_key != 'UNKNOWN'
GROUP BY geo.join_key, geo.geo_source, cs.cs_source
ORDER BY triple_count DESC
LIMIT 5000
