-- q38_wave89_ma_x_wave69_entity_360.sql (Wave 89-91)
--
-- Wave 89 M&A / succession / governance family × Wave 69 entity_360
-- family cross-join. The M&A × entity_360 axis is the canonical
-- corporate-event vs entity-state alignment surface: when a corp has
-- BOTH (a) M&A / succession / board-overlap signal (Wave 89) AND
-- (b) entity_360 facet coverage (Wave 69), the M&A advisor / proxy
-- analyst can read the corporate-event vs 360-coverage density.
-- Cross-join produces the bilateral surface that M&A target-screen
-- DD needs.
--
-- Wave 89 (M&A / succession / governance) tables in scope (all LIVE
-- in Glue per 2026-05-17 verify):
--   m_a_event_signals / entity_succession_360 / founding_succession_chain /
--   succession_event_pulse / succession_program_matching /
--   board_member_overlap / executive_compensation_disclosure /
--   board_diversity_signal / anti_trust_settlement_history /
--   related_party_transaction / ipo_pipeline_signal /
--   houjin_parent_subsidiary / dividend_policy_stability.
--
-- Wave 69 (entity_360) tables in scope:
--   entity_360_summary / entity_subsidy_360 / entity_certification_360 /
--   entity_risk_360 / entity_compliance_360 / entity_court_360 /
--   entity_invoice_360 / entity_partner_360 / entity_succession_360.
--
-- Pattern: per-family rollup (COUNT + approx_distinct subject.id)
-- CROSS JOIN producing (ma_family, entity_360_family) pairs with
-- combined coverage density + M&A-to-entity alignment ratio. Honors
-- the 50 GB PERF-14 cap (BytesScannedCutoffPerQuery).

WITH wave89_ma AS (
  SELECT 'm_a_event_signals' AS src,
         COUNT(*) AS row_count,
         approx_distinct(json_extract_scalar(subject, '$.id')) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_m_a_event_signals_v1

  UNION ALL
  SELECT 'entity_succession_360',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_entity_succession_360_v1

  UNION ALL
  SELECT 'founding_succession_chain',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_founding_succession_chain_v1

  UNION ALL
  SELECT 'succession_event_pulse',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_succession_event_pulse_v1

  UNION ALL
  SELECT 'succession_program_matching',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_succession_program_matching_v1

  UNION ALL
  SELECT 'board_member_overlap',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_board_member_overlap_v1

  UNION ALL
  SELECT 'executive_compensation_disclosure',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_executive_compensation_disclosure_v1

  UNION ALL
  SELECT 'board_diversity_signal',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_board_diversity_signal_v1

  UNION ALL
  SELECT 'anti_trust_settlement_history',
         COUNT(*),
         approx_distinct(json_extract_scalar(subject, '$.id'))
  FROM jpcite_credit_2026_05.packet_anti_trust_settlement_history_v1
),
wave69_entity_360 AS (
  SELECT 'entity_360_summary' AS src,
         COUNT(*) AS row_count,
         approx_distinct(houjin_bangou) AS approx_distinct_subjects
  FROM jpcite_credit_2026_05.packet_entity_360_summary_v1

  UNION ALL
  SELECT 'entity_subsidy_360',
         COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_subsidy_360_v1

  UNION ALL
  SELECT 'entity_certification_360',
         COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_certification_360_v1

  UNION ALL
  SELECT 'entity_risk_360',
         COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_risk_360_v1

  UNION ALL
  SELECT 'entity_compliance_360',
         COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_compliance_360_v1

  UNION ALL
  SELECT 'entity_invoice_360',
         COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_invoice_360_v1

  UNION ALL
  SELECT 'entity_partner_360',
         COUNT(*),
         approx_distinct(houjin_bangou)
  FROM jpcite_credit_2026_05.packet_entity_partner_360_v1
)
SELECT
  m.src AS wave89_ma_family,
  m.row_count AS ma_row_count,
  m.approx_distinct_subjects AS ma_distinct_subjects,
  e.src AS wave69_entity_360_family,
  e.row_count AS entity_360_row_count,
  e.approx_distinct_subjects AS entity_360_distinct_subjects,
  -- M&A-to-entity_360 alignment: distinct subjects ratio capped at
  -- 1.0. Reads as "% of entity_360-tracked corps that also carry an
  -- M&A / succession event signal" — proxy for M&A pipeline density
  -- per 360 facet.
  CASE
    WHEN e.approx_distinct_subjects = 0 THEN 0.0
    ELSE LEAST(1.0,
               CAST(m.approx_distinct_subjects AS DOUBLE)
               / CAST(e.approx_distinct_subjects AS DOUBLE))
  END AS ma_entity_360_alignment_density
FROM wave89_ma m
CROSS JOIN wave69_entity_360 e
ORDER BY m.row_count DESC, e.row_count DESC
LIMIT 200
