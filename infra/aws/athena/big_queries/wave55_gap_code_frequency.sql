-- wave55_gap_code_frequency.sql
--
-- 7-enum gap code frequency per outcome (data quality audit).
-- `known_gaps` is JSON array of {code, description}; we UNNEST it to
-- count gap codes per source_table. The 7 canonical codes observed:
--   professional_review_required
--   no_hit_not_absence
--   thin_corpus
--   alias_mismatch_possible
--   transient_data_quality_issue
--   public_review_period_only
--   normalization_pending

WITH packet_gaps AS (
  -- packet_houjin_360 stores gaps inside `coverage.known_gaps` (struct field, also string-JSON).
  SELECT 'packet_houjin_360' AS source_table,
         json_extract(json_parse(coverage), '$.known_gaps') AS gaps_json
    FROM jpcite_credit_2026_05.packet_houjin_360
  UNION ALL SELECT 'packet_acceptance_probability', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_acceptance_probability
  -- packet_program_lineage has no known_gaps field; emit an empty JSON array so the UNNEST is harmless.
  UNION ALL SELECT 'packet_program_lineage', json_parse('[]') FROM jpcite_credit_2026_05.packet_program_lineage
  UNION ALL SELECT 'packet_patent_corp_360_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_patent_corp_360_v1
  UNION ALL SELECT 'packet_environmental_compliance_radar_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_environmental_compliance_radar_v1
  UNION ALL SELECT 'packet_statistical_cohort_proxy_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_statistical_cohort_proxy_v1
  UNION ALL SELECT 'packet_diet_question_program_link_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_diet_question_program_link_v1
  UNION ALL SELECT 'packet_edinet_finance_program_match_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_edinet_finance_program_match_v1
  UNION ALL SELECT 'packet_trademark_brand_protection_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1
  UNION ALL SELECT 'packet_statistics_market_size_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_statistics_market_size_v1
  UNION ALL SELECT 'packet_cross_administrative_timeline_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_cross_administrative_timeline_v1
  UNION ALL SELECT 'packet_public_procurement_trend_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_public_procurement_trend_v1
  UNION ALL SELECT 'packet_regulation_impact_simulator_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_regulation_impact_simulator_v1
  UNION ALL SELECT 'packet_patent_environmental_link_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1
  UNION ALL SELECT 'packet_diet_question_amendment_correlate_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_diet_question_amendment_correlate_v1
  UNION ALL SELECT 'packet_edinet_program_subsidy_compounding_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_edinet_program_subsidy_compounding_v1
  UNION ALL SELECT 'packet_kanpou_program_event_link_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_kanpou_program_event_link_v1
  UNION ALL SELECT 'packet_kfs_saiketsu_industry_radar_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_kfs_saiketsu_industry_radar_v1
  UNION ALL SELECT 'packet_municipal_budget_match_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_municipal_budget_match_v1
  UNION ALL SELECT 'packet_trademark_industry_density_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
  UNION ALL SELECT 'packet_environmental_disposal_radar_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_environmental_disposal_radar_v1
  UNION ALL SELECT 'packet_regulatory_change_industry_impact_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_regulatory_change_industry_impact_v1
  UNION ALL SELECT 'packet_gbiz_invoice_dispatch_match_v1', json_parse(known_gaps) FROM jpcite_credit_2026_05.packet_gbiz_invoice_dispatch_match_v1
),
unnested AS (
  SELECT
    pg.source_table,
    json_extract_scalar(g, '$.code') AS gap_code
  FROM packet_gaps pg
  CROSS JOIN UNNEST(CAST(pg.gaps_json AS array(json))) AS t(g)
  WHERE pg.gaps_json IS NOT NULL
    AND json_array_length(pg.gaps_json) > 0
)
SELECT
  source_table,
  gap_code,
  COUNT(*) AS gap_count
FROM unnested
WHERE gap_code IS NOT NULL
GROUP BY source_table, gap_code
ORDER BY source_table, gap_count DESC
LIMIT 500;
