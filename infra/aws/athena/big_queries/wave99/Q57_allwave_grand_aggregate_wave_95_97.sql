-- Q57_allwave_grand_aggregate_wave_95_97.sql (Wave 99)
--
-- Full grand-aggregate including Wave 95-97 newer-family small-cohort.
-- Successor to wave98/q53 (14 wave families top-level) — this adds the
-- Wave 95-97 data-governance newer-family small-cohort to the lean
-- per-family footprint surface. Reads as the canonical "show me the
-- 17 representative wave families + foundation in one shot" surface —
-- one row per (wave_family, src) with row_count + approx_distinct
-- (subject_id) for cardinality.
--
-- Wave 95-97 newer-family additions (3 representative tables):
--   wave95_governance → packet_data_residency_disclosure_v1
--   wave96_master → packet_master_data_governance_v1
--   wave97_vendor_dd → packet_vendor_due_diligence_v1
--
-- Carried over from wave98/q53 (14 families + foundation = 15
-- representative tables):
--   wave53 baseline → packet_application_strategy_v1
--   wave53_3 acceptance → packet_acceptance_probability
--   wave57 geographic → packet_prefecture_program_heatmap_v1
--   wave60_65 finance → packet_bond_issuance_pattern_v1
--   wave67 tech_infra → packet_api_uptime_sla_obligation_v1
--   wave69 entity_360 → packet_entity_360_summary_v1
--   wave70 industry_x_prefecture → packet_industry_x_prefecture_houjin_v1
--   wave72 aiml → packet_ai_governance_disclosure_v1
--   wave76 startup → packet_business_lifecycle_stage_v1
--   wave80 supply → packet_supplier_lifecycle_risk_v1
--   wave81 esg → packet_tcfd_disclosure_completeness_v1
--   wave82 ip → packet_patent_filing_velocity_v1
--   wave85 cybersec → packet_cybersecurity_certification_v1
--   wave89 ma → packet_m_a_event_signals_v1
--   wave91 brand → packet_trademark_brand_protection_v1
--   wave94 insurance → packet_ai_safety_certification_v1
--   foundation → packet_houjin_360
--
-- 18 wave families × 1 representative table each (all LIVE in Glue):
--   = 15 from wave98/q53 + 3 new Wave 95-97 newer-family
--
-- Scan target: ~400-1100MB (18 UNION ALL on representative tables,
-- COUNT + approx_distinct on subject.id only; Wave 95-97 arms add
-- < 1MB each at this snapshot — FULL-SCALE generators in flight).
-- Expected row count: 18 (1 per representative table) + grand rollup;
-- LIMIT 1000 safety.
-- Time estimate: ≤ 120s on Athena engine v3 (workgroup result reuse
-- ON, 50GB BytesScannedCutoffPerQuery PERF-14 cap honored).
--
-- Output schema (8 cols):
--   wave_family / src / row_count / approx_distinct_subjects /
--   pct_of_grand_total / coverage_rank / approx_houjin_density /
--   wave_generation

WITH grand AS (
  -- Wave 53 baseline
  SELECT 'wave53' AS wave_family, 'application_strategy' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_application_strategy_v1

  -- Wave 53.3 acceptance probability
  UNION ALL
  SELECT 'wave53_3', 'acceptance_probability', COUNT(*),
         approx_distinct(json_extract_scalar(cohort_definition, '$.cohort_id'))
  FROM jpcite_credit_2026_05.packet_acceptance_probability

  -- Wave 57 geographic
  UNION ALL
  SELECT 'wave57_geographic', 'prefecture_program_heatmap', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_prefecture_program_heatmap_v1

  -- Wave 60-65 finance (bond issuance as representative)
  UNION ALL
  SELECT 'wave60_65_finance', 'bond_issuance_pattern', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_bond_issuance_pattern_v1

  -- Wave 67 tech infra (api_uptime as representative)
  UNION ALL
  SELECT 'wave67_tech', 'api_uptime_sla_obligation', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_api_uptime_sla_obligation_v1

  -- Wave 69 entity_360 (summary as representative)
  UNION ALL
  SELECT 'wave69_entity_360', 'entity_360_summary', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_entity_360_summary_v1

  -- Wave 70 industry × prefecture
  UNION ALL
  SELECT 'wave70_industry', 'industry_x_prefecture_houjin', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_industry_x_prefecture_houjin_v1

  -- Wave 72 AI/ML governance
  UNION ALL
  SELECT 'wave72_aiml', 'ai_governance_disclosure', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_ai_governance_disclosure_v1

  -- Wave 76 startup (business lifecycle stage as representative)
  UNION ALL
  SELECT 'wave76_startup', 'business_lifecycle_stage', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_business_lifecycle_stage_v1

  -- Wave 80 supply chain (supplier lifecycle risk as representative)
  UNION ALL
  SELECT 'wave80_supply', 'supplier_lifecycle_risk', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_supplier_lifecycle_risk_v1

  -- Wave 81 ESG (TCFD as representative)
  UNION ALL
  SELECT 'wave81_esg', 'tcfd_disclosure_completeness', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_tcfd_disclosure_completeness_v1

  -- Wave 82 IP (patent filing velocity as representative)
  UNION ALL
  SELECT 'wave82_ip', 'patent_filing_velocity', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_patent_filing_velocity_v1

  -- Wave 85 cybersec
  UNION ALL
  SELECT 'wave85_cybersec', 'cybersecurity_certification', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_cybersecurity_certification_v1

  -- Wave 89 M&A
  UNION ALL
  SELECT 'wave89_ma', 'm_a_event_signals', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_m_a_event_signals_v1

  -- Wave 91 brand
  UNION ALL
  SELECT 'wave91_brand', 'trademark_brand_protection', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1

  -- Wave 94 insurance (AI safety cert as representative)
  UNION ALL
  SELECT 'wave94_insurance', 'ai_safety_certification', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_ai_safety_certification_v1

  -- Wave 95 governance (data residency disclosure as representative — newer family)
  UNION ALL
  SELECT 'wave95_governance', 'data_residency_disclosure', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_data_residency_disclosure_v1

  -- Wave 96 master data (master data governance as representative — newer family)
  UNION ALL
  SELECT 'wave96_master', 'master_data_governance', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_master_data_governance_v1

  -- Wave 97 vendor DD (vendor due diligence as representative — newer family)
  UNION ALL
  SELECT 'wave97_vendor_dd', 'vendor_due_diligence', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1

  -- Foundation (houjin_360 baseline)
  UNION ALL
  SELECT 'foundation', 'houjin_360', COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_houjin_360
),
grand_total AS (
  SELECT SUM(row_count) AS total_rows
  FROM grand
)
SELECT
  g.wave_family,
  g.src,
  g.row_count,
  g.approx_distinct_subjects,
  -- pct_of_grand_total: this row's share of the 18-family +
  -- foundation grand total — reads as "% of the union footprint that
  -- lives in this family/src".
  CASE
    WHEN gt.total_rows = 0 THEN 0.0
    ELSE CAST(g.row_count AS DOUBLE) / CAST(gt.total_rows AS DOUBLE)
  END AS pct_of_grand_total,
  -- coverage_rank: dense row rank by row_count DESC across the 20
  -- representative rows.
  DENSE_RANK() OVER (ORDER BY g.row_count DESC) AS coverage_rank,
  -- approx_houjin_density: distinct_subjects per 1000 rows — proxy
  -- for "how many distinct entities the representative table covers
  -- per 1K rows". Higher = broader entity sweep.
  CASE
    WHEN g.row_count = 0 THEN 0.0
    ELSE CAST(g.approx_distinct_subjects AS DOUBLE)
         / (CAST(g.row_count AS DOUBLE) / 1000.0)
  END AS approx_houjin_density,
  -- wave_generation: ordinal bucket so downstream consumers can group
  -- by 'baseline (53)' / 'mid (60-76)' / 'modern (80-94)' / 'newer
  -- (95-97)' / 'foundation'. Reads as wave-era proxy.
  CASE
    WHEN g.wave_family IN ('wave53', 'wave53_3', 'wave57_geographic') THEN 'baseline'
    WHEN g.wave_family IN ('wave60_65_finance', 'wave67_tech',
                            'wave69_entity_360', 'wave70_industry',
                            'wave72_aiml', 'wave76_startup') THEN 'mid'
    WHEN g.wave_family IN ('wave80_supply', 'wave81_esg', 'wave82_ip',
                            'wave85_cybersec', 'wave89_ma',
                            'wave91_brand', 'wave94_insurance') THEN 'modern'
    WHEN g.wave_family IN ('wave95_governance', 'wave96_master',
                            'wave97_vendor_dd') THEN 'newer'
    WHEN g.wave_family = 'foundation' THEN 'foundation'
    ELSE 'other'
  END AS wave_generation
FROM grand g
CROSS JOIN grand_total gt
ORDER BY g.row_count DESC
LIMIT 1000
