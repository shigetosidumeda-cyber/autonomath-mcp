-- q41_wave89_91_x_jsic_intersection.sql (Wave 89-91)
--
-- Wave 89 (M&A / succession / governance) + Wave 90 (talent / workforce
-- / leadership) + Wave 91 (brand / customer proxy) × jsic_major
-- intersection. Three new wave families rolled up against the
-- canonical JSIC industry axis used by wave70/q21, wave82/q26,
-- wave85/q31, wave88/q36. Tables without jsic_major are bucketed to
-- 'UNK' so the per-family row totals stay honest.
--
-- The 3-bucket Wave 89-91 surface this produces is the corporate-
-- event + leadership-signal + brand-equity cross-section, sliced on
-- industry — the canonical "which JSIC sector carries the most M&A
-- + talent + brand signal density" view.
--
-- Pattern: SELECT 1 per row with json_extract_scalar(subject,
-- '$.jsic_major') as the axis. Foundation packet_houjin_360 is added
-- so the baseline JSIC distribution is observable in the same output.
-- Honors the 50 GB PERF-14 cap.

WITH all_packets AS (
  -- Wave 89 M&A / succession / governance
  SELECT 'wave89_ma' AS wave_family, 'm_a_event_signals' AS src,
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK') AS jsic_major
  FROM jpcite_credit_2026_05.packet_m_a_event_signals_v1

  UNION ALL SELECT 'wave89_ma', 'entity_succession_360',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_entity_succession_360_v1

  UNION ALL SELECT 'wave89_ma', 'founding_succession_chain',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_founding_succession_chain_v1

  UNION ALL SELECT 'wave89_ma', 'succession_event_pulse',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_succession_event_pulse_v1

  UNION ALL SELECT 'wave89_ma', 'succession_program_matching',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_succession_program_matching_v1

  UNION ALL SELECT 'wave89_ma', 'board_member_overlap',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_board_member_overlap_v1

  UNION ALL SELECT 'wave89_ma', 'executive_compensation_disclosure',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_executive_compensation_disclosure_v1

  UNION ALL SELECT 'wave89_ma', 'board_diversity_signal',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_board_diversity_signal_v1

  UNION ALL SELECT 'wave89_ma', 'anti_trust_settlement_history',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_anti_trust_settlement_history_v1

  -- Wave 90 talent / workforce / leadership (live proxies)
  UNION ALL SELECT 'wave90_talent', 'employer_brand_signal',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_employer_brand_signal_v1

  UNION ALL SELECT 'wave90_talent', 'gender_workforce_balance',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_gender_workforce_balance_v1

  UNION ALL SELECT 'wave90_talent', 'training_data_provenance',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_training_data_provenance_v1

  -- Wave 91 brand / customer proxy
  UNION ALL SELECT 'wave91_brand', 'trademark_brand_protection',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1

  UNION ALL SELECT 'wave91_brand', 'trademark_industry_density',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1

  UNION ALL SELECT 'wave91_brand', 'trademark_registration_intensity',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_trademark_registration_intensity_v1

  UNION ALL SELECT 'wave91_brand', 'review_sentiment_aggregate',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_review_sentiment_aggregate_v1

  UNION ALL SELECT 'wave91_brand', 'investor_relations_intensity',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_investor_relations_intensity_v1

  UNION ALL SELECT 'wave91_brand', 'press_release_pulse',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_press_release_pulse_v1

  UNION ALL SELECT 'wave91_brand', 'media_relations_pattern',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_media_relations_pattern_v1

  -- Foundation anchor (houjin_360) so the JSIC distribution baseline
  -- is observable in the same output
  UNION ALL SELECT 'foundation', 'houjin_360',
         COALESCE(json_extract_scalar(subject, '$.jsic_major'), 'UNK')
  FROM jpcite_credit_2026_05.packet_houjin_360
)
SELECT
  wave_family,
  jsic_major,
  COUNT(*) AS row_count,
  COUNT(DISTINCT src) AS distinct_packet_sources
FROM all_packets
GROUP BY wave_family, jsic_major
ORDER BY wave_family, row_count DESC
LIMIT 500
