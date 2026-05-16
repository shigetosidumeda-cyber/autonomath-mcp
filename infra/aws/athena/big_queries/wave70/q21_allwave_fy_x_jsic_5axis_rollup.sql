-- q21_allwave_fy_x_jsic_5axis_rollup.sql (Wave 70-more)
--
-- All-Wave fiscal-year × jsic 5-axis roll-up across Wave 53 → 76 packets.
-- Extends wave67/q15 (fy × wave_family with Poisson 95% CI) by:
--   * adding a jsic_major axis (the 21-category JSIC major code; we extract
--     it from the subject.jsic_major / cohort_definition.jsic_major path
--     when present, otherwise bucket it to 'UNK' so the row count stays
--     honest)
--   * spanning Wave 53 → 76 instead of Wave 53 → 60
--   * 5 axes: fiscal_year_jp, wave_family, jsic_major, approx_distinct_keys,
--             95% CI lo / hi on row_count
--
-- FY definition unchanged:
--   FY(t) = year(t) if month(t) >= 4 else year(t) - 1
--   2026-04-01..2027-03-31 = FY 2026.
--
-- Honors the 100 GB workgroup cap. Despite the breadth of tables, scan
-- footprint stays in the low-GB range because the SELECT list only
-- references json-extract scalars on already-projected columns, which
-- Athena column-prunes aggressively on parquet. Tables that do not carry
-- jsic_major are intentionally kept as 'UNK' to avoid silently dropping
-- their rows from the totals.

WITH dated AS (
  -- Wave 53 finance / governance baseline
  SELECT 'wave53' AS wave_family, 'application_strategy' AS src,
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK') AS jsic_major,
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK') AS jk,
         CAST(from_iso8601_timestamp(created_at) AS timestamp) AS gen_ts
  FROM jpcite_credit_2026_05.packet_application_strategy_v1
  WHERE created_at IS NOT NULL

  -- Wave 53.3 cross-source deep
  UNION ALL SELECT 'wave53_3','patent_corp_360',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'),
                  json_extract_scalar(cohort_definition, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_patent_corp_360_v1
  WHERE generated_at IS NOT NULL

  -- Wave 55 mixed
  UNION ALL SELECT 'wave55','kfs_saiketsu_industry_radar',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'),
                  json_extract_scalar(cohort_definition, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_kfs_saiketsu_industry_radar_v1
  WHERE generated_at IS NOT NULL

  -- Wave 60 cross-industry macro
  UNION ALL SELECT 'wave60','trademark_industry_density',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'),
                  json_extract_scalar(cohort_definition, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'),
                  json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
  WHERE generated_at IS NOT NULL

  -- Wave 65 financial markets
  UNION ALL SELECT 'wave65','m_a_event_signals',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_m_a_event_signals_v1
  WHERE generated_at IS NOT NULL

  -- Wave 66 PII compliance
  UNION ALL SELECT 'wave66','eu_gdpr_overlap',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_eu_gdpr_overlap_v1
  WHERE generated_at IS NOT NULL

  -- Wave 67 tech infrastructure
  UNION ALL SELECT 'wave67','iso_certification_overlap',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_iso_certification_overlap_v1
  WHERE generated_at IS NOT NULL

  -- Wave 68 supply chain (vendor_due_diligence schema has only created_at)
  UNION ALL SELECT 'wave68','vendor_due_diligence',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(created_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1
  WHERE created_at IS NOT NULL

  -- Wave 69 entity_360
  UNION ALL SELECT 'wave69','entity_360_summary',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_entity_360_summary_v1
  WHERE generated_at IS NOT NULL

  -- Wave 72 AI/ML
  UNION ALL SELECT 'wave72','ai_governance_disclosure',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_ai_governance_disclosure_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave72','ai_model_lineage',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_ai_model_lineage_v1
  WHERE generated_at IS NOT NULL

  -- Wave 73 climate
  UNION ALL SELECT 'wave73','tcfd_disclosure_completeness',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_tcfd_disclosure_completeness_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave73','climate_transition_plan',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_climate_transition_plan_v1
  WHERE generated_at IS NOT NULL

  -- Wave 74 fintech
  UNION ALL SELECT 'wave74','bond_issuance_pattern',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_bond_issuance_pattern_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave74','transition_finance_eligibility',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_transition_finance_eligibility_v1
  WHERE generated_at IS NOT NULL

  -- Wave 75 labor
  UNION ALL SELECT 'wave75','employment_program_eligibility',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_employment_program_eligibility_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave75','labor_dispute_event_rate',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_labor_dispute_event_rate_v1
  WHERE generated_at IS NOT NULL

  -- Wave 76 startup
  UNION ALL SELECT 'wave76','capital_raising_history',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_capital_raising_history_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave76','ipo_pipeline_signal',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_ipo_pipeline_signal_v1
  WHERE generated_at IS NOT NULL
  UNION ALL SELECT 'wave76','founding_succession_chain',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK'),
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNK'),
         CAST(from_iso8601_timestamp(generated_at) AS timestamp)
  FROM jpcite_credit_2026_05.packet_founding_succession_chain_v1
  WHERE generated_at IS NOT NULL
),
rolled AS (
  SELECT
    CASE WHEN month(gen_ts) >= 4 THEN year(gen_ts) ELSE year(gen_ts) - 1 END AS fiscal_year_jp,
    wave_family,
    jsic_major,
    COUNT(*) AS row_count,
    approx_distinct(jk) AS approx_distinct_keys
  FROM dated
  GROUP BY
    CASE WHEN month(gen_ts) >= 4 THEN year(gen_ts) ELSE year(gen_ts) - 1 END,
    wave_family,
    jsic_major
)
SELECT
  fiscal_year_jp,
  wave_family,
  jsic_major,
  row_count,
  approx_distinct_keys,
  GREATEST(0, CAST(row_count - 1.96 * sqrt(row_count) AS BIGINT)) AS ci_lo_95,
  CAST(row_count + 1.96 * sqrt(row_count) AS BIGINT) AS ci_hi_95
FROM rolled
ORDER BY fiscal_year_jp DESC, wave_family, row_count DESC
LIMIT 1000
