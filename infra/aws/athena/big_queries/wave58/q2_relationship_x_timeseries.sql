-- q2_relationship_x_timeseries.sql (Wave 58)
--
-- Cross-join Wave 58 (relationship) × Wave 56 (time-series) on
-- houjin_bangou / entity_id / subject.id. Wave 58 captures static
-- corporate-relationship graph (board overlap, parent-subsidiary,
-- business-partner-360, certification linkages, vendor payment history).
-- Wave 56 captures the temporal cadence of program / amendment /
-- enforcement / invoice / regulatory diff. The join surfaces
-- "which corporate-network nodes have what time-series activity".
--
-- Join key normalization:
--   * subject.id (houjin_bangou first)
--   * houjin_bangou body field (set explicitly by some Wave 58 packets)
--   * cohort_definition.cohort_id (fallback)
-- All packet bodies are JSON STRING.

WITH wave58_rel AS (
  SELECT
    COALESCE(
      json_extract_scalar(subject, '$.id'),
      json_extract_scalar(cohort_definition, '$.cohort_id'),
      'UNKNOWN'
    ) AS join_key,
    'packet_board_member_overlap_v1' AS rel_source,
    generated_at AS rel_generated_at,
    CAST(json_extract_scalar(metrics, '$.overlap_total') AS DOUBLE) AS rel_metric
  FROM jpcite_credit_2026_05.packet_board_member_overlap_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_business_partner_360_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.bid_history_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_business_partner_360_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_certification_houjin_link_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.linked_houjin_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_certification_houjin_link_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_employment_program_eligibility_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.program_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_employment_program_eligibility_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_founding_succession_chain_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_adoptions') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_founding_succession_chain_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_houjin_parent_subsidiary_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.group_size_total') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_houjin_parent_subsidiary_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_industry_association_link_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.support_org_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_industry_association_link_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_license_houjin_jurisdiction_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.permit_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_license_houjin_jurisdiction_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_public_listed_program_link_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.adoption_link_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_public_listed_program_link_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_vendor_payment_history_match_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.unique_procurer_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_vendor_payment_history_match_v1
),
wave56_ts AS (
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN') AS join_key,
    'packet_program_amendment_timeline_v2' AS ts_source,
    generated_at AS ts_generated_at,
    CAST(json_extract_scalar(metrics, '$.total_diffs') AS DOUBLE) AS ts_metric
  FROM jpcite_credit_2026_05.packet_program_amendment_timeline_v2
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_enforcement_seasonal_trend_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_cases') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_enforcement_seasonal_trend_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_adoption_fiscal_cycle_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_adoption_fiscal_cycle_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_invoice_registration_velocity_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.active_total') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_invoice_registration_velocity_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_regulatory_q_over_q_diff_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_diffs') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_regulatory_q_over_q_diff_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_succession_event_pulse_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.adoption_total') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_succession_event_pulse_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_bid_announcement_seasonality_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_bids') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_bid_announcement_seasonality_v1
)
SELECT
  rel.join_key,
  rel.rel_source,
  ts.ts_source,
  COUNT(*) AS triple_count,
  AVG(rel.rel_metric) AS avg_rel_metric,
  AVG(ts.ts_metric) AS avg_ts_metric,
  MAX(rel.rel_generated_at) AS latest_rel,
  MAX(ts.ts_generated_at) AS latest_ts
FROM wave58_rel rel
LEFT JOIN wave56_ts ts ON rel.join_key = ts.join_key
WHERE rel.join_key != 'UNKNOWN'
GROUP BY rel.join_key, rel.rel_source, ts.ts_source
ORDER BY triple_count DESC
LIMIT 5000
