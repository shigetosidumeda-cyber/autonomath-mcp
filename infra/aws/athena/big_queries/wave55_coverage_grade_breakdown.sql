-- wave55_coverage_grade_breakdown.sql
--
-- Coverage A/B/C/D grade distribution per outcome (quality QA).
-- Wave 53.3/54 packets embed coverage/quality scores inside `metrics`,
-- `coverage`, or a top-level coverage_score struct. We project a
-- normalized 'grade' bucket for each row and roll up per source_table.
--
-- Grade rubric (A/B/C/D as quartiles):
--   A: score >= 0.75 OR n_signal_count >= 5
--   B: 0.50 <= score < 0.75 OR 2 <= n_signal_count < 5
--   C: 0.25 <= score < 0.50 OR 1 == n_signal_count
--   D: score < 0.25 OR n_signal_count == 0

WITH packet_score AS (
  -- packet_houjin_360 — score under coverage.coverage_score (0..1)
  SELECT 'packet_houjin_360' AS source_table,
         CAST(json_extract_scalar(coverage, '$.coverage_score') AS DOUBLE) AS score
    FROM jpcite_credit_2026_05.packet_houjin_360
  UNION ALL
  SELECT 'packet_acceptance_probability', probability_estimate
    FROM jpcite_credit_2026_05.packet_acceptance_probability
  UNION ALL
  SELECT 'packet_program_lineage',
         CAST(json_extract_scalar(coverage_score, '$.overall_score') AS DOUBLE)
    FROM jpcite_credit_2026_05.packet_program_lineage
  -- Wave 53.3+54 — use a representative metric per packet
  UNION ALL SELECT 'packet_patent_corp_360_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.patent_signal_count') AS DOUBLE) / 10.0)
    FROM jpcite_credit_2026_05.packet_patent_corp_360_v1
  UNION ALL SELECT 'packet_environmental_compliance_radar_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.env_enforcement_count') AS DOUBLE) / 10.0)
    FROM jpcite_credit_2026_05.packet_environmental_compliance_radar_v1
  UNION ALL SELECT 'packet_statistical_cohort_proxy_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.cohort_houjin_count') AS DOUBLE) / 100.0)
    FROM jpcite_credit_2026_05.packet_statistical_cohort_proxy_v1
  UNION ALL SELECT 'packet_diet_question_program_link_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.policy_origin_fact_count') AS DOUBLE) / 5.0)
    FROM jpcite_credit_2026_05.packet_diet_question_program_link_v1
  UNION ALL SELECT 'packet_edinet_finance_program_match_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.adoption_row_count') AS DOUBLE) / 10.0)
    FROM jpcite_credit_2026_05.packet_edinet_finance_program_match_v1
  UNION ALL SELECT 'packet_trademark_brand_protection_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.trademark_adoption_count') AS DOUBLE) / 5.0)
    FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1
  UNION ALL SELECT 'packet_statistics_market_size_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.houjin_count') AS DOUBLE) / 100.0)
    FROM jpcite_credit_2026_05.packet_statistics_market_size_v1
  UNION ALL SELECT 'packet_cross_administrative_timeline_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.event_count') AS DOUBLE) / 10.0)
    FROM jpcite_credit_2026_05.packet_cross_administrative_timeline_v1
  UNION ALL SELECT 'packet_public_procurement_trend_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.bid_count') AS DOUBLE) / 50.0)
    FROM jpcite_credit_2026_05.packet_public_procurement_trend_v1
  UNION ALL SELECT 'packet_regulation_impact_simulator_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.impacted_houjin_count') AS DOUBLE) / 100.0)
    FROM jpcite_credit_2026_05.packet_regulation_impact_simulator_v1
  UNION ALL SELECT 'packet_patent_environmental_link_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.patent_adoption_count') AS DOUBLE) / 5.0)
    FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1
  UNION ALL SELECT 'packet_diet_question_amendment_correlate_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.amendment_diff_count') AS DOUBLE) / 5.0)
    FROM jpcite_credit_2026_05.packet_diet_question_amendment_correlate_v1
  UNION ALL SELECT 'packet_edinet_program_subsidy_compounding_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.subsidy_adoption_count') AS DOUBLE) / 5.0)
    FROM jpcite_credit_2026_05.packet_edinet_program_subsidy_compounding_v1
  UNION ALL SELECT 'packet_kanpou_program_event_link_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.kanpou_relevant_count') AS DOUBLE) / 5.0)
    FROM jpcite_credit_2026_05.packet_kanpou_program_event_link_v1
  UNION ALL SELECT 'packet_kfs_saiketsu_industry_radar_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.industry_bucket_count') AS DOUBLE) / 5.0)
    FROM jpcite_credit_2026_05.packet_kfs_saiketsu_industry_radar_v1
  UNION ALL SELECT 'packet_municipal_budget_match_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.total_adoptions') AS DOUBLE) / 1000.0)
    FROM jpcite_credit_2026_05.packet_municipal_budget_match_v1
  UNION ALL SELECT 'packet_trademark_industry_density_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.trademark_adoption_count_total') AS DOUBLE) / 10.0)
    FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
  UNION ALL SELECT 'packet_environmental_disposal_radar_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.disposal_enforcement_count') AS DOUBLE) / 5.0)
    FROM jpcite_credit_2026_05.packet_environmental_disposal_radar_v1
  UNION ALL SELECT 'packet_regulatory_change_industry_impact_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.industry_houjin_count') AS DOUBLE) / 100.0)
    FROM jpcite_credit_2026_05.packet_regulatory_change_industry_impact_v1
  UNION ALL SELECT 'packet_gbiz_invoice_dispatch_match_v1',
    LEAST(1.0, CAST(json_extract_scalar(metrics, '$.adoption_history_count') AS DOUBLE) / 5.0)
    FROM jpcite_credit_2026_05.packet_gbiz_invoice_dispatch_match_v1
)
SELECT
  source_table,
  COUNT(*)                                                     AS n_docs,
  SUM(CASE WHEN score >= 0.75 THEN 1 ELSE 0 END)               AS grade_a,
  SUM(CASE WHEN score >= 0.50 AND score < 0.75 THEN 1 ELSE 0 END) AS grade_b,
  SUM(CASE WHEN score >= 0.25 AND score < 0.50 THEN 1 ELSE 0 END) AS grade_c,
  SUM(CASE WHEN score < 0.25 OR score IS NULL THEN 1 ELSE 0 END) AS grade_d,
  AVG(score)                                                   AS avg_score
FROM packet_score
GROUP BY source_table
ORDER BY n_docs DESC
LIMIT 100;
