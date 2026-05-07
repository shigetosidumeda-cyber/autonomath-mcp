# Migration Inventory

- generated_at: `2026-05-07T07:59:37+09:00`
- migrations_root: `/Users/shigetoumeda/jpcite/scripts/migrations`
- migration_files: `289`
- forward_files: `200`
- rollback_files: `88`
- rollback_pairs: `88`
- orphan_rollbacks: `0`
- forward_missing_rollback: `112`
- draft_files: `1`
- manual_files: `1`
- duplicate_forward_numeric_prefixes: `4`
- files_with_dangerous_sql_markers: `93`
- forward_files_with_dangerous_sql_markers: `10`
- unmarked_target_db_files: `49`

## Family Counts

| family | files |
|---|---:|
| numeric | 161 |
| wave24 | 128 |

## Target DB Counts

| target_db | files |
|---|---:|
| autonomath | 180 |
| jpintel | 53 |
| jpintel.db | 7 |
| unmarked | 49 |

## Duplicate Forward Numeric Prefixes

- `052`: `052_api_keys_subscription_status.sql`, `052_perf_indexes.sql`
- `067`: `067_dataset_versioning.sql`, `067_dataset_versioning_autonomath.sql`
- `074`: `074_programs_merged_from.sql`, `074_tier_x_exclusion_reason_classify.sql`
- `121`: `121_jpi_programs_subsidy_rate_text_column.sql`, `121_subsidy_rate_text_column.sql`

## Orphan Rollbacks

- none

## Manual And Draft Files

- `120_drop_dead_vec_unifts.sql` (manual)
- `006_adoption.sql.draft` (draft)

## Dangerous SQL Markers

| file | markers |
|---|---|
| `010_email_schedule_day0_day1.sql` | drop_table |
| `057_case_studies_fts.sql` | delete_from |
| `065_compat_matrix_uni_id_backfill.sql` | delete_from |
| `077_compat_matrix_quality.sql` | delete_from |
| `082_relation_density_expansion_rollback.sql` | drop_index, drop_column, delete_from |
| `083_tax_rulesets_v2_backfill.sql` | delete_from |
| `108_api_keys_id_unique_nonpartial.sql` | drop_index |
| `109_case_studies_fts_dedup.sql` | delete_from |
| `110_autonomath_drop_cross_pollution.sql` | drop_table |
| `120_drop_dead_vec_unifts.sql` | drop_table |
| `148_programs_jsic_majors_rollback.sql` | drop_index, drop_column |
| `150_am_amount_condition_quality_tier_rollback.sql` | drop_index, drop_column |
| `154_am_temporal_correlation_rollback.sql` | drop_table, drop_index |
| `155_am_geo_industry_density_rollback.sql` | drop_table, drop_index |
| `156_am_funding_stack_empirical_rollback.sql` | drop_table, drop_index |
| `158_am_entity_density_score_rollback.sql` | drop_table, drop_index |
| `159_am_id_bridge_rollback.sql` | drop_table, drop_index |
| `160_am_adoption_trend_monthly_rollback.sql` | drop_table, drop_index |
| `161_am_enforcement_anomaly_rollback.sql` | drop_table, drop_index |
| `162_am_entity_pagerank_rollback.sql` | drop_table, drop_index |
| `164_am_program_eligibility_predicate_rollback.sql` | drop_table, drop_index |
| `166_am_canonical_vec_tables_rollback.sql` | drop_table |
| `168_am_actionable_answer_cache_rollback.sql` | drop_table, drop_index |
| `169_am_actionable_qa_cache_rollback.sql` | drop_table, drop_index |
| `170_program_decision_layer_rollback.sql` | drop_table, drop_index |
| `171_corporate_risk_layer_rollback.sql` | drop_table, drop_index |
| `172_corpus_snapshot_rollback.sql` | drop_table, drop_index |
| `173_artifact_rollback.sql` | drop_table, drop_index |
| `174_source_document_rollback.sql` | drop_table, drop_index |
| `175_extracted_fact_rollback.sql` | drop_table, drop_index |
| `176_source_foundation_domain_tables_rollback.sql` | drop_table, drop_index |
| `wave24_105_audit_seal_key_version_rollback.sql` | drop_table, drop_index, drop_column |
| `wave24_106_am_amendment_snapshot_rebuild_rollback.sql` | drop_table, drop_index |
| `wave24_107_am_compat_matrix_visibility_rollback.sql` | drop_index, drop_column |
| `wave24_108_programs_source_verified_at_rollback.sql` | drop_index, drop_column |
| `wave24_109_am_amount_condition_is_authoritative_rollback.sql` | drop_index, drop_column |
| `wave24_110_am_entities_vec_v2_rollback.sql` | drop_table |
| `wave24_111_am_entity_monthly_snapshot_rollback.sql` | drop_table, drop_index |
| `wave24_112_am_region_extension_rollback.sql` | drop_table, drop_index, drop_column |
| `wave24_113a_programs_jsic_rollback.sql` | drop_index, drop_column |
| `wave24_113b_jpi_programs_jsic_rollback.sql` | drop_index, drop_column |
| `wave24_113c_autonomath_houjin_master_jsic_rollback.sql` | drop_index, drop_column |
| `wave24_126_am_recommended_programs_rollback.sql` | drop_table, drop_index |
| `wave24_127_am_program_combinations_rollback.sql` | drop_table, drop_index |
| `wave24_128_am_program_calendar_12mo_rollback.sql` | drop_table, drop_index |
| `wave24_129_am_enforcement_industry_risk_rollback.sql` | drop_table, drop_index |
| `wave24_130_am_case_study_similarity_rollback.sql` | drop_table, drop_index |
| `wave24_131_am_houjin_360_snapshot_rollback.sql` | drop_table, drop_index |
| `wave24_132_am_tax_amendment_history_rollback.sql` | drop_table, drop_index |
| `wave24_133_am_invoice_buyer_seller_graph_rollback.sql` | drop_table, drop_index |
| `wave24_134_am_capital_band_program_match_rollback.sql` | drop_table, drop_index |
| `wave24_135_am_program_adoption_stats_rollback.sql` | drop_table, drop_index |
| `wave24_136_am_program_narrative.sql` | delete_from |
| `wave24_136_am_program_narrative_rollback.sql` | drop_table, drop_index |
| `wave24_137_am_program_eligibility_predicate_rollback.sql` | drop_table, drop_index |
| `wave24_138_am_program_documents_rollback.sql` | drop_table, drop_index |
| `wave24_139_am_region_program_density_rollback.sql` | drop_table, drop_index |
| `wave24_140_am_narrative_extracted_entities_rollback.sql` | drop_table, drop_index |
| `wave24_141_am_narrative_quarantine_rollback.sql` | drop_table, drop_index, drop_column |
| `wave24_142_am_narrative_customer_reports_rollback.sql` | drop_table, drop_index |
| `wave24_143_customer_webhooks_test_hits_rollback.sql` | drop_table, drop_index |
| `wave24_145_am_data_quality_snapshot_rollback.sql` | drop_table, drop_index |
| `wave24_148_am_credit_pack_purchase_rollback.sql` | drop_table, drop_index |
| `wave24_149_am_program_narrative_full_rollback.sql` | drop_table, drop_index |
| `wave24_152_am_5hop_graph_rollback.sql` | drop_table, drop_index |
| `wave24_153_am_entity_appearance_count_rollback.sql` | drop_table, drop_index |
| `wave24_155_am_geo_industry_density_rollback.sql` | delete_from |
| `wave24_157_am_adopted_company_features_rollback.sql` | drop_table, drop_index |
| `wave24_163_am_citation_network_rollback.sql` | drop_table, drop_index |
| `wave24_164_gbiz_v2_mirror_tables_rollback.sql` | drop_table, drop_index |
| `wave24_166_credit_pack_reservation_rollback.sql` | drop_table, drop_index |
| `wave24_168_entity_resolution_bridge_v2_rollback.sql` | drop_table, drop_index |
| `wave24_170_source_catalog_rollback.sql` | drop_table |
| `wave24_171_source_freshness_ledger_rollback.sql` | drop_table |
| `wave24_172_cross_source_signal_layer_rollback.sql` | drop_table, delete_from |
| `wave24_173_invoice_status_history_rollback.sql` | drop_table, drop_index |
| `wave24_174_enforcement_permit_event_layer_rollback.sql` | drop_table, drop_index |
| `wave24_175_public_funding_ledger_rollback.sql` | drop_table, drop_index |
| `wave24_176_edinet_filing_signal_layer_rollback.sql` | drop_table |
| `wave24_177_regulatory_citation_graph_rollback.sql` | drop_table |
| `wave24_178_document_requirement_layer_rollback.sql` | drop_table |
| `wave24_180_time_machine_index_rollback.sql` | drop_index |
| `wave24_181_verify_log_rollback.sql` | drop_table, drop_index |
| `wave24_183_citation_log_rollback.sql` | drop_table, drop_index |
| `wave24_184_contribution_queue_rollback.sql` | drop_table, drop_index |
| `wave24_185_kokkai_utterance_rollback.sql` | drop_table, drop_index |
| `wave24_186_industry_journal_mention_rollback.sql` | drop_table, drop_index |
| `wave24_187_brand_mention_rollback.sql` | drop_table, drop_index |
| `wave24_188_evolution_dashboard_snapshot_rollback.sql` | drop_table, drop_index |
| `wave24_189_citation_sample_rollback.sql` | drop_table, drop_index |
| `wave24_190_restore_drill_log_rollback.sql` | drop_table, drop_index |
| `wave24_191_municipality_subsidy_rollback.sql` | drop_table, drop_index |
| `wave24_192_pubcomment_announcement_rollback.sql` | drop_table, drop_index |

## Unmarked Target DB Files

- `001_lineage.sql`
- `002_subscribers.sql`
- `003_feedback.sql`
- `005_usage_params.sql`
- `006_adoption.sql.draft`
- `008_email_schedule.sql`
- `009_email_schedule_retry.sql`
- `010_email_schedule_day0_day1.sql`
- `011_external_data_tables.sql`
- `012_case_law.sql`
- `013_loan_risk_structure.sql`
- `014_business_intelligence_layer.sql`
- `015_laws.sql`
- `016_court_decisions.sql`
- `017_bids.sql`
- `018_tax_rulesets.sql`
- `019_invoice_registrants.sql`
- `020_compliance_subscribers.sql`
- `021_line_users.sql`
- `022_widget_keys.sql`
- `023_device_codes.sql`
- `024_advisors.sql`
- `037_customer_self_cap.sql`
- `038_alert_subscriptions.sql`
- `039_healthcare_schema.sql`
- `041_testimonials.sql`
- `042_real_estate_schema.sql`
- `043_l4_cache.sql`
- `044_precompute_tables.sql`
- `045_precompute_more.sql`
- `048_pc_program_health.sql`
- `050_tier_x_quarantine_fix.sql`
- `051_exclusion_rules_uid_keys.sql`
- `052_api_keys_subscription_status.sql`
- `053_stripe_webhook_events.sql`
- `054_usage_events_stripe_reconciliation.sql`
- `056_search_perf_indexes.sql`
- `057_case_studies_fts.sql`
- `058_audit_log.sql`
- `059_postmark_webhook_events.sql`
- `060_bg_task_queue.sql`
- `061_telemetry_columns.sql`
- `062_empty_search_log.sql`
- `063_advisory_locks.sql`
- `073_api_keys_bcrypt_dual_path.sql`
- `074_tier_x_exclusion_reason_classify.sql`
- `102_cron_runs_heartbeat.sql`
- `106_line_message_log.sql`
- `122_usage_events_billing_idempotency.sql`

## Review Rules

1. Do not edit applied migrations; add a new migration instead.
2. Keep rollback files paired with the exact forward migration name.
3. Treat duplicate numeric prefixes and wave-prefixed migrations as release-order review items.
4. Review `delete_from`, `drop_*`, and `truncate` markers before any production run.
5. Treat `unmarked` target_db files as DB-boundary review items.
