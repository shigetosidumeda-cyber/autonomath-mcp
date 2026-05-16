-- wave55_packet_size_distribution.sql
--
-- Histogram of packet "size" by outcome_type. We approximate packet
-- byte size as the JSON length of the largest nested array field that
-- each packet kind carries. For uniformity we union the document count
-- and a per-row "approx_bytes" using length of serialized struct cols.

WITH sized AS (
  -- 3 foundation
  SELECT 'packet_houjin_360' AS source_table, length(records) + length(sections) + length(coverage) AS approx_bytes
    FROM jpcite_credit_2026_05.packet_houjin_360
  UNION ALL
  SELECT 'packet_acceptance_probability', length(cohort_definition) + length(confidence_interval)
    FROM jpcite_credit_2026_05.packet_acceptance_probability
  UNION ALL
  SELECT 'packet_program_lineage', length(legal_basis_chain) + length(notice_chain) + length(amendment_timeline)
    FROM jpcite_credit_2026_05.packet_program_lineage
  -- Wave 53.3 + 54 (use metrics + cohort_definition as size proxies; all packets share these)
  UNION ALL SELECT 'packet_patent_corp_360_v1', length(houjin_summary) + length(patent_signals) + length(patent_cap_programs) FROM jpcite_credit_2026_05.packet_patent_corp_360_v1
  UNION ALL SELECT 'packet_environmental_compliance_radar_v1', length(houjin_summary) + length(env_enforcements) + length(gx_program_adoptions) FROM jpcite_credit_2026_05.packet_environmental_compliance_radar_v1
  UNION ALL SELECT 'packet_statistical_cohort_proxy_v1', length(cohort_stats) + length(top_houjin) + length(industry_stat_refs) FROM jpcite_credit_2026_05.packet_statistical_cohort_proxy_v1
  UNION ALL SELECT 'packet_diet_question_program_link_v1', length(policy_origin_facts) + length(amendment_diffs) FROM jpcite_credit_2026_05.packet_diet_question_program_link_v1
  UNION ALL SELECT 'packet_edinet_finance_program_match_v1', length(adoption_rows) + length(tax_rulesets) + length(houjin_summary) FROM jpcite_credit_2026_05.packet_edinet_finance_program_match_v1
  UNION ALL SELECT 'packet_trademark_brand_protection_v1', length(trademark_adoption_rows) + length(trademark_program_caps) FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1
  UNION ALL SELECT 'packet_statistics_market_size_v1', length(industry_stat_refs) + length(market_cell) FROM jpcite_credit_2026_05.packet_statistics_market_size_v1
  UNION ALL SELECT 'packet_cross_administrative_timeline_v1', length(events) + length(houjin_summary) FROM jpcite_credit_2026_05.packet_cross_administrative_timeline_v1
  UNION ALL SELECT 'packet_public_procurement_trend_v1', length(cell_stats) + length(top_winners) FROM jpcite_credit_2026_05.packet_public_procurement_trend_v1
  UNION ALL SELECT 'packet_regulation_impact_simulator_v1', length(amendment) + length(impacted_houjin) FROM jpcite_credit_2026_05.packet_regulation_impact_simulator_v1
  UNION ALL SELECT 'packet_patent_environmental_link_v1', length(patent_adoptions) + length(env_signals) FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1
  UNION ALL SELECT 'packet_diet_question_amendment_correlate_v1', length(diet_policy_origin_facts) + length(amendment_diffs) FROM jpcite_credit_2026_05.packet_diet_question_amendment_correlate_v1
  UNION ALL SELECT 'packet_edinet_program_subsidy_compounding_v1', length(edinet_anchor_aliases) + length(subsidy_adoption_breakdown) FROM jpcite_credit_2026_05.packet_edinet_program_subsidy_compounding_v1
  UNION ALL SELECT 'packet_kanpou_program_event_link_v1', length(kanpou_relevant_events) + length(all_other_events) FROM jpcite_credit_2026_05.packet_kanpou_program_event_link_v1
  UNION ALL SELECT 'packet_kfs_saiketsu_industry_radar_v1', length(industry_buckets) + length(saiketsu_sample) FROM jpcite_credit_2026_05.packet_kfs_saiketsu_industry_radar_v1
  UNION ALL SELECT 'packet_municipal_budget_match_v1', length(top_municipalities) + length(top_programs) FROM jpcite_credit_2026_05.packet_municipal_budget_match_v1
  UNION ALL SELECT 'packet_trademark_industry_density_v1', length(trademark_adoptions) FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
  UNION ALL SELECT 'packet_environmental_disposal_radar_v1', length(disposal_enforcements) + length(municipality_actions) FROM jpcite_credit_2026_05.packet_environmental_disposal_radar_v1
  UNION ALL SELECT 'packet_regulatory_change_industry_impact_v1', length(industry_program_amendments) FROM jpcite_credit_2026_05.packet_regulatory_change_industry_impact_v1
  UNION ALL SELECT 'packet_gbiz_invoice_dispatch_match_v1', length(invoice_registrant) + length(houjin_master_match) + length(adoption_history) + length(enforcement_history) FROM jpcite_credit_2026_05.packet_gbiz_invoice_dispatch_match_v1
)
SELECT
  source_table,
  COUNT(*)                                            AS n_docs,
  SUM(COALESCE(approx_bytes, 0))                      AS total_approx_bytes,
  AVG(COALESCE(approx_bytes, 0))                      AS avg_approx_bytes,
  MIN(COALESCE(approx_bytes, 0))                      AS min_approx_bytes,
  MAX(COALESCE(approx_bytes, 0))                      AS max_approx_bytes,
  APPROX_PERCENTILE(COALESCE(approx_bytes, 0), 0.5)   AS p50_bytes,
  APPROX_PERCENTILE(COALESCE(approx_bytes, 0), 0.95)  AS p95_bytes
FROM sized
GROUP BY source_table
ORDER BY total_approx_bytes DESC
LIMIT 100;
