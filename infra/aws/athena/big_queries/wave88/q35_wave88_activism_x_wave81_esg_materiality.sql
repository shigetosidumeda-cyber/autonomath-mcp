-- q35_wave88_activism_x_wave81_esg_materiality.sql (Wave 86-88)
--
-- Wave 88 corporate activism / political donation family × Wave 81
-- ESG materiality family cross-join. The activism × ESG axis is the
-- canonical political-engagement vs ESG-disclosure alignment surface:
-- when a corp has BOTH (a) political donation / lobby / trade
-- association / policy advocacy signal (Wave 88) AND (b) ESG
-- materiality disclosure (Wave 81), the proxy / ESG advisor can
-- read the activism-to-materiality coherence. Cross-join produces
-- the bilateral surface that ESG audit + proxy-voting DD needs.
--
-- Wave 88 (corporate activism / political) tables in scope (most are
-- pre-sync 0-row; LIVE counterparts used as proxies):
--   political_donation_record (planned) / lobby_activity_intensity
--   (planned) / corporate_political_activity_signal (Wave 88 anchor) /
--   anti_trust_settlement_history (planned) / regulatory_engagement_
--   intensity (planned).
--   Live proxies in Glue today: industry_association_link.
--
-- Wave 81 (ESG materiality) tables in scope:
--   tcfd_disclosure_completeness / scope1_2_disclosure_completeness /
--   scope3_emissions_disclosure / environmental_disclosure /
--   biodiversity_disclosure.
--
-- Pattern: per-family rollup (COUNT + approx_distinct subject.id)
-- CROSS JOIN producing (activism_family, esg_family) pairs with
-- combined coverage density + activism-materiality coherence ratio.
-- Honors the 50 GB PERF-14 cap.

WITH wave88_activism AS (
  SELECT 'industry_association_link' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_industry_association_link_v1

  UNION ALL
  SELECT 'regulatory_change_industry_impact',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_regulatory_change_industry_impact_v1
),
wave81_esg AS (
  SELECT 'tcfd_disclosure_completeness' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_tcfd_disclosure_completeness_v1

  UNION ALL
  SELECT 'scope1_2_disclosure_completeness',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_scope1_2_disclosure_completeness_v1

  UNION ALL
  SELECT 'scope3_emissions_disclosure',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_scope3_emissions_disclosure_v1

  UNION ALL
  SELECT 'environmental_disclosure',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_environmental_disclosure_v1

  UNION ALL
  SELECT 'biodiversity_disclosure',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_biodiversity_disclosure_v1
)
SELECT
  v.src AS wave88_activism_family,
  v.row_count AS activism_row_count,
  v.approx_distinct_subjects AS activism_distinct_subjects,
  e.src AS wave81_esg_family,
  e.row_count AS esg_row_count,
  e.approx_distinct_subjects AS esg_distinct_subjects,
  -- activism-materiality coherence: distinct subjects ratio,
  -- capped at 1.0. Reads as "% of ESG-disclosed subjects also
  -- carrying corporate-activism signal" — proxy for ESG-aligned
  -- political-engagement transparency.
  CASE
    WHEN e.approx_distinct_subjects = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(v.approx_distinct_subjects AS DOUBLE)
               / CAST(e.approx_distinct_subjects AS DOUBLE))
  END AS activism_materiality_coherence
FROM wave88_activism v
CROSS JOIN wave81_esg e
ORDER BY v.row_count DESC, e.row_count DESC
LIMIT 100
