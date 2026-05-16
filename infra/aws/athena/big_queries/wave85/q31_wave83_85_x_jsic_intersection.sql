-- q31_wave83_85_x_jsic_intersection.sql (Wave 83-85)
--
-- Wave 83 (climate physical) + Wave 84 (demographics) + Wave 85
-- (cybersec) × jsic_major intersection. Three new wave families rolled
-- up against the canonical JSIC industry axis used by wave70/q21 and
-- wave82/q26. Tables without jsic_major are bucketed to 'UNK' so the
-- per-family row totals stay honest.
--
-- The 3-bucket Wave 83-85 surface this produces is the sustainability
-- + regional-policy + security advisor cross-section, sliced on
-- industry — the canonical "which JSIC sector carries the most
-- physical-climate + demographic + cybersec signal density" view.
--
-- Pattern: SELECT 1 per row with json_extract_scalar(subject,
-- '$.jsic_major') as the axis. Foundation packet_houjin_360 is added
-- so the baseline JSIC distribution is observable in the same output.
-- Honors the 50 GB PERF-14 cap.

WITH all_packets AS (
  -- Wave 83 climate physical
  SELECT 'wave83_climate' AS wave_family, 'physical_climate_risk_geo' AS src,
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK') AS jsic_major
  FROM jpcite_credit_2026_05.packet_physical_climate_risk_geo_v1

  UNION ALL SELECT 'wave83_climate', 'carbon_credit_inventory',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_carbon_credit_inventory_v1

  UNION ALL SELECT 'wave83_climate', 'carbon_reporting_compliance',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_carbon_reporting_compliance_v1

  UNION ALL SELECT 'wave83_climate', 'climate_alignment_target',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_climate_alignment_target_v1

  UNION ALL SELECT 'wave83_climate', 'climate_transition_plan',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_climate_transition_plan_v1

  -- Wave 84 demographics / population proxies (full set pending —
  -- task #230 Wave 84 FULL-SCALE 30 generators)
  UNION ALL SELECT 'wave84_demographic', 'city_industry_diversification',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_city_industry_diversification_v1

  UNION ALL SELECT 'wave84_demographic', 'prefecture_industry_inbound',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_prefecture_industry_inbound_v1

  UNION ALL SELECT 'wave84_demographic', 'city_size_subsidy_propensity',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_city_size_subsidy_propensity_v1

  UNION ALL SELECT 'wave84_demographic', 'rural_subsidy_coverage',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_rural_subsidy_coverage_v1

  -- Wave 85 cybersec
  UNION ALL SELECT 'wave85_cybersec', 'cybersecurity_certification',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_cybersecurity_certification_v1

  UNION ALL SELECT 'wave85_cybersec', 'fdi_security_review',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_fdi_security_review_v1

  UNION ALL SELECT 'wave85_cybersec', 'data_breach_event_history',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_data_breach_event_history_v1

  UNION ALL SELECT 'wave85_cybersec', 'mandatory_breach_notice_sla',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_mandatory_breach_notice_sla_v1

  UNION ALL SELECT 'wave85_cybersec', 'anonymization_method_disclosure',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_anonymization_method_disclosure_v1

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
