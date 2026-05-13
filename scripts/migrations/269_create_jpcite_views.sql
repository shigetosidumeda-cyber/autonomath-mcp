-- target_db: autonomath
-- 269_create_jpcite_views.sql
-- Wave 46.B (2026-05-12): jpcite brand alias views over am_* tables
-- Background: internal autonomath schema (am_*) retains 152+ tables for SOT.
-- This migration adds read-only jc_* views (jpcite canonical) over the regular
-- am_* tables so downstream code (operator/ETL/REST/MCP) can migrate to jc_*
-- gradually without dropping or renaming any production table.
--
-- Properties:
--   * Idempotent: every statement uses CREATE VIEW IF NOT EXISTS.
--   * Non-destructive: am_* tables remain SOT; jc_* views are SELECT-only.
--   * Excludes FTS5/vec0 virtual tables (cannot be wrapped by a plain view
--     without losing search capability).
--   * Coverage: 135 regular am_* tables → 135 jc_* views.
--
-- See: docs/research/wave46/STATE_w46_46b_pr.md
-- Memory: project_jpcite_internal_autonomath_rename (view + symlink + env 両 read)
-- Constraints: feedback_destruction_free_organization (no rm/mv)

PRAGMA foreign_keys = OFF;
BEGIN TRANSACTION;

CREATE VIEW IF NOT EXISTS jc_5hop_graph AS SELECT * FROM am_5hop_graph;
CREATE VIEW IF NOT EXISTS jc_actionable_answer_cache AS SELECT * FROM am_actionable_answer_cache;
CREATE VIEW IF NOT EXISTS jc_actionable_qa_cache AS SELECT * FROM am_actionable_qa_cache;
CREATE VIEW IF NOT EXISTS jc_adopted_company_features AS SELECT * FROM am_adopted_company_features;
CREATE VIEW IF NOT EXISTS jc_adoption_trend_monthly AS SELECT * FROM am_adoption_trend_monthly;
CREATE VIEW IF NOT EXISTS jc_alliance_opportunity AS SELECT * FROM am_alliance_opportunity;
CREATE VIEW IF NOT EXISTS jc_alliance_opportunity_refresh_log AS SELECT * FROM am_alliance_opportunity_refresh_log;
CREATE VIEW IF NOT EXISTS jc_amendment_announcement AS SELECT * FROM am_amendment_announcement;
CREATE VIEW IF NOT EXISTS jc_amendment_diff AS SELECT * FROM am_amendment_diff;
CREATE VIEW IF NOT EXISTS jc_annotation_kind AS SELECT * FROM am_annotation_kind;
CREATE VIEW IF NOT EXISTS jc_appi_compliance AS SELECT * FROM am_appi_compliance;
CREATE VIEW IF NOT EXISTS jc_appi_compliance_ingest_log AS SELECT * FROM am_appi_compliance_ingest_log;
CREATE VIEW IF NOT EXISTS jc_authority_contact AS SELECT * FROM am_authority_contact;
CREATE VIEW IF NOT EXISTS jc_budget_subsidy_chain AS SELECT * FROM am_budget_subsidy_chain;
CREATE VIEW IF NOT EXISTS jc_budget_subsidy_chain_meta AS SELECT * FROM am_budget_subsidy_chain_meta;
CREATE VIEW IF NOT EXISTS jc_canonical_vec_case_study_map AS SELECT * FROM am_canonical_vec_case_study_map;
CREATE VIEW IF NOT EXISTS jc_canonical_vec_corporate_map AS SELECT * FROM am_canonical_vec_corporate_map;
CREATE VIEW IF NOT EXISTS jc_canonical_vec_enforcement_map AS SELECT * FROM am_canonical_vec_enforcement_map;
CREATE VIEW IF NOT EXISTS jc_canonical_vec_law_map AS SELECT * FROM am_canonical_vec_law_map;
CREATE VIEW IF NOT EXISTS jc_canonical_vec_program_map AS SELECT * FROM am_canonical_vec_program_map;
CREATE VIEW IF NOT EXISTS jc_canonical_vec_statistic_map AS SELECT * FROM am_canonical_vec_statistic_map;
CREATE VIEW IF NOT EXISTS jc_canonical_vec_tax_measure_map AS SELECT * FROM am_canonical_vec_tax_measure_map;
CREATE VIEW IF NOT EXISTS jc_capital_band_program_match AS SELECT * FROM am_capital_band_program_match;
CREATE VIEW IF NOT EXISTS jc_case_study_narrative AS SELECT * FROM am_case_study_narrative;
CREATE VIEW IF NOT EXISTS jc_case_study_similarity AS SELECT * FROM am_case_study_similarity;
CREATE VIEW IF NOT EXISTS jc_citation_network AS SELECT * FROM am_citation_network;
CREATE VIEW IF NOT EXISTS jc_cohort_5d AS SELECT * FROM am_cohort_5d;
CREATE VIEW IF NOT EXISTS jc_corporate_risk_layer AS SELECT * FROM am_corporate_risk_layer;
CREATE VIEW IF NOT EXISTS jc_court_decisions_extended AS SELECT * FROM am_court_decisions_extended;
CREATE VIEW IF NOT EXISTS jc_court_decisions_v2 AS SELECT * FROM am_court_decisions_v2;
CREATE VIEW IF NOT EXISTS jc_court_decisions_v2_run_log AS SELECT * FROM am_court_decisions_v2_run_log;
CREATE VIEW IF NOT EXISTS jc_credit_pack_purchase AS SELECT * FROM am_credit_pack_purchase;
CREATE VIEW IF NOT EXISTS jc_credit_signal AS SELECT * FROM am_credit_signal;
CREATE VIEW IF NOT EXISTS jc_credit_signal_aggregate AS SELECT * FROM am_credit_signal_aggregate;
CREATE VIEW IF NOT EXISTS jc_credit_signal_run_log AS SELECT * FROM am_credit_signal_run_log;
CREATE VIEW IF NOT EXISTS jc_data_quality_snapshot AS SELECT * FROM am_data_quality_snapshot;
CREATE VIEW IF NOT EXISTS jc_dlq AS SELECT * FROM am_dlq;
CREATE VIEW IF NOT EXISTS jc_edinet_filings AS SELECT * FROM am_edinet_filings;
CREATE VIEW IF NOT EXISTS jc_enforcement_anomaly AS SELECT * FROM am_enforcement_anomaly;
CREATE VIEW IF NOT EXISTS jc_enforcement_detail AS SELECT * FROM am_enforcement_detail;
CREATE VIEW IF NOT EXISTS jc_enforcement_industry_risk AS SELECT * FROM am_enforcement_industry_risk;
CREATE VIEW IF NOT EXISTS jc_enforcement_municipality AS SELECT * FROM am_enforcement_municipality;
CREATE VIEW IF NOT EXISTS jc_enforcement_municipality_run_log AS SELECT * FROM am_enforcement_municipality_run_log;
CREATE VIEW IF NOT EXISTS jc_enforcement_source_index AS SELECT * FROM am_enforcement_source_index;
CREATE VIEW IF NOT EXISTS jc_enforcement_summary AS SELECT * FROM am_enforcement_summary;
CREATE VIEW IF NOT EXISTS jc_entities_vec_e5_embed_log AS SELECT * FROM am_entities_vec_e5_embed_log;
CREATE VIEW IF NOT EXISTS jc_entities_vec_e5_refresh_log AS SELECT * FROM am_entities_vec_e5_refresh_log;
CREATE VIEW IF NOT EXISTS jc_entities_vec_embed_log AS SELECT * FROM am_entities_vec_embed_log;
CREATE VIEW IF NOT EXISTS jc_entities_vec_refresh_log AS SELECT * FROM am_entities_vec_refresh_log;
CREATE VIEW IF NOT EXISTS jc_entities_vec_reranker_score AS SELECT * FROM am_entities_vec_reranker_score;
CREATE VIEW IF NOT EXISTS jc_entities_vec_v2_metadata AS SELECT * FROM am_entities_vec_v2_metadata;
CREATE VIEW IF NOT EXISTS jc_entity_annotation AS SELECT * FROM am_entity_annotation;
CREATE VIEW IF NOT EXISTS jc_entity_appearance_count AS SELECT * FROM am_entity_appearance_count;
CREATE VIEW IF NOT EXISTS jc_entity_density_score AS SELECT * FROM am_entity_density_score;
CREATE VIEW IF NOT EXISTS jc_entity_monthly_snapshot AS SELECT * FROM am_entity_monthly_snapshot;
CREATE VIEW IF NOT EXISTS jc_entity_pagerank AS SELECT * FROM am_entity_pagerank;
CREATE VIEW IF NOT EXISTS jc_fact_signature AS SELECT * FROM am_fact_signature;
CREATE VIEW IF NOT EXISTS jc_fact_source_agreement AS SELECT * FROM am_fact_source_agreement;
CREATE VIEW IF NOT EXISTS jc_fact_source_agreement_run_log AS SELECT * FROM am_fact_source_agreement_run_log;
CREATE VIEW IF NOT EXISTS jc_fdi_country AS SELECT * FROM am_fdi_country;
CREATE VIEW IF NOT EXISTS jc_fdi_country_run_log AS SELECT * FROM am_fdi_country_run_log;
CREATE VIEW IF NOT EXISTS jc_funding_stack_empirical AS SELECT * FROM am_funding_stack_empirical;
CREATE VIEW IF NOT EXISTS jc_geo_industry_density AS SELECT * FROM am_geo_industry_density;
CREATE VIEW IF NOT EXISTS jc_houjin_360_narrative AS SELECT * FROM am_houjin_360_narrative;
CREATE VIEW IF NOT EXISTS jc_houjin_360_snapshot AS SELECT * FROM am_houjin_360_snapshot;
CREATE VIEW IF NOT EXISTS jc_houjin_risk_score AS SELECT * FROM am_houjin_risk_score;
CREATE VIEW IF NOT EXISTS jc_houjin_risk_score_refresh_log AS SELECT * FROM am_houjin_risk_score_refresh_log;
CREATE VIEW IF NOT EXISTS jc_id_bridge AS SELECT * FROM am_id_bridge;
CREATE VIEW IF NOT EXISTS jc_idempotency_cache AS SELECT * FROM am_idempotency_cache;
CREATE VIEW IF NOT EXISTS jc_industry_guidelines AS SELECT * FROM am_industry_guidelines;
CREATE VIEW IF NOT EXISTS jc_industry_jsic_175 AS SELECT * FROM am_industry_jsic_175;
CREATE VIEW IF NOT EXISTS jc_industry_sector_175_run_log AS SELECT * FROM am_industry_sector_175_run_log;
CREATE VIEW IF NOT EXISTS jc_invoice_buyer_seller_graph AS SELECT * FROM am_invoice_buyer_seller_graph;
CREATE VIEW IF NOT EXISTS jc_jpo_patents AS SELECT * FROM am_jpo_patents;
CREATE VIEW IF NOT EXISTS jc_jpo_utility_models AS SELECT * FROM am_jpo_utility_models;
CREATE VIEW IF NOT EXISTS jc_law_article_summary AS SELECT * FROM am_law_article_summary;
CREATE VIEW IF NOT EXISTS jc_law_guideline AS SELECT * FROM am_law_guideline;
CREATE VIEW IF NOT EXISTS jc_law_guideline_run_log AS SELECT * FROM am_law_guideline_run_log;
CREATE VIEW IF NOT EXISTS jc_law_jorei_pref AS SELECT * FROM am_law_jorei_pref;
CREATE VIEW IF NOT EXISTS jc_law_jorei_pref_run_log AS SELECT * FROM am_law_jorei_pref_run_log;
CREATE VIEW IF NOT EXISTS jc_law_translation_progress AS SELECT * FROM am_law_translation_progress;
CREATE VIEW IF NOT EXISTS jc_law_translation_refresh_log AS SELECT * FROM am_law_translation_refresh_log;
CREATE VIEW IF NOT EXISTS jc_law_translation_review_queue AS SELECT * FROM am_law_translation_review_queue;
CREATE VIEW IF NOT EXISTS jc_law_tsutatsu_all AS SELECT * FROM am_law_tsutatsu_all;
CREATE VIEW IF NOT EXISTS jc_law_tsutatsu_all_run_log AS SELECT * FROM am_law_tsutatsu_all_run_log;
CREATE VIEW IF NOT EXISTS jc_legal_chain AS SELECT * FROM am_legal_chain;
CREATE VIEW IF NOT EXISTS jc_legal_chain_run_log AS SELECT * FROM am_legal_chain_run_log;
CREATE VIEW IF NOT EXISTS jc_narrative_customer_reports AS SELECT * FROM am_narrative_customer_reports;
CREATE VIEW IF NOT EXISTS jc_narrative_extracted_entities AS SELECT * FROM am_narrative_extracted_entities;
CREATE VIEW IF NOT EXISTS jc_narrative_quarantine AS SELECT * FROM am_narrative_quarantine;
CREATE VIEW IF NOT EXISTS jc_narrative_serve_log AS SELECT * FROM am_narrative_serve_log;
CREATE VIEW IF NOT EXISTS jc_nta_tsutatsu_extended AS SELECT * FROM am_nta_tsutatsu_extended;
CREATE VIEW IF NOT EXISTS jc_overseas_run_log AS SELECT * FROM am_overseas_run_log;
CREATE VIEW IF NOT EXISTS jc_pdf_report_generation_log AS SELECT * FROM am_pdf_report_generation_log;
CREATE VIEW IF NOT EXISTS jc_pdf_report_subscriptions AS SELECT * FROM am_pdf_report_subscriptions;
CREATE VIEW IF NOT EXISTS jc_personalization_refresh_log AS SELECT * FROM am_personalization_refresh_log;
CREATE VIEW IF NOT EXISTS jc_personalization_score AS SELECT * FROM am_personalization_score;
CREATE VIEW IF NOT EXISTS jc_portfolio_optimize AS SELECT * FROM am_portfolio_optimize;
CREATE VIEW IF NOT EXISTS jc_portfolio_optimize_refresh_log AS SELECT * FROM am_portfolio_optimize_refresh_log;
CREATE VIEW IF NOT EXISTS jc_program_adoption_stats AS SELECT * FROM am_program_adoption_stats;
CREATE VIEW IF NOT EXISTS jc_program_agriculture AS SELECT * FROM am_program_agriculture;
CREATE VIEW IF NOT EXISTS jc_program_agriculture_ingest_log AS SELECT * FROM am_program_agriculture_ingest_log;
CREATE VIEW IF NOT EXISTS jc_program_calendar_12mo AS SELECT * FROM am_program_calendar_12mo;
CREATE VIEW IF NOT EXISTS jc_program_combinations AS SELECT * FROM am_program_combinations;
CREATE VIEW IF NOT EXISTS jc_program_decision_layer AS SELECT * FROM am_program_decision_layer;
CREATE VIEW IF NOT EXISTS jc_program_documents AS SELECT * FROM am_program_documents;
CREATE VIEW IF NOT EXISTS jc_program_eligibility_history AS SELECT * FROM am_program_eligibility_history;
CREATE VIEW IF NOT EXISTS jc_program_eligibility_predicate AS SELECT * FROM am_program_eligibility_predicate;
CREATE VIEW IF NOT EXISTS jc_program_eligibility_predicate_json AS SELECT * FROM am_program_eligibility_predicate_json;
CREATE VIEW IF NOT EXISTS jc_program_narrative AS SELECT * FROM am_program_narrative;
CREATE VIEW IF NOT EXISTS jc_program_narrative_full AS SELECT * FROM am_program_narrative_full;
CREATE VIEW IF NOT EXISTS jc_program_overseas AS SELECT * FROM am_program_overseas;
CREATE VIEW IF NOT EXISTS jc_program_private_foundation AS SELECT * FROM am_program_private_foundation;
CREATE VIEW IF NOT EXISTS jc_program_private_foundation_ingest_log AS SELECT * FROM am_program_private_foundation_ingest_log;
CREATE VIEW IF NOT EXISTS jc_program_risk_4d AS SELECT * FROM am_program_risk_4d;
CREATE VIEW IF NOT EXISTS jc_program_sector_175_map AS SELECT * FROM am_program_sector_175_map;
CREATE VIEW IF NOT EXISTS jc_program_source_municipality_v2 AS SELECT * FROM am_program_source_municipality_v2;
CREATE VIEW IF NOT EXISTS jc_program_source_municipality_v2_run_log AS SELECT * FROM am_program_source_municipality_v2_run_log;
CREATE VIEW IF NOT EXISTS jc_program_substitute AS SELECT * FROM am_program_substitute;
CREATE VIEW IF NOT EXISTS jc_program_version AS SELECT * FROM am_program_version;
CREATE VIEW IF NOT EXISTS jc_pubcomment_engagement AS SELECT * FROM am_pubcomment_engagement;
CREATE VIEW IF NOT EXISTS jc_realtime_dispatch_history AS SELECT * FROM am_realtime_dispatch_history;
CREATE VIEW IF NOT EXISTS jc_realtime_subscribers AS SELECT * FROM am_realtime_subscribers;
CREATE VIEW IF NOT EXISTS jc_recommended_programs AS SELECT * FROM am_recommended_programs;
CREATE VIEW IF NOT EXISTS jc_region_program_density AS SELECT * FROM am_region_program_density;
CREATE VIEW IF NOT EXISTS jc_region_program_density_breakdown AS SELECT * FROM am_region_program_density_breakdown;
CREATE VIEW IF NOT EXISTS jc_state_checkpoint AS SELECT * FROM am_state_checkpoint;
CREATE VIEW IF NOT EXISTS jc_subsidy_30yr_forecast AS SELECT * FROM am_subsidy_30yr_forecast;
CREATE VIEW IF NOT EXISTS jc_subsidy_30yr_forecast_refresh_log AS SELECT * FROM am_subsidy_30yr_forecast_refresh_log;
CREATE VIEW IF NOT EXISTS jc_supplier_chain AS SELECT * FROM am_supplier_chain;
CREATE VIEW IF NOT EXISTS jc_tax_amendment_history AS SELECT * FROM am_tax_amendment_history;
CREATE VIEW IF NOT EXISTS jc_tax_treaty AS SELECT * FROM am_tax_treaty;
CREATE VIEW IF NOT EXISTS jc_temporal_correlation AS SELECT * FROM am_temporal_correlation;
CREATE VIEW IF NOT EXISTS jc_validation_result AS SELECT * FROM am_validation_result;
CREATE VIEW IF NOT EXISTS jc_validation_rule AS SELECT * FROM am_validation_rule;

COMMIT;
PRAGMA foreign_keys = ON;

-- end of 269_create_jpcite_views.sql
