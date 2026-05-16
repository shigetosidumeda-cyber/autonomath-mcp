-- q16_wave60_65_cross_industry_x_cross_finance_rollup.sql (Wave 67 re-run)
--
-- Wave 60-65 specific ultra-aggregate. Cross-industry packets (wave60 set
-- already in q11) extended with the Wave 61-65 financial / monetary /
-- governance / international / financial-markets surfaces that landed in
-- the 687-packet sync (commit 878c09e74). Goal: confirm the new tables
-- are populated AND surface which financial-axis families compound on
-- top of the industry-axis to establish the Y2 cross-finance moat.
--
-- Family scope:
--   wave60_industry = 12 cross-industry macro packets (already in q11; included for parity)
--   wave61_financial = bond_issuance / dividend_policy / capital_raising /
--                      cash_runway / funding_to_revenue / kpi_funding /
--                      ipo_pipeline / shareholder_return / executive_comp /
--                      insider_trading_disclosure
--   wave62_sectoral = construction_public_works / manufacturing_dx_grants /
--                     healthcare_compliance_subsidy / retail_inbound_subsidy /
--                     transport_logistics_grants / energy_efficiency_subsidy /
--                     education_research_grants / non_profit_program_overlay /
--                     payroll_subsidy_intensity / agriculture_program_intensity
--   wave63_governance = audit_firm_rotation / board_diversity_signal /
--                       consumer_protection_compliance / carbon_reporting_compliance /
--                       antimonopoly_violation_intensity / regulatory_audit_outcomes /
--                       product_recall_intensity / environmental_disclosure /
--                       industry_compliance_index / related_party_transaction
--   wave64_international = bilateral_trade_program / cross_border_remittance /
--                          double_tax_treaty_impact / fdi_security_review /
--                          foreign_direct_investment / import_export_license /
--                          international_arbitration_venue / tax_haven_subsidiary /
--                          us_export_control_overlap / wto_subsidy_compliance
--   wave65_markets = fpd_etf_holdings / listed_company_disclosure_pulse /
--                    m_a_event_signals / revenue_volatility_subsidy_offset /
--                    subsidy_roi_estimate / iso_certification_overlap /
--                    invoice_payment_velocity / trade_finance_eligibility /
--                    debt_subsidy_stack / patent_subsidy_intersection
--
-- Pattern: SELECT 1 per row + GROUP BY family. Parquet column pruning
-- keeps scan small even across 50+ tables; honors 100 GB workgroup cap
-- and stays under $0.05.

WITH all_packets AS (
  -- wave60_industry (12, already in q11; re-listed for self-consistent family rollup)
  SELECT 'wave60_industry' AS wave_family, 'trademark_industry_density' AS src, 1 AS row_cnt FROM jpcite_credit_2026_05.packet_trademark_industry_density_v1
  UNION ALL SELECT 'wave60_industry','trademark_brand_protection',1 FROM jpcite_credit_2026_05.packet_trademark_brand_protection_v1
  UNION ALL SELECT 'wave60_industry','permit_renewal_calendar',1 FROM jpcite_credit_2026_05.packet_permit_renewal_calendar_v1
  UNION ALL SELECT 'wave60_industry','statistics_market_size',1 FROM jpcite_credit_2026_05.packet_statistics_market_size_v1
  UNION ALL SELECT 'wave60_industry','regulation_impact_simulator',1 FROM jpcite_credit_2026_05.packet_regulation_impact_simulator_v1
  UNION ALL SELECT 'wave60_industry','regulatory_change_industry_impact',1 FROM jpcite_credit_2026_05.packet_regulatory_change_industry_impact_v1
  UNION ALL SELECT 'wave60_industry','regulatory_change_radar',1 FROM jpcite_credit_2026_05.packet_regulatory_change_radar_v1
  UNION ALL SELECT 'wave60_industry','public_procurement_trend',1 FROM jpcite_credit_2026_05.packet_public_procurement_trend_v1
  UNION ALL SELECT 'wave60_industry','succession_program_matching',1 FROM jpcite_credit_2026_05.packet_succession_program_matching_v1
  UNION ALL SELECT 'wave60_industry','tax_treaty_japan_inbound',1 FROM jpcite_credit_2026_05.packet_tax_treaty_japan_inbound_v1
  UNION ALL SELECT 'wave60_industry','vendor_due_diligence',1 FROM jpcite_credit_2026_05.packet_vendor_due_diligence_v1
  UNION ALL SELECT 'wave60_industry','local_government_subsidy_aggregator',1 FROM jpcite_credit_2026_05.packet_local_government_subsidy_aggregator_v1

  -- wave61_financial (10)
  UNION ALL SELECT 'wave61_financial','bond_issuance_pattern',1 FROM jpcite_credit_2026_05.packet_bond_issuance_pattern_v1
  UNION ALL SELECT 'wave61_financial','dividend_policy_stability',1 FROM jpcite_credit_2026_05.packet_dividend_policy_stability_v1
  UNION ALL SELECT 'wave61_financial','capital_raising_history',1 FROM jpcite_credit_2026_05.packet_capital_raising_history_v1
  UNION ALL SELECT 'wave61_financial','cash_runway_estimate',1 FROM jpcite_credit_2026_05.packet_cash_runway_estimate_v1
  UNION ALL SELECT 'wave61_financial','funding_to_revenue_ratio',1 FROM jpcite_credit_2026_05.packet_funding_to_revenue_ratio_v1
  UNION ALL SELECT 'wave61_financial','kpi_funding_correlation',1 FROM jpcite_credit_2026_05.packet_kpi_funding_correlation_v1
  UNION ALL SELECT 'wave61_financial','ipo_pipeline_signal',1 FROM jpcite_credit_2026_05.packet_ipo_pipeline_signal_v1
  UNION ALL SELECT 'wave61_financial','shareholder_return_intensity',1 FROM jpcite_credit_2026_05.packet_shareholder_return_intensity_v1
  UNION ALL SELECT 'wave61_financial','executive_compensation_disclosure',1 FROM jpcite_credit_2026_05.packet_executive_compensation_disclosure_v1
  UNION ALL SELECT 'wave61_financial','insider_trading_disclosure',1 FROM jpcite_credit_2026_05.packet_insider_trading_disclosure_v1

  -- wave62_sectoral (10)
  UNION ALL SELECT 'wave62_sectoral','construction_public_works',1 FROM jpcite_credit_2026_05.packet_construction_public_works_v1
  UNION ALL SELECT 'wave62_sectoral','manufacturing_dx_grants',1 FROM jpcite_credit_2026_05.packet_manufacturing_dx_grants_v1
  UNION ALL SELECT 'wave62_sectoral','healthcare_compliance_subsidy',1 FROM jpcite_credit_2026_05.packet_healthcare_compliance_subsidy_v1
  UNION ALL SELECT 'wave62_sectoral','retail_inbound_subsidy',1 FROM jpcite_credit_2026_05.packet_retail_inbound_subsidy_v1
  UNION ALL SELECT 'wave62_sectoral','transport_logistics_grants',1 FROM jpcite_credit_2026_05.packet_transport_logistics_grants_v1
  UNION ALL SELECT 'wave62_sectoral','energy_efficiency_subsidy',1 FROM jpcite_credit_2026_05.packet_energy_efficiency_subsidy_v1
  UNION ALL SELECT 'wave62_sectoral','education_research_grants',1 FROM jpcite_credit_2026_05.packet_education_research_grants_v1
  UNION ALL SELECT 'wave62_sectoral','non_profit_program_overlay',1 FROM jpcite_credit_2026_05.packet_non_profit_program_overlay_v1
  UNION ALL SELECT 'wave62_sectoral','payroll_subsidy_intensity',1 FROM jpcite_credit_2026_05.packet_payroll_subsidy_intensity_v1
  UNION ALL SELECT 'wave62_sectoral','agriculture_program_intensity',1 FROM jpcite_credit_2026_05.packet_agriculture_program_intensity_v1

  -- wave63_governance (10)
  UNION ALL SELECT 'wave63_governance','audit_firm_rotation',1 FROM jpcite_credit_2026_05.packet_audit_firm_rotation_v1
  UNION ALL SELECT 'wave63_governance','board_diversity_signal',1 FROM jpcite_credit_2026_05.packet_board_diversity_signal_v1
  UNION ALL SELECT 'wave63_governance','consumer_protection_compliance',1 FROM jpcite_credit_2026_05.packet_consumer_protection_compliance_v1
  UNION ALL SELECT 'wave63_governance','carbon_reporting_compliance',1 FROM jpcite_credit_2026_05.packet_carbon_reporting_compliance_v1
  UNION ALL SELECT 'wave63_governance','antimonopoly_violation_intensity',1 FROM jpcite_credit_2026_05.packet_antimonopoly_violation_intensity_v1
  UNION ALL SELECT 'wave63_governance','regulatory_audit_outcomes',1 FROM jpcite_credit_2026_05.packet_regulatory_audit_outcomes_v1
  UNION ALL SELECT 'wave63_governance','product_recall_intensity',1 FROM jpcite_credit_2026_05.packet_product_recall_intensity_v1
  UNION ALL SELECT 'wave63_governance','environmental_disclosure',1 FROM jpcite_credit_2026_05.packet_environmental_disclosure_v1
  UNION ALL SELECT 'wave63_governance','industry_compliance_index',1 FROM jpcite_credit_2026_05.packet_industry_compliance_index_v1
  UNION ALL SELECT 'wave63_governance','related_party_transaction',1 FROM jpcite_credit_2026_05.packet_related_party_transaction_v1

  -- wave64_international (10)
  UNION ALL SELECT 'wave64_international','bilateral_trade_program',1 FROM jpcite_credit_2026_05.packet_bilateral_trade_program_v1
  UNION ALL SELECT 'wave64_international','cross_border_remittance',1 FROM jpcite_credit_2026_05.packet_cross_border_remittance_v1
  UNION ALL SELECT 'wave64_international','double_tax_treaty_impact',1 FROM jpcite_credit_2026_05.packet_double_tax_treaty_impact_v1
  UNION ALL SELECT 'wave64_international','fdi_security_review',1 FROM jpcite_credit_2026_05.packet_fdi_security_review_v1
  UNION ALL SELECT 'wave64_international','foreign_direct_investment',1 FROM jpcite_credit_2026_05.packet_foreign_direct_investment_v1
  UNION ALL SELECT 'wave64_international','import_export_license',1 FROM jpcite_credit_2026_05.packet_import_export_license_v1
  UNION ALL SELECT 'wave64_international','international_arbitration_venue',1 FROM jpcite_credit_2026_05.packet_international_arbitration_venue_v1
  UNION ALL SELECT 'wave64_international','tax_haven_subsidiary',1 FROM jpcite_credit_2026_05.packet_tax_haven_subsidiary_v1
  UNION ALL SELECT 'wave64_international','us_export_control_overlap',1 FROM jpcite_credit_2026_05.packet_us_export_control_overlap_v1
  UNION ALL SELECT 'wave64_international','wto_subsidy_compliance',1 FROM jpcite_credit_2026_05.packet_wto_subsidy_compliance_v1

  -- wave65_markets (10)
  UNION ALL SELECT 'wave65_markets','fpd_etf_holdings',1 FROM jpcite_credit_2026_05.packet_fpd_etf_holdings_v1
  UNION ALL SELECT 'wave65_markets','listed_company_disclosure_pulse',1 FROM jpcite_credit_2026_05.packet_listed_company_disclosure_pulse_v1
  UNION ALL SELECT 'wave65_markets','m_a_event_signals',1 FROM jpcite_credit_2026_05.packet_m_a_event_signals_v1
  UNION ALL SELECT 'wave65_markets','revenue_volatility_subsidy_offset',1 FROM jpcite_credit_2026_05.packet_revenue_volatility_subsidy_offset_v1
  UNION ALL SELECT 'wave65_markets','subsidy_roi_estimate',1 FROM jpcite_credit_2026_05.packet_subsidy_roi_estimate_v1
  UNION ALL SELECT 'wave65_markets','iso_certification_overlap',1 FROM jpcite_credit_2026_05.packet_iso_certification_overlap_v1
  UNION ALL SELECT 'wave65_markets','invoice_payment_velocity',1 FROM jpcite_credit_2026_05.packet_invoice_payment_velocity_v1
  UNION ALL SELECT 'wave65_markets','trade_finance_eligibility',1 FROM jpcite_credit_2026_05.packet_trade_finance_eligibility_v1
  UNION ALL SELECT 'wave65_markets','debt_subsidy_stack',1 FROM jpcite_credit_2026_05.packet_debt_subsidy_stack_v1
  UNION ALL SELECT 'wave65_markets','patent_subsidy_intersection',1 FROM jpcite_credit_2026_05.packet_patent_subsidy_intersection_v1
)
SELECT
  wave_family,
  COUNT(*) AS row_count_total,
  COUNT(DISTINCT src) AS distinct_packet_sources
FROM all_packets
GROUP BY wave_family
ORDER BY row_count_total DESC
LIMIT 100
