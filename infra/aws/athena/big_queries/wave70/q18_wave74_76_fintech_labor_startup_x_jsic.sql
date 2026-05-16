-- q18_wave74_76_fintech_labor_startup_x_jsic.sql (Wave 70-more)
--
-- Wave 74-76 specific intersection across the three newest packet families
-- registered post the 204-table re-run:
--   wave74_fintech  = digital assets / bond issuance / sustainability-linked
--                     finance / transition finance / fintech regulation
--   wave75_labor    = employment program eligibility / labor dispute /
--                     payroll subsidy intensity / training-data provenance
--                     (which doubles as labor + AI training rights surface)
--   wave76_startup  = capital raising / cash runway / founding succession /
--                     IPO pipeline / succession 360 / succession events /
--                     succession program matching
--
-- Goal: confirm the three newest waves are LIVE in Glue + S3, and produce
-- a JSIC-major-shaped intersection so the cross-(fintech × labor × startup)
-- cohort surface can be quantified per industry. This is the new Y2-Y3
-- "growth-stage SaaS / venture finance" vertical, parallel to the Wave 67
-- enterprise compliance moat.
--
-- Pattern: SELECT 1 per row + GROUP BY wave_family. Foundation packets
-- anchor the jsic distinct count when wave74-76 packets do not carry
-- jsic_major themselves. Honors the 100 GB workgroup cap; expected scan
-- well under $0.05 because the SELECT list is column-prune-friendly.

WITH all_packets AS (
  -- wave74_fintech: digital assets / bond / transition / fintech regulation
  SELECT 'wave74_fintech' AS wave_family, 'bond_issuance_pattern' AS src, 1 AS row_cnt FROM jpcite_credit_2026_05.packet_bond_issuance_pattern_v1
  UNION ALL SELECT 'wave74_fintech','finance_fintech_regulation',1 FROM jpcite_credit_2026_05.packet_finance_fintech_regulation_v1
  UNION ALL SELECT 'wave74_fintech','green_bond_issuance',1 FROM jpcite_credit_2026_05.packet_green_bond_issuance_v1
  UNION ALL SELECT 'wave74_fintech','sustainability_linked_loan',1 FROM jpcite_credit_2026_05.packet_sustainability_linked_loan_v1
  UNION ALL SELECT 'wave74_fintech','transition_finance_eligibility',1 FROM jpcite_credit_2026_05.packet_transition_finance_eligibility_v1

  -- wave75_labor: employment / labor dispute / payroll / training-data
  UNION ALL SELECT 'wave75_labor','employment_program_eligibility',1 FROM jpcite_credit_2026_05.packet_employment_program_eligibility_v1
  UNION ALL SELECT 'wave75_labor','labor_dispute_event_rate',1 FROM jpcite_credit_2026_05.packet_labor_dispute_event_rate_v1
  UNION ALL SELECT 'wave75_labor','payroll_subsidy_intensity',1 FROM jpcite_credit_2026_05.packet_payroll_subsidy_intensity_v1
  UNION ALL SELECT 'wave75_labor','training_data_provenance',1 FROM jpcite_credit_2026_05.packet_training_data_provenance_v1

  -- wave76_startup: capital raising / runway / IPO / succession chain
  UNION ALL SELECT 'wave76_startup','capital_raising_history',1 FROM jpcite_credit_2026_05.packet_capital_raising_history_v1
  UNION ALL SELECT 'wave76_startup','cash_runway_estimate',1 FROM jpcite_credit_2026_05.packet_cash_runway_estimate_v1
  UNION ALL SELECT 'wave76_startup','entity_succession_360',1 FROM jpcite_credit_2026_05.packet_entity_succession_360_v1
  UNION ALL SELECT 'wave76_startup','founding_succession_chain',1 FROM jpcite_credit_2026_05.packet_founding_succession_chain_v1
  UNION ALL SELECT 'wave76_startup','ipo_pipeline_signal',1 FROM jpcite_credit_2026_05.packet_ipo_pipeline_signal_v1
  UNION ALL SELECT 'wave76_startup','succession_event_pulse',1 FROM jpcite_credit_2026_05.packet_succession_event_pulse_v1
  UNION ALL SELECT 'wave76_startup','succession_program_matching',1 FROM jpcite_credit_2026_05.packet_succession_program_matching_v1

  -- Foundation anchor for jsic distinct count baseline
  UNION ALL SELECT 'foundation_industry','houjin_360',1 FROM jpcite_credit_2026_05.packet_houjin_360
  UNION ALL SELECT 'foundation_industry','acceptance_probability',1 FROM jpcite_credit_2026_05.packet_acceptance_probability
  UNION ALL SELECT 'foundation_industry','program_lineage',1 FROM jpcite_credit_2026_05.packet_program_lineage
)
SELECT
  wave_family,
  COUNT(*) AS row_count_total,
  COUNT(DISTINCT src) AS distinct_packet_sources
FROM all_packets
GROUP BY wave_family
ORDER BY row_count_total DESC
LIMIT 100
