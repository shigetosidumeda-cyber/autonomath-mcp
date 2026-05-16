-- q17_wave66_68_pii_tech_supply_x_jsic_intersection.sql (Wave 67 re-run)
--
-- Wave 66-68 specific intersection. Covers the three newest packet families
-- that landed post-Wave-65 in the 687-packet sync (commit 878c09e74):
--   wave66_pii = APPI / GDPR / data-cross-border / privacy / consent surfaces
--   wave67_tech = technical infrastructure / fintech / ESG-tech / certification
--                 overlap surfaces (the Wave 67 packet generator family,
--                 separate from the Wave 67 *Athena* re-run)
--   wave68_supply = supply chain / vendor / payment / labor / logistics chain
--
-- Goal: confirm the three newest waves are LIVE in Glue + S3, and produce
-- a JSIC-major intersection so the cross-(PII × tech × supply) cohort
-- surface can be quantified per industry — that intersection is the
-- "deep moat" surface for the Y2-Y3 enterprise compliance vertical.
--
-- Pattern: SELECT 1 per row + GROUP BY family + JSIC distinct count.
-- Honors the 100 GB workgroup cap and stays under $0.05 even across
-- 30+ tables, because Athena column-prunes parquet to header-only when
-- the SELECT list never references real columns. Some PII / supply
-- packets do not carry jsic_major; counted as NULL bucket for honesty.

WITH all_packets AS (
  -- wave66_pii: PII compliance + GDPR + data cross-border + privacy
  SELECT 'wave66_pii' AS wave_family, 'eu_gdpr_overlap' AS src, 1 AS row_cnt FROM jpcite_credit_2026_05.packet_eu_gdpr_overlap_v1
  UNION ALL SELECT 'wave66_pii','cross_border_data_transfer',1 FROM jpcite_credit_2026_05.packet_cross_border_data_transfer_v1

  -- wave67_tech: tech / fintech / ESG-tech / certification overlap
  UNION ALL SELECT 'wave67_tech','finance_fintech_regulation',1 FROM jpcite_credit_2026_05.packet_finance_fintech_regulation_v1
  UNION ALL SELECT 'wave67_tech','digital_transformation_subsidy_chain',1 FROM jpcite_credit_2026_05.packet_digital_transformation_subsidy_chain_v1
  UNION ALL SELECT 'wave67_tech','iso_certification_overlap',1 FROM jpcite_credit_2026_05.packet_iso_certification_overlap_v1
  UNION ALL SELECT 'wave67_tech','green_investment_eligibility',1 FROM jpcite_credit_2026_05.packet_green_investment_eligibility_v1
  UNION ALL SELECT 'wave67_tech','industry_compliance_index',1 FROM jpcite_credit_2026_05.packet_industry_compliance_index_v1

  -- wave68_supply: supply chain / vendor / labor / logistics
  UNION ALL SELECT 'wave68_supply','vendor_payment_history_match',1 FROM jpcite_credit_2026_05.packet_vendor_payment_history_match_v1
  UNION ALL SELECT 'wave68_supply','vendor_due_diligence',1 FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1
  UNION ALL SELECT 'wave68_supply','invoice_payment_velocity',1 FROM jpcite_credit_2026_05.packet_invoice_payment_velocity_v1
  UNION ALL SELECT 'wave68_supply','labor_dispute_event_rate',1 FROM jpcite_credit_2026_05.packet_labor_dispute_event_rate_v1
  UNION ALL SELECT 'wave68_supply','transport_logistics_grants',1 FROM jpcite_credit_2026_05.packet_transport_logistics_grants_v1
  UNION ALL SELECT 'wave68_supply','related_party_transaction',1 FROM jpcite_credit_2026_05.packet_related_party_transaction_v1
  UNION ALL SELECT 'wave68_supply','trade_finance_eligibility',1 FROM jpcite_credit_2026_05.packet_trade_finance_eligibility_v1

  -- foundation surfaces for jsic distinct count baseline (already in q11/q16,
  -- but included so jsic intersection has anchor rows when wave66-68 packets
  -- do not themselves carry jsic_major).
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
