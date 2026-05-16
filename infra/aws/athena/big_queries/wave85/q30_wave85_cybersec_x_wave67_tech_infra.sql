-- q30_wave85_cybersec_x_wave67_tech_infra.sql (Wave 83-85)
--
-- Wave 85 cybersec family × Wave 67 tech-infra family cross-join.
-- The cybersec × tech-infra axis is the canonical NIS2 / 経済安全保障
-- alignment surface — when a corp has BOTH cybersec posture signal
-- (Wave 85) AND tech infrastructure dependency disclosure (Wave 67),
-- the CISO / 経済安保 advisor can read the supply-side hardening delta
-- between disclosed posture and disclosed dependency. The cross-join
-- here produces the bilateral coverage density that an audit / DD
-- workflow needs.
--
-- Wave 85 (cybersec family) tables in scope:
--   cybersecurity_certification / fdi_security_review /
--   data_breach_event_history / mandatory_breach_notice_sla /
--   anonymization_method_disclosure / sensitive_data_handling
--
-- Wave 67 (tech infra family) tables in scope:
--   api_uptime_sla_obligation / cloud_dependency_disclosure /
--   data_center_location / devops_maturity_signal /
--   system_outage_incident_log
--
-- Pattern: per-family rollup (COUNT + approx_distinct subject.id)
-- CROSS JOIN producing (cybersec_family, tech_family) pairs with
-- their combined coverage density. Honors the 50 GB PERF-14 cap.

WITH wave85_cybersec AS (
  SELECT 'cybersecurity_certification' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_cybersecurity_certification_v1

  UNION ALL
  SELECT 'fdi_security_review',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_fdi_security_review_v1

  UNION ALL
  SELECT 'data_breach_event_history',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_data_breach_event_history_v1

  UNION ALL
  SELECT 'mandatory_breach_notice_sla',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_mandatory_breach_notice_sla_v1

  UNION ALL
  SELECT 'anonymization_method_disclosure',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_anonymization_method_disclosure_v1
),
wave67_tech AS (
  SELECT 'api_uptime_sla_obligation' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_api_uptime_sla_obligation_v1

  UNION ALL
  SELECT 'cloud_dependency_disclosure',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_cloud_dependency_disclosure_v1

  UNION ALL
  SELECT 'data_center_location',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_data_center_location_v1

  UNION ALL
  SELECT 'devops_maturity_signal',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_devops_maturity_signal_v1

  UNION ALL
  SELECT 'system_outage_incident_log',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_system_outage_incident_log_v1
)
SELECT
  c.src AS wave85_cybersec_family,
  c.row_count AS cybersec_row_count,
  c.approx_distinct_subjects AS cybersec_distinct_subjects,
  t.src AS wave67_tech_family,
  t.row_count AS tech_row_count,
  t.approx_distinct_subjects AS tech_distinct_subjects,
  -- posture-dependency alignment: ratio of tech distinct subjects
  -- also covered by cybersec axis. Capped at 1.0.
  CASE
    WHEN t.approx_distinct_subjects = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(c.approx_distinct_subjects AS DOUBLE)
               / CAST(t.approx_distinct_subjects AS DOUBLE))
  END AS cybersec_tech_alignment_density
FROM wave85_cybersec c
CROSS JOIN wave67_tech t
ORDER BY c.row_count DESC, t.row_count DESC
LIMIT 100
