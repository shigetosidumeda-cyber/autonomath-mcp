-- q4_relationship_x_crosssource.sql (Wave 58)
--
-- Cross-join Wave 58 (relationship) × Wave 54 cross-source. Wave 54 = the
-- 10 cross-source packets (patent_environmental_link, diet_question
-- amendment correlate, edinet program subsidy compounding, kanpou program
-- event link, kfs saiketsu industry radar, municipal budget match,
-- trademark industry density, environmental disposal radar, regulatory
-- change industry impact, gbiz invoice dispatch match). The join surface:
-- corporate-network node × multi-source observation density.
--
-- Join key normalization:
--   * subject.id (houjin_bangou)
--   * cohort_definition.cohort_id
-- All packet bodies are JSON STRING.

WITH wave58_rel AS (
  SELECT
    COALESCE(
      json_extract_scalar(subject, '$.id'),
      json_extract_scalar(cohort_definition, '$.cohort_id'),
      'UNKNOWN'
    ) AS join_key,
    'packet_board_member_overlap_v1' AS rel_source,
    generated_at AS rel_generated_at,
    CAST(json_extract_scalar(metrics, '$.overlap_total') AS DOUBLE) AS rel_metric
  FROM jpcite_credit_2026_05.packet_board_member_overlap_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_business_partner_360_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.bid_history_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_business_partner_360_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_certification_houjin_link_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.linked_houjin_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_certification_houjin_link_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_employment_program_eligibility_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.program_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_employment_program_eligibility_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_founding_succession_chain_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_adoptions') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_founding_succession_chain_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_houjin_parent_subsidiary_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.group_size_total') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_houjin_parent_subsidiary_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_industry_association_link_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.support_org_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_industry_association_link_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_license_houjin_jurisdiction_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.permit_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_license_houjin_jurisdiction_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_public_listed_program_link_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.adoption_link_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_public_listed_program_link_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_vendor_payment_history_match_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.unique_procurer_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_vendor_payment_history_match_v1
),
wave54_cs AS (
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN') AS join_key,
    'packet_patent_environmental_link_v1' AS cs_source,
    generated_at AS cs_generated_at,
    CAST(json_extract_scalar(metrics, '$.patent_adoption_count') AS DOUBLE) AS cs_metric
  FROM jpcite_credit_2026_05.packet_patent_environmental_link_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_diet_question_amendment_correlate_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.shitsugi_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_diet_question_amendment_correlate_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_edinet_program_subsidy_compounding_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.adoption_breakdown_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_edinet_program_subsidy_compounding_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_kanpou_program_event_link_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.kanpou_event_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_kanpou_program_event_link_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_kfs_saiketsu_industry_radar_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.saiketsu_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_kfs_saiketsu_industry_radar_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_municipal_budget_match_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.total_adoptions') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_municipal_budget_match_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_trademark_industry_density_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.trademark_adoption_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_environmental_disposal_radar_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.disposal_enforcement_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_environmental_disposal_radar_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_regulatory_change_industry_impact_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.industry_amendment_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_regulatory_change_industry_impact_v1
  UNION ALL
  SELECT
    COALESCE(json_extract_scalar(subject, '$.id'),
             json_extract_scalar(cohort_definition, '$.cohort_id'), 'UNKNOWN'),
    'packet_gbiz_invoice_dispatch_match_v1', generated_at,
    CAST(json_extract_scalar(metrics, '$.match_count') AS DOUBLE)
  FROM jpcite_credit_2026_05.packet_gbiz_invoice_dispatch_match_v1
)
SELECT
  rel.join_key,
  rel.rel_source,
  cs.cs_source,
  COUNT(*) AS triple_count,
  AVG(rel.rel_metric) AS avg_rel_metric,
  AVG(cs.cs_metric) AS avg_cs_metric,
  MAX(rel.rel_generated_at) AS latest_rel,
  MAX(cs.cs_generated_at) AS latest_cs
FROM wave58_rel rel
LEFT JOIN wave54_cs cs ON rel.join_key = cs.join_key
WHERE rel.join_key != 'UNKNOWN'
GROUP BY rel.join_key, rel.rel_source, cs.cs_source
ORDER BY triple_count DESC
LIMIT 5000
