-- time_series_burn_pattern.sql
--
-- Purpose:  Track ETL progress over time across every populated packet
--           table by row count per (date, package_kind). This is a
--           "burn pattern" check: how quickly each outcome family
--           grew during the 2026-05 credit run.
--
-- Output:   one row per (run_date, package_kind) tuple with:
--             - run_date         derived from created_at (YYYY-MM-DD)
--             - package_kind     stable packet family identifier
--             - row_count        count of docs produced that day
--             - distinct_subjects count of distinct object_id (proxy for unique entities)
--             - earliest_ts      MIN(created_at) within the day
--             - latest_ts        MAX(created_at) within the day
--
-- Budget:   ~500-800 MB scan across all 19 packet tables (real population).
-- Notes:    UNION ALL across 19 tables so a single execution touches
--           every packet prefix in the bucket. ``created_at`` is
--           expected to be ISO-8601; ``SUBSTR(created_at, 1, 10)``
--           extracts the YYYY-MM-DD prefix.

WITH all_packets AS (
  SELECT 'houjin_360' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_houjin_360
  UNION ALL
  SELECT 'acceptance_probability' AS package_kind,
         json_extract_scalar(header, '$.created_at') AS created_at,
         json_extract_scalar(header, '$.object_id') AS object_id
    FROM jpcite_credit_2026_05.packet_acceptance_probability
  UNION ALL
  SELECT 'program_lineage' AS package_kind,
         json_extract_scalar(header, '$.created_at') AS created_at,
         json_extract_scalar(header, '$.object_id') AS object_id
    FROM jpcite_credit_2026_05.packet_program_lineage
  UNION ALL
  SELECT 'application_strategy_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_application_strategy_v1
  UNION ALL
  SELECT 'bid_opportunity_matching_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_bid_opportunity_matching_v1
  UNION ALL
  SELECT 'cohort_program_recommendation_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_cohort_program_recommendation_v1
  UNION ALL
  SELECT 'company_public_baseline_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_company_public_baseline_v1
  UNION ALL
  SELECT 'enforcement_industry_heatmap_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_enforcement_industry_heatmap_v1
  UNION ALL
  SELECT 'invoice_houjin_cross_check_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_invoice_houjin_cross_check_v1
  UNION ALL
  SELECT 'invoice_registrant_public_check_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_invoice_registrant_public_check_v1
  UNION ALL
  SELECT 'kanpou_gazette_watch_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_kanpou_gazette_watch_v1
  UNION ALL
  SELECT 'local_government_subsidy_aggregator_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_local_government_subsidy_aggregator_v1
  UNION ALL
  SELECT 'permit_renewal_calendar_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_permit_renewal_calendar_v1
  UNION ALL
  SELECT 'program_law_amendment_impact_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_program_law_amendment_impact_v1
  UNION ALL
  SELECT 'regulatory_change_radar_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_regulatory_change_radar_v1
  UNION ALL
  SELECT 'subsidy_application_timeline_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_subsidy_application_timeline_v1
  UNION ALL
  SELECT 'succession_program_matching_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_succession_program_matching_v1
  UNION ALL
  SELECT 'tax_treaty_japan_inbound_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_tax_treaty_japan_inbound_v1
  UNION ALL
  SELECT 'vendor_due_diligence_v1' AS package_kind, created_at, object_id FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1
)
SELECT
  SUBSTR(created_at, 1, 10)           AS run_date,
  package_kind,
  COUNT(*)                            AS row_count,
  COUNT(DISTINCT object_id)           AS distinct_subjects,
  MIN(created_at)                     AS earliest_ts,
  MAX(created_at)                     AS latest_ts
FROM all_packets
WHERE created_at IS NOT NULL
GROUP BY SUBSTR(created_at, 1, 10), package_kind
ORDER BY run_date DESC, row_count DESC
LIMIT 2000;
