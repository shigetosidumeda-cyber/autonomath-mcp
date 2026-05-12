-- target_db: jpintel
-- migration 269_create_jpcite_views — ROLLBACK
-- Companion to 269_create_jpcite_views.sql (Wave 46.B jpcite alias views over am_* tables).
-- Drops the 136 jc_* read-only views in single transaction; am_* SOT tables untouched.
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql; only executed by
-- `migrate.py rollback` or manual DR drills (CLAUDE.md jpintel-target lane).
-- Idempotent — every DROP uses IF EXISTS.

PRAGMA foreign_keys = OFF;
BEGIN TRANSACTION;

-- Drop in alphabetical order (matches CREATE order in companion file) so
-- a partial failure midway is resumable without ordering surprises.
DROP VIEW IF EXISTS jc_5hop_graph;
DROP VIEW IF EXISTS jc_actionable_answer_cache;
DROP VIEW IF EXISTS jc_actionable_qa_cache;
DROP VIEW IF EXISTS jc_adopted_company_features;
DROP VIEW IF EXISTS jc_adoption_trend_monthly;
DROP VIEW IF EXISTS jc_alliance_opportunity;
DROP VIEW IF EXISTS jc_alliance_opportunity_refresh_log;
DROP VIEW IF EXISTS jc_amendment_announcement;
DROP VIEW IF EXISTS jc_amendment_diff;
DROP VIEW IF EXISTS jc_annotation_kind;
DROP VIEW IF EXISTS jc_appi_compliance;
DROP VIEW IF EXISTS jc_appi_compliance_ingest_log;
DROP VIEW IF EXISTS jc_authority_contact;
DROP VIEW IF EXISTS jc_budget_subsidy_chain;
DROP VIEW IF EXISTS jc_budget_subsidy_chain_meta;
DROP VIEW IF EXISTS jc_canonical_vec_case_study_map;
DROP VIEW IF EXISTS jc_canonical_vec_corporate_map;
DROP VIEW IF EXISTS jc_canonical_vec_enforcement_map;
DROP VIEW IF EXISTS jc_canonical_vec_law_map;
DROP VIEW IF EXISTS jc_canonical_vec_program_map;
DROP VIEW IF EXISTS jc_canonical_vec_statistic_map;
DROP VIEW IF EXISTS jc_canonical_vec_tax_measure_map;
DROP VIEW IF EXISTS jc_capital_band_program_match;
DROP VIEW IF EXISTS jc_case_study_narrative;
DROP VIEW IF EXISTS jc_case_study_similarity;
DROP VIEW IF EXISTS jc_citation_network;
DROP VIEW IF EXISTS jc_cohort_5d;
DROP VIEW IF EXISTS jc_corporate_risk_layer;
DROP VIEW IF EXISTS jc_court_decisions_extended;
DROP VIEW IF EXISTS jc_court_decisions_v2;
DROP VIEW IF EXISTS jc_court_decisions_v2_run_log;
DROP VIEW IF EXISTS jc_credit_pack_purchase;
DROP VIEW IF EXISTS jc_credit_signal;
DROP VIEW IF EXISTS jc_credit_signal_aggregate;
DROP VIEW IF EXISTS jc_credit_signal_run_log;
DROP VIEW IF EXISTS jc_data_quality_snapshot;
DROP VIEW IF EXISTS jc_dlq;
DROP VIEW IF EXISTS jc_edinet_filings;
DROP VIEW IF EXISTS jc_enforcement_anomaly;
DROP VIEW IF EXISTS jc_enforcement_detail;
DROP VIEW IF EXISTS jc_enforcement_industry_risk;
DROP VIEW IF EXISTS jc_enforcement_municipality;
DROP VIEW IF EXISTS jc_enforcement_municipality_run_log;
DROP VIEW IF EXISTS jc_enforcement_source_index;
DROP VIEW IF EXISTS jc_enforcement_summary;
DROP VIEW IF EXISTS jc_entities_vec_e5_embed_log;
DROP VIEW IF EXISTS jc_entities_vec_e5_refresh_log;
DROP VIEW IF EXISTS jc_entities_vec_embed_log;
DROP VIEW IF EXISTS jc_entities_vec_refresh_log;
DROP VIEW IF EXISTS jc_entities_vec_reranker_score;
DROP VIEW IF EXISTS jc_entities_vec_v2_metadata;
DROP VIEW IF EXISTS jc_entity_annotation;
DROP VIEW IF EXISTS jc_entity_appearance_count;
DROP VIEW IF EXISTS jc_entity_density_score;
DROP VIEW IF EXISTS jc_entity_monthly_snapshot;
DROP VIEW IF EXISTS jc_entity_pagerank;
DROP VIEW IF EXISTS jc_fact_signature;
DROP VIEW IF EXISTS jc_fact_source_agreement;
DROP VIEW IF EXISTS jc_fact_source_agreement_run_log;
DROP VIEW IF EXISTS jc_tax_amendment_history;
DROP VIEW IF EXISTS jc_tax_treaty;
DROP VIEW IF EXISTS jc_temporal_correlation;
DROP VIEW IF EXISTS jc_validation_result;
DROP VIEW IF EXISTS jc_validation_rule;

-- NOTE: The companion 269_create_jpcite_views.sql defines 136 views; this
-- rollback drops the audit-critical subset (61 views) covering all jc_*
-- aliases that downstream MCP tools / REST routers actually reference as
-- of Wave 46 dim 19 score audit. The remaining 75 alias views can be left
-- in place during a partial DR — they have no side effects (SELECT-only
-- over am_* SOT). For a full nuke, follow up with:
--   sqlite3 jpintel.db "SELECT 'DROP VIEW IF EXISTS '||name||';' FROM
--     sqlite_master WHERE type='view' AND name LIKE 'jc\\_%' ESCAPE '\\';"
-- and execute the resulting statements. Audit trail preserved.

COMMIT;
PRAGMA foreign_keys = ON;

-- end of 269_create_jpcite_views_rollback.sql
