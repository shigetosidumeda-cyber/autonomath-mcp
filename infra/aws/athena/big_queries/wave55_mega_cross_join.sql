-- wave55_mega_cross_join.sql
--
-- "Mother of all cross-joins". LEFT JOINs across 39 packet Glue tables
-- (3 foundation + 16 Wave 53 + 10 Wave 53.3 + 10 Wave 54) on a common
-- dimension. The common dimension is normalized as follows:
--
--   houjin_bangou (13-digit corp number)
--     when present in cohort_definition.houjin_bangou
--     or json_extract_scalar(subject, '$.id') of kind 'houjin'
--   cohort_id (fallback)
--     anything else (program / prefecture / jsic_major / cohort)
--
-- Result is a 法人 360 mega-view that aggregates packet-presence-bit +
-- key metric per common dimension. Caller can `subject_id IS NOT NULL`
-- to filter only the populated rows.
--
-- Budget: 1+ GB scan across 39 packet tables (real data).
--
-- All packet tables store nested arrays as JSON STRING for schema-drift
-- resistance; we extract via json_extract_scalar(...).
--
-- NOTE: Wave 53/53.3/54 packet tables use slightly different envelopes.
-- The 3 foundation tables (houjin_360, acceptance_probability,
-- program_lineage) have their own column shape. For the foundation
-- tables we project the closest analogue of cohort_id / subject_id.

WITH foundation_houjin_360 AS (
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN') AS subject_id,
    'houjin' AS subject_kind,
    'packet_houjin_360' AS source_table,
    generated_at,
    CAST(json_extract_scalar(coverage, '$.coverage_score') AS DOUBLE) AS metric_value,
    coverage AS coverage_struct
  FROM jpcite_credit_2026_05.packet_houjin_360
),
foundation_accept AS (
  SELECT
    COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN') AS subject_id,
    'cohort' AS subject_kind,
    'packet_acceptance_probability' AS source_table,
    freshest_announced_at AS generated_at,
    probability_estimate AS metric_value,
    cohort_definition AS coverage_struct
  FROM jpcite_credit_2026_05.packet_acceptance_probability
),
foundation_lineage AS (
  SELECT
    COALESCE(json_extract_scalar(program, '$.entity_id'), 'UNKNOWN') AS subject_id,
    'program' AS subject_kind,
    'packet_program_lineage' AS source_table,
    json_extract_scalar(header, '$.generated_at') AS generated_at,
    CAST(json_extract_scalar(coverage_score, '$.overall_score') AS DOUBLE) AS metric_value,
    coverage_score AS coverage_struct
  FROM jpcite_credit_2026_05.packet_program_lineage
),
-- Wave 53.3 + Wave 54 packets carry both subject.id and cohort_definition.cohort_id.
-- Houjin-flavored: patent_corp_360 / env_compliance / edinet_finance / trademark_brand /
-- cross_administrative / patent_environmental / edinet_compounding / gbiz_invoice
-- Program-flavored: diet_question_program_link / kanpou_program_event /
-- diet_question_amendment / regulation_impact
-- Cohort/Aggregate-flavored: statistical_cohort_proxy / statistics_market_size /
-- public_procurement_trend / regulatory_change_industry_impact / trademark_industry_density /
-- municipal_budget_match / environmental_disposal_radar / kfs_saiketsu_industry_radar
packet_wave53_3_w54 AS (
  SELECT subject_id, subject_kind, source_table, generated_at, metric_value FROM (
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN') AS subject_id,
      COALESCE(json_extract_scalar(subject, '$.kind'), 'houjin') AS subject_kind,
      'packet_patent_corp_360_v1' AS source_table,
      generated_at,
      CAST(json_extract_scalar(metrics, '$.patent_signal_count') AS DOUBLE) AS metric_value
    FROM jpcite_credit_2026_05.packet_patent_corp_360_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'houjin'),
      'packet_environmental_compliance_radar_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.env_enforcement_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_environmental_compliance_radar_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'cohort'),
      'packet_statistical_cohort_proxy_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.cohort_houjin_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_statistical_cohort_proxy_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'program'),
      'packet_diet_question_program_link_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.policy_origin_fact_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_diet_question_program_link_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'houjin'),
      'packet_edinet_finance_program_match_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.adoption_row_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_edinet_finance_program_match_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'houjin'),
      'packet_trademark_brand_protection_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.trademark_adoption_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'cohort'),
      'packet_statistics_market_size_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.total_program_yen') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_statistics_market_size_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'houjin'),
      'packet_cross_administrative_timeline_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.event_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_cross_administrative_timeline_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'cohort'),
      'packet_public_procurement_trend_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.total_awarded_yen') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_public_procurement_trend_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'rule_change'),
      'packet_regulation_impact_simulator_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.impacted_houjin_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_regulation_impact_simulator_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'houjin'),
      'packet_patent_environmental_link_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.patent_adoption_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'program'),
      'packet_diet_question_amendment_correlate_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.amendment_diff_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_diet_question_amendment_correlate_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'houjin'),
      'packet_edinet_program_subsidy_compounding_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.subsidy_adoption_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_edinet_program_subsidy_compounding_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'program'),
      'packet_kanpou_program_event_link_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.kanpou_relevant_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_kanpou_program_event_link_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'tax_type'),
      'packet_kfs_saiketsu_industry_radar_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.industry_bucket_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_kfs_saiketsu_industry_radar_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'prefecture'),
      'packet_municipal_budget_match_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.total_amount_yen') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_municipal_budget_match_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'jsic_major'),
      'packet_trademark_industry_density_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.trademark_adoption_count_total') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'issuing_authority'),
      'packet_environmental_disposal_radar_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.disposal_enforcement_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_environmental_disposal_radar_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'jsic_major'),
      'packet_regulatory_change_industry_impact_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.industry_houjin_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_regulatory_change_industry_impact_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'),
               json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
      COALESCE(json_extract_scalar(subject, '$.kind'), 'invoice_registrant'),
      'packet_gbiz_invoice_dispatch_match_v1',
      generated_at,
      CAST(json_extract_scalar(metrics, '$.adoption_history_count') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_gbiz_invoice_dispatch_match_v1
  )
),
-- 16 Wave 53 outcome tables — these use a slim schema (no cohort_definition.cohort_id field
-- in every variant), so we pull subject.id when it exists.
packet_wave53 AS (
  SELECT subject_id, subject_kind, source_table, generated_at, metric_value FROM (
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'), object_id) AS subject_id,
      'houjin' AS subject_kind,
      'packet_application_strategy_v1' AS source_table,
      created_at AS generated_at,
      CAST(NULL AS DOUBLE) AS metric_value
    FROM jpcite_credit_2026_05.packet_application_strategy_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), object_id),
      'cohort',
      'packet_bid_opportunity_matching_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_bid_opportunity_matching_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), object_id),
      'cohort',
      'packet_cohort_program_recommendation_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_cohort_program_recommendation_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'), object_id),
      'houjin',
      'packet_company_public_baseline_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_company_public_baseline_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), object_id),
      'cohort',
      'packet_enforcement_industry_heatmap_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_enforcement_industry_heatmap_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'), object_id),
      'houjin',
      'packet_invoice_houjin_cross_check_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_invoice_houjin_cross_check_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'), object_id),
      'invoice_registrant',
      'packet_invoice_registrant_public_check_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_invoice_registrant_public_check_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'), object_id),
      'houjin',
      'packet_kanpou_gazette_watch_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_kanpou_gazette_watch_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), object_id),
      'cohort',
      'packet_local_government_subsidy_aggregator_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_local_government_subsidy_aggregator_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'), object_id),
      'houjin',
      'packet_permit_renewal_calendar_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_permit_renewal_calendar_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'), object_id),
      'program',
      'packet_program_law_amendment_impact_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_program_law_amendment_impact_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), object_id),
      'cohort',
      'packet_regulatory_change_radar_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_regulatory_change_radar_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(cohort_definition, '$.cohort_id'), object_id),
      'cohort',
      'packet_subsidy_application_timeline_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_subsidy_application_timeline_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'), object_id),
      'houjin',
      'packet_succession_program_matching_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_succession_program_matching_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'), object_id),
      'houjin',
      'packet_tax_treaty_japan_inbound_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_tax_treaty_japan_inbound_v1
    UNION ALL
    SELECT
      COALESCE(json_extract_scalar(subject, '$.id'), object_id),
      'houjin',
      'packet_vendor_due_diligence_v1',
      created_at,
      CAST(NULL AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1
  )
),
all_rows AS (
  SELECT subject_id, subject_kind, source_table, generated_at, metric_value FROM foundation_houjin_360
  UNION ALL
  SELECT subject_id, subject_kind, source_table, generated_at, metric_value FROM foundation_accept
  UNION ALL
  SELECT subject_id, subject_kind, source_table, generated_at, metric_value FROM foundation_lineage
  UNION ALL
  SELECT subject_id, subject_kind, source_table, generated_at, metric_value FROM packet_wave53_3_w54
  UNION ALL
  SELECT subject_id, subject_kind, source_table, generated_at, metric_value FROM packet_wave53
),
mega_view AS (
  SELECT
    subject_id,
    subject_kind,
    COUNT(DISTINCT source_table)  AS source_table_presence,
    COUNT(*)                      AS total_packet_count,
    AVG(metric_value)             AS avg_metric_value,
    MAX(metric_value)             AS max_metric_value,
    SUM(CASE WHEN source_table = 'packet_houjin_360'              THEN 1 ELSE 0 END) AS n_houjin_360,
    SUM(CASE WHEN source_table = 'packet_acceptance_probability'  THEN 1 ELSE 0 END) AS n_acceptance,
    SUM(CASE WHEN source_table = 'packet_program_lineage'         THEN 1 ELSE 0 END) AS n_lineage,
    SUM(CASE WHEN source_table = 'packet_patent_corp_360_v1'      THEN 1 ELSE 0 END) AS n_patent_360,
    SUM(CASE WHEN source_table = 'packet_gbiz_invoice_dispatch_match_v1' THEN 1 ELSE 0 END) AS n_gbiz_invoice,
    MIN(generated_at)             AS earliest_generated_at,
    MAX(generated_at)             AS latest_generated_at
  FROM all_rows
  WHERE subject_id IS NOT NULL AND subject_id <> 'UNKNOWN'
  GROUP BY subject_id, subject_kind
)
SELECT
  subject_id,
  subject_kind,
  source_table_presence,
  total_packet_count,
  avg_metric_value,
  max_metric_value,
  n_houjin_360,
  n_acceptance,
  n_lineage,
  n_patent_360,
  n_gbiz_invoice,
  earliest_generated_at,
  latest_generated_at
FROM mega_view
ORDER BY source_table_presence DESC, total_packet_count DESC
LIMIT 5000;
