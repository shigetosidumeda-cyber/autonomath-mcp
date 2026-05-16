-- q20_wave72_73_aiml_climate_x_wave60_65_finance.sql (Wave 70-more)
--
-- Wave 72-73 (AI/ML + climate) × Wave 60-65 (cross-industry / finance)
-- intersection. The newest AI governance + climate disclosure cohorts are
-- highly correlated with the wave60-65 listed-company / bond-issuance /
-- ESG-investment surface — both are tied to the 2025 上場会社 開示制度 /
-- 金融商品取引法 改正 timeline. This query quantifies the overlap so the
-- "ESG-disclosure compliance + climate finance" enterprise vertical can be
-- priced and routed.
--
-- Pattern: 3-bucket GROUP BY (ai_ml_compliance / climate_disclosure /
-- wave60_65_finance) with row counts + approx_distinct on the subject id
-- where available. wave72-73 packets are subject-keyed, wave60-65 are
-- mixed cohort + subject so we coerce to a common $.id or fall through.

WITH all_packets AS (
  -- Wave 72: AI/ML governance + compliance
  SELECT 'wave72_ai_ml' AS bucket, 'ai_governance_disclosure' AS src,
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN') AS sid
  FROM jpcite_credit_2026_05.packet_ai_governance_disclosure_v1
  UNION ALL SELECT 'wave72_ai_ml','ai_model_lineage',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_ai_model_lineage_v1
  UNION ALL SELECT 'wave72_ai_ml','ai_regulatory_horizon_scan',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_ai_regulatory_horizon_scan_v1
  UNION ALL SELECT 'wave72_ai_ml','ai_safety_certification',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_ai_safety_certification_v1
  UNION ALL SELECT 'wave72_ai_ml','algorithmic_decision_transparency',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_algorithmic_decision_transparency_v1
  UNION ALL SELECT 'wave72_ai_ml','automated_decision_dispute_rate',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_automated_decision_dispute_rate_v1
  UNION ALL SELECT 'wave72_ai_ml','bias_audit_disclosure',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_bias_audit_disclosure_v1
  UNION ALL SELECT 'wave72_ai_ml','deepfake_disclosure_obligation',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_deepfake_disclosure_obligation_v1
  UNION ALL SELECT 'wave72_ai_ml','explainability_compliance',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_explainability_compliance_v1

  -- Wave 73: climate disclosure + green finance overlap
  UNION ALL SELECT 'wave73_climate','carbon_credit_inventory',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_carbon_credit_inventory_v1
  UNION ALL SELECT 'wave73_climate','carbon_reporting_compliance',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_carbon_reporting_compliance_v1
  UNION ALL SELECT 'wave73_climate','climate_alignment_target',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_climate_alignment_target_v1
  UNION ALL SELECT 'wave73_climate','climate_transition_plan',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_climate_transition_plan_v1
  UNION ALL SELECT 'wave73_climate','just_transition_program',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_just_transition_program_v1
  UNION ALL SELECT 'wave73_climate','physical_climate_risk_geo',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_physical_climate_risk_geo_v1
  UNION ALL SELECT 'wave73_climate','scope3_emissions_disclosure',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_scope3_emissions_disclosure_v1
  UNION ALL SELECT 'wave73_climate','tcfd_disclosure_completeness',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_tcfd_disclosure_completeness_v1

  -- Wave 60-65 finance: bond / dividend / executive / insider / m_a / share
  UNION ALL SELECT 'wave60_65_finance','bond_issuance_pattern',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_bond_issuance_pattern_v1
  UNION ALL SELECT 'wave60_65_finance','dividend_policy_stability',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_dividend_policy_stability_v1
  UNION ALL SELECT 'wave60_65_finance','executive_compensation_disclosure',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_executive_compensation_disclosure_v1
  UNION ALL SELECT 'wave60_65_finance','funding_to_revenue_ratio',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_funding_to_revenue_ratio_v1
  UNION ALL SELECT 'wave60_65_finance','insider_trading_disclosure',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_insider_trading_disclosure_v1
  UNION ALL SELECT 'wave60_65_finance','listed_company_disclosure_pulse',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_listed_company_disclosure_pulse_v1
  UNION ALL SELECT 'wave60_65_finance','m_a_event_signals',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_m_a_event_signals_v1
  UNION ALL SELECT 'wave60_65_finance','revenue_volatility_subsidy_offset',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_revenue_volatility_subsidy_offset_v1
  UNION ALL SELECT 'wave60_65_finance','shareholder_return_intensity',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_shareholder_return_intensity_v1
  UNION ALL SELECT 'wave60_65_finance','subsidy_roi_estimate',
         COALESCE(json_extract_scalar(subject, '$.id'), 'UNKNOWN')
  FROM jpcite_credit_2026_05.packet_subsidy_roi_estimate_v1
)
SELECT
  bucket,
  COUNT(*) AS row_count_total,
  COUNT(DISTINCT src) AS distinct_packet_sources,
  approx_distinct(sid) AS approx_distinct_subject_ids
FROM all_packets
GROUP BY bucket
ORDER BY row_count_total DESC
LIMIT 100
