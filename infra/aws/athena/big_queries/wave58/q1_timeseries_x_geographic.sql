-- q1_timeseries_x_geographic.sql (Wave 58)
--
-- Cross-join Wave 56 (time-series) × Wave 57 (geographic) on subject_id /
-- cohort_definition. The Wave 56 tables capture temporal cadence of
-- amendments / enforcement / adoption / invoice registration / regulatory
-- diff. The Wave 57 tables capture spatial distribution (city / prefecture
-- / rural / region × industry). Join surface = COALESCE of
--   * subject.id (houjin_bangou)
--   * cohort_definition.cohort_id
--   * cohort_definition.prefecture
-- as a normalized join key, so the cell row count is the number of
-- (subject_id, time-series source, geographic source) triples populated
-- in S3.
--
-- All packet tables store the body as JSON STRING for schema-drift
-- resistance; extract with json_extract_scalar.

WITH wave56_ts AS (
  SELECT
    COALESCE(
      json_extract_scalar(subject, '$.id'),
      json_extract_scalar(cohort_definition, '$.cohort_id'),
      json_extract_scalar(cohort_definition, '$.prefecture'),
      'UNKNOWN'
    ) AS join_key,
    'packet_program_amendment_timeline_v2' AS ts_source,
    generated_at AS ts_generated_at,
    CAST(json_extract_scalar(metrics, '$.total_diffs') AS DOUBLE) AS ts_metric
  FROM jpcite_credit_2026_05.packet_program_amendment_timeline_v2
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_enforcement_seasonal_trend_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_cases') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_enforcement_seasonal_trend_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_adoption_fiscal_cycle_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_adoption_fiscal_cycle_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_tax_ruleset_phase_change_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_phase_changes') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_tax_ruleset_phase_change_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_invoice_registration_velocity_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.active_total') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_invoice_registration_velocity_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_regulatory_q_over_q_diff_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_diffs') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_regulatory_q_over_q_diff_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_subsidy_application_window_predict_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.recent_rounds_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_subsidy_application_window_predict_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_bid_announcement_seasonality_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_bids') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_bid_announcement_seasonality_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_succession_event_pulse_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.adoption_total') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_succession_event_pulse_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_kanpou_event_burst_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.monthly_mean') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_kanpou_event_burst_v1
),
wave57_geo AS (
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN') AS join_key,
    'packet_city_jct_density_v1' AS geo_source,
    generated_at AS geo_generated_at,
    CAST(json_extract_scalar(metrics, '$.total_municipalities') AS DOUBLE) AS geo_metric
  FROM jpcite_credit_2026_05.packet_city_jct_density_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_city_size_subsidy_propensity_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_municipalities') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_city_size_subsidy_propensity_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_cross_prefecture_arbitrage_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.top_adoptions') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_cross_prefecture_arbitrage_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_municipality_subsidy_inventory_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_programs') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_municipality_subsidy_inventory_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_prefecture_court_decision_focus_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_decisions') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_prefecture_court_decision_focus_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_prefecture_environmental_compliance_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.compliance_score') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_prefecture_environmental_compliance_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_prefecture_program_heatmap_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_programs') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_prefecture_program_heatmap_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_region_industry_match_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_programs') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_region_industry_match_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_regional_enforcement_density_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_cases') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_regional_enforcement_density_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'),
             json_extract_scalar(cohort_definition, '$.prefecture'), 'UNKNOWN'),
    'packet_rural_subsidy_coverage_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.rural_municipality_total') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_rural_subsidy_coverage_v1
)
SELECT
  ts.join_key,
  ts.ts_source,
  geo.geo_source,
  COUNT(*) AS triple_count,
  AVG(ts.ts_metric) AS avg_ts_metric,
  AVG(geo.geo_metric) AS avg_geo_metric,
  MAX(ts.ts_generated_at) AS latest_ts,
  MAX(geo.geo_generated_at) AS latest_geo
FROM wave56_ts ts
LEFT JOIN wave57_geo geo ON ts.join_key = geo.join_key
WHERE ts.join_key != 'UNKNOWN'
GROUP BY ts.join_key, ts.ts_source, geo.geo_source
ORDER BY triple_count DESC
LIMIT 5000
