# MIGRATION_INDEX.md

Authoritative read-only audit of `scripts/migrations/`. Generated 2026-05-05.
Source dir: `scripts/migrations/` — 161 forward + 51 rollback companions.

## Counts

- Forward migrations: **161**
- Rollback companions: **51** of 161 (110 have no rollback)
- Idempotent: **153** / non-idempotent suspects: **8**
- target_db split:
  - **autonomath**: 72
  - **(no header → defaults to jpintel)**: 49
  - **jpintel**: 40

Migration runner conventions (see `scripts/migrate.py` + `entrypoint.sh`):
- `_rollback.sql` files are **never** applied by `migrate.py` — manual only.
- Files marked `-- target_db: autonomath` are skipped by `migrate.py` against jpintel.db (recorded as applied) and applied to autonomath.db by `entrypoint.sh §4` self-heal loop.
- Files without `target_db` header default to jpintel.
- `migrate.py` records `INSERT INTO schema_migrations(id, checksum, applied_at)`; checksum mismatch on a re-run is detected.

## Numbering gaps (first-cycle 001..163, excluding `wave24_*`)

Missing numbers: `4, 6, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 40, 84, 93, 94, 95, 100, 117, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 149, 152, 153, 157`

Notes per CLAUDE.md / wave logs:
- 004 / 006 / 025-036 / 040 — never landed (planned but not used or reserved during agent merges).
- 084 / 093 / 094 / 095 / 100 — intentional reservations during Wave 21-22 parallel-agent merge.
- 117 / 127-145 / 149 / 152 / 153 / 156 / 157 / 158 / 161-162 — first-cycle slots; later overwritten by `wave24_NNN_*` companions which use the same NNN prefix.
- `006_adoption.sql.draft` — never enabled; `.draft` extension excludes it from the runner glob.
- `052_*` and `074_*` and `121_*` and `155_*` and `156_*` and `158_*` and `159_*` and `160_*` and `161_*` and `162_*` — number collisions exist between first-cycle and `wave24_*`. Runner sorts lexicographically so wave24 lands AFTER same-number first-cycle file (`056_acceptance...` < `wave24_056_*`).

## Forward migrations (numeric order)

| # | file | target | ops | tables (create / alter / drop) | idem | rb |
| - | - | - | - | - | - | - |
| 001 | `001_lineage.sql` | JPI* | ALT/INDEX | - / programs / - | Y | - |
| 002 | `002_subscribers.sql` | JPI* | INDEX/TABLE | subscribers / - / - | Y | - |
| 003 | `003_feedback.sql` | JPI* | INDEX/TABLE | feedback / - / - | Y | - |
| 005 | `005_usage_params.sql` | JPI* | ALT/INDEX | - / usage_events / - | Y | - |
| 007 | `007_anon_rate_limit.sql` | JPI* | INDEX/TABLE | anon_rate_limit / - / - | Y | - |
| 008 | `008_email_schedule.sql` | JPI* | INDEX/TABLE | email_schedule / - / - | Y | - |
| 009 | `009_email_schedule_retry.sql` | JPI* | ALT | - / email_schedule / - | Y | - |
| 010 | `010_email_schedule_day0_day1.sql` | JPI* | ALT/INDEX/TABLE/D TABLE | email_schedule_new / email_schedule_new / email_schedule | N | - |
| 011 | `011_external_data_tables.sql` | JPI* | ALT/INDEX/TABLE | case_studies,enforcement_cases,loan_programs,new_program_candidates,program_documents / exclusion_rules / - | Y | - |
| 012 | `012_case_law.sql` | JPI* | INDEX/TABLE | case_law / - / - | Y | - |
| 013 | `013_loan_risk_structure.sql` | JPI* | ALT/INDEX | - / loan_programs / - | Y | - |
| 014 | `014_business_intelligence_layer.sql` | JPI* | INDEX/TABLE/VTABLE/UPDATE | adoption_fts,adoption_records,houjin_master,houjin_master_fts,industry_program_density,industry_stats,minis... | Y | - |
| 015 | `015_laws.sql` | JPI* | ALT/INDEX/TABLE/VTABLE | laws,laws_fts,program_law_refs / - / - | Y | - |
| 016 | `016_court_decisions.sql` | JPI* | INDEX/TABLE/VIEW/VTABLE/D VIEW | court_decisions,court_decisions_fts,enforcement_decision_refs v:case_law_v2 / - / - | N | - |
| 017 | `017_bids.sql` | JPI* | INDEX/TABLE/VTABLE | bids,bids_fts / - / - | Y | - |
| 018 | `018_tax_rulesets.sql` | JPI* | INDEX/TABLE/VTABLE | tax_rulesets,tax_rulesets_fts / - / - | Y | - |
| 019 | `019_invoice_registrants.sql` | JPI* | INDEX/TABLE/UPDATE | invoice_registrants / - / - | Y | - |
| 020 | `020_compliance_subscribers.sql` | JPI* | INDEX/TABLE/UPDATE | compliance_notification_log,compliance_subscribers / - / - | Y | - |
| 021 | `021_line_users.sql` | JPI* | INDEX/TABLE | line_users / - / - | Y | - |
| 022 | `022_widget_keys.sql` | JPI* | INDEX/TABLE | widget_keys / - / - | Y | - |
| 023 | `023_device_codes.sql` | JPI* | INDEX/TABLE | device_codes / - / - | Y | - |
| 024 | `024_advisors.sql` | JPI* | INDEX/TABLE | advisor_referrals,advisors / - / - | Y | - |
| 037 | `037_customer_self_cap.sql` | JPI* | ALT | - / api_keys / - | Y | - |
| 038 | `038_alert_subscriptions.sql` | JPI* | INDEX/TABLE | alert_subscriptions / - / - | Y | - |
| 039 | `039_healthcare_schema.sql` | JPI* | INDEX/TABLE | care_subsidies,medical_institutions / - / - | Y | - |
| 041 | `041_testimonials.sql` | JPI* | INDEX/TABLE | testimonials / - / - | Y | - |
| 042 | `042_real_estate_schema.sql` | JPI* | INDEX/TABLE | real_estate_programs,zoning_overlays / - / - | Y | - |
| 043 | `043_l4_cache.sql` | JPI* | INDEX/TABLE | l4_query_cache / - / - | Y | - |
| 044 | `044_precompute_tables.sql` | JPI* | INDEX/TABLE | pc_acceptance_stats_by_program,pc_authority_to_programs,pc_certification_by_subject,pc_combo_pairs,pc_enfor... | Y | - |
| 045 | `045_precompute_more.sql` | JPI* | INDEX/TABLE | pc_acceptance_rate_by_authority,pc_amendment_recent_by_law,pc_amendment_severity_distribution,pc_amount_max... | Y | - |
| 046 | `046_annotation_layer.sql` | AM | INDEX/TABLE | am_annotation_kind,am_entity_annotation / - / - | Y | - |
| 047 | `047_validation_layer.sql` | AM | INDEX/TABLE | am_validation_result,am_validation_rule / - / - | Y | - |
| 048 | `048_pc_program_health.sql` | JPI* | INDEX/TABLE | jpi_pc_program_health / - / - | Y | - |
| 049 | `049_provenance_strengthen.sql` | AM | ALT/INDEX/TRIGGER/UPDATE | - / am_entity_facts,am_source,jpi_feedback / - | Y | - |
| 050 | `050_tier_x_quarantine_fix.sql` | JPI* | UPDATE | - / - / - | Y | - |
| 051 | `051_exclusion_rules_uid_keys.sql` | JPI* | ALT/INDEX/UPDATE | - / exclusion_rules / - | Y | - |
| 052 | `052_api_keys_subscription_status.sql` | JPI* | ALT/INDEX/TABLE/D TABLE | - / api_keys / - | N | - |
| 052 | `052_perf_indexes.sql` | AM | INDEX | - / - / - | Y | - |
| 053 | `053_stripe_webhook_events.sql` | JPI* | INDEX/TABLE/D INDEX/D TABLE | stripe_webhook_events / - / - | Y | - |
| 054 | `054_usage_events_stripe_reconciliation.sql` | JPI* | ALT/INDEX | - / usage_events / - | Y | - |
| 055 | `055_acceptance_stats_index.sql` | AM | INDEX | - / - / - | Y | - |
| 056 | `056_search_perf_indexes.sql` | JPI* | INDEX | - / - / - | Y | - |
| 057 | `057_case_studies_fts.sql` | JPI* | TRIGGER/VTABLE/DELETE/INS/UPDATE | case_studies_fts / - / - | Y | - |
| 058 | `058_audit_log.sql` | JPI* | INDEX/TABLE | audit_log / - / - | Y | - |
| 059 | `059_postmark_webhook_events.sql` | JPI* | INDEX/TABLE | postmark_webhook_events / - / - | Y | - |
| 060 | `060_bg_task_queue.sql` | JPI* | INDEX/TABLE | bg_task_queue / - / - | Y | - |
| 061 | `061_telemetry_columns.sql` | JPI* | ALT/INDEX | - / usage_events / - | Y | - |
| 062 | `062_empty_search_log.sql` | JPI* | INDEX/TABLE | empty_search_log / - / - | Y | - |
| 063 | `063_advisory_locks.sql` | JPI* | INDEX/TABLE/UPDATE | advisory_locks / - / - | Y | - |
| 064 | `064_unified_rule_view.sql` | AM | VIEW/D VIEW | -v:am_unified_rule / - / - | Y | - |
| 065 | `065_compat_matrix_uni_id_backfill.sql` | AM | TABLE/DELETE/INS/UPDATE | jpi_exclusion_rules_pre052_snapshot / - / - | Y | Y |
| 066 | `066_appi_disclosure_requests.sql` | JPI | INDEX/TABLE/D INDEX/D TABLE | appi_disclosure_requests / - / - | Y | - |
| 067 | `067_dataset_versioning.sql` | JPI | ALT/INDEX/D INDEX/UPDATE | - / bids,case_studies,court_decisions,enforcement_cases,laws,loan_programs,programs,tax_rulesets / - | Y | - |
| 067 | `067_dataset_versioning_autonomath.sql` | AM | ALT/INDEX/UPDATE | - / am_entities,am_entity_facts / - | Y | - |
| 068 | `068_appi_deletion_requests.sql` | JPI | INDEX/TABLE/D INDEX/D TABLE | appi_deletion_requests / - / - | Y | - |
| 069 | `069_uncertainty_view.sql` | AM | VIEW/D VIEW | -v:am_uncertainty_view / - / - | Y | - |
| 070 | `070_programs_active_at_v2.sql` | AM | VIEW/D VIEW | -v:programs_active_at_v2 / - / - | Y | - |
| 071 | `071_stripe_edge_cases.sql` | JPI | INDEX/TABLE/D INDEX/D TABLE | refund_requests,stripe_tax_cache / - / - | Y | - |
| 072 | `072_email_unsubscribes.sql` | JPI | TABLE/D TABLE | email_unsubscribes / - / - | Y | - |
| 073 | `073_api_keys_bcrypt_dual_path.sql` | JPI* | ALT | - / api_keys / - | Y | - |
| 074 | `074_programs_merged_from.sql` | JPI | ALT | - / programs / - | Y | - |
| 074 | `074_tier_x_exclusion_reason_classify.sql` | JPI* | ALT/TABLE/TRIGGER/UPDATE | exclusion_reason_codes / programs / - | Y | - |
| 075 | `075_am_amendment_diff.sql` | AM | INDEX/TABLE | am_amendment_diff / - / - | Y | - |
| 076 | `076_trial_signup.sql` | JPI | ALT/INDEX/TABLE | trial_signups / api_keys / - | Y | - |
| 077 | `077_compat_matrix_quality.sql` | AM | ALT/INDEX/DELETE/UPDATE | - / am_compat_matrix / - | Y | - |
| 078 | `078_amount_condition_quarantine.sql` | AM | ALT/INDEX/UPDATE | - / am_amount_condition / - | Y | - |
| 079 | `079_saved_searches.sql` | JPI | INDEX/TABLE/D TABLE | saved_searches / - / - | N | - |
| 080 | `080_customer_webhooks.sql` | JPI | INDEX/TABLE | customer_webhooks,webhook_deliveries / - / - | Y | - |
| 081 | `081_invoice_registrants_bulk_index.sql` | JPI | INDEX | - / - / - | Y | - |
| 082 | `082_relation_density_expansion.sql` | AM | ALT/INDEX/DELETE | - / am_relation / - | Y | Y |
| 083 | `083_tax_rulesets_v2_backfill.sql` | JPI | DELETE/INS | - / - / - | Y | - |
| 085 | `085_usage_events_client_tag.sql` | JPI | ALT/INDEX | - / usage_events / - | Y | - |
| 086 | `086_api_keys_parent_child.sql` | JPI | ALT/INDEX/UPDATE | - / api_keys / - | Y | - |
| 087 | `087_idempotency_cache.sql` | JPI | ALT/INDEX/TABLE | am_idempotency_cache / api_keys / - | Y | - |
| 088 | `088_houjin_watch.sql` | JPI | INDEX/TABLE | customer_watches / - / - | Y | - |
| 089 | `089_audit_seal_table.sql` | JPI | INDEX/TABLE | audit_seals / - / - | Y | - |
| 090 | `090_law_article_body_en.sql` | AM | ALT/INDEX/UPDATE | - / am_alias,am_law_article / - | Y | - |
| 091 | `091_tax_treaty.sql` | AM | INDEX/TABLE | am_tax_treaty / - / - | Y | - |
| 092 | `092_foreign_capital_eligibility.sql` | AM | ALT/INDEX/UPDATE | - / am_subsidy_rule / - | Y | - |
| 096 | `096_client_profiles.sql` | JPI | INDEX/TABLE/D TABLE/UPDATE | client_profiles / - / - | N | - |
| 097 | `097_saved_searches_profile_ids.sql` | JPI | ALT/INDEX/TABLE/INS | - / saved_searches / - | Y | - |
| 098 | `098_program_post_award_calendar.sql` | JPI | INDEX/TABLE/D TABLE | customer_intentions,program_post_award_calendar / - / - | N | - |
| 099 | `099_recurring_engagement.sql` | JPI | ALT/INDEX/TABLE | course_subscriptions / saved_searches / - | Y | - |
| 101 | `101_trust_infrastructure.sql` | AM | ALT/INDEX/TABLE/UPDATE | audit_log_section52,correction_log,correction_submissions,dead_url_alerts,quality_metrics_daily,reproducibi... | Y | - |
| 102 | `102_cron_runs_heartbeat.sql` | JPI* | INDEX/TABLE | cron_runs / - / - | Y | - |
| 103 | `103_nta_corpus.sql` | AM | INDEX/TABLE/TRIGGER/VTABLE/INS/UPDATE | nta_bunsho_kaitou,nta_bunsho_kaitou_fts,nta_saiketsu,nta_saiketsu_fts,nta_shitsugi,nta_shitsugi_fts,nta_tsu... | Y | - |
| 104 | `104_wave22_dd_question_templates.sql` | AM | INDEX/TABLE/VIEW | dd_question_templates v:v_dd_question_template_summary / - / - | Y | - |
| 105 | `105_integrations.sql` | JPI | ALT/INDEX/TABLE | integration_accounts,integration_sync_log / saved_searches / - | Y | - |
| 106 | `106_line_message_log.sql` | JPI* | INDEX/TABLE | line_message_log / - / - | Y | - |
| 107 | `107_cross_source_baseline_state.sql` | AM | TABLE | cross_source_baseline_state / - / - | Y | - |
| 108 | `108_api_keys_id_unique_nonpartial.sql` | JPI | D INDEX/INS/UPDATE | - / - / - | N | - |
| 109 | `109_case_studies_fts_dedup.sql` | JPI | DELETE/INS | - / - / - | N | - |
| 110 | `110_autonomath_drop_cross_pollution.sql` | AM | TABLE/D TABLE | - / - / programs,programs_fts,programs_fts_config,programs_fts_content,programs_fts_data,programs_fts_docsi... | Y | - |
| 111 | `111_analytics_events.sql` | JPI | INDEX/TABLE | analytics_events / - / - | Y | - |
| 112 | `112_alias_candidates_queue.sql` | JPI | INDEX/TABLE | alias_candidates_queue / - / - | Y | - |
| 113 | `113_weekly_digest_state.sql` | JPI | ALT/INDEX | - / analytics_events,saved_searches / - | Y | - |
| 114 | `114_adoption_program_join.sql` | AM | ALT/INDEX | - / jpi_adoption_records / - | Y | - |
| 115 | `115_source_manifest_view.sql` | AM | VIEW/D VIEW | -v:v_program_source_manifest / - / - | Y | - |
| 116 | `116_usage_events_client_tag_index.sql` | JPI | ALT/INDEX/D INDEX | - / usage_events / - | Y | - |
| 118 | `118_programs_source_url_status.sql` | JPI | ALT/INDEX | - / programs / - | Y | - |
| 119 | `119_audit_seal_seal_id_columns.sql` | JPI | ALT/INDEX | - / audit_seals / - | Y | - |
| 120 | `120_drop_dead_vec_unifts.sql` | AM | D TABLE | - / - / am_entities_fts_uni,am_entities_fts_uni_config,am_entities_fts_uni_content,am_entities_fts_uni_data... | Y | - |
| 121 | `121_jpi_programs_subsidy_rate_text_column.sql` | AM | ALT | - / jpi_programs / - | Y | - |
| 121 | `121_subsidy_rate_text_column.sql` | JPI | ALT | - / programs / - | Y | - |
| 122 | `122_usage_events_billing_idempotency.sql` | JPI* | ALT | - / usage_events / - | Y | - |
| 123 | `123_funnel_events.sql` | JPI | ALT/INDEX/TABLE | funnel_events / analytics_events / - | Y | - |
| 124 | `124_src_attribution.sql` | JPI | ALT/INDEX | - / analytics_events,funnel_events / - | Y | - |
| 125 | `125_tax_treaty_backfill_30_countries.sql` | AM | UPDATE | - / - / - | Y | - |
| 126 | `126_citation_verification.sql` | JPI | ALT/INDEX/TABLE | citation_verification / - / - | Y | - |
| 146 | `146_audit_merkle_anchor.sql` | AM | INDEX/TABLE | audit_merkle_anchor,audit_merkle_leaves / - / - | Y | - |
| 147 | `147_am_entities_vec_tables.sql` | AM | VTABLE/INS | am_entities_vec_A,am_entities_vec_C,am_entities_vec_J,am_entities_vec_K,am_entities_vec_L,am_entities_vec_S... | Y | - |
| 148 | `148_programs_jsic_majors.sql` | JPI | ALT/INDEX/UPDATE | - / programs / - | Y | Y |
| 150 | `150_am_amount_condition_quality_tier.sql` | AM | ALT/INDEX/UPDATE | - / am_amount_condition / - | Y | Y |
| 151 | `151_programs_cross_source_verified.sql` | JPI | ALT/INDEX/UPDATE | - / programs / - | Y | - |
| 154 | `154_am_temporal_correlation.sql` | AM | INDEX/TABLE/DELETE | am_temporal_correlation / - / - | Y | Y |
| 155 | `155_am_geo_industry_density.sql` | AM | INDEX/TABLE/INS | am_geo_industry_density / - / - | Y | Y |
| 156 | `156_am_funding_stack_empirical.sql` | AM | INDEX/TABLE/INS | am_funding_stack_empirical / - / - | Y | Y |
| 158 | `158_am_entity_density_score.sql` | AM | INDEX/TABLE/INS | am_entity_density_score / - / - | Y | Y |
| 159 | `159_am_id_bridge.sql` | AM | INDEX/TABLE/INS | am_id_bridge / - / - | Y | Y |
| 160 | `160_am_adoption_trend_monthly.sql` | AM | INDEX/TABLE/DELETE | am_adoption_trend_monthly / - / - | Y | Y |
| 161 | `161_am_enforcement_anomaly.sql` | AM | INDEX/TABLE/INS | am_enforcement_anomaly / - / - | Y | Y |
| 162 | `162_am_entity_pagerank.sql` | AM | INDEX/TABLE/INS | am_entity_pagerank / - / - | Y | Y |
| 105 | `wave24_105_audit_seal_key_version.sql` | JPI | ALT/INDEX/TABLE | audit_seal_keys / audit_seals / - | Y | Y |
| 106 | `wave24_106_amendment_snapshot_rebuild.sql` | AM | ALT/INDEX/TABLE/UPDATE | am_program_eligibility_history / am_amendment_snapshot / - | Y | Y |
| 107 | `wave24_107_am_compat_matrix_visibility.sql` | AM | ALT/INDEX/UPDATE | - / am_compat_matrix / - | Y | Y |
| 108 | `wave24_108_programs_source_verified_at.sql` | JPI | ALT/INDEX | - / programs / - | Y | Y |
| 109 | `wave24_109_am_amount_condition_is_authoritative.sql` | AM | ALT/INDEX/UPDATE | - / am_amount_condition / - | Y | Y |
| 110 | `wave24_110_am_entities_vec_v2.sql` | AM | TABLE/VTABLE | am_entities_vec_v2,am_entities_vec_v2_metadata / - / - | Y | Y |
| 110a | `wave24_110a_tier_c_cleanup.sql` | JPI | UPDATE | - / - / - | Y | Y |
| 111 | `wave24_111_am_entity_monthly_snapshot.sql` | AM | INDEX/TABLE | am_entity_monthly_snapshot / - / - | Y | Y |
| 112 | `wave24_112_am_region_extension.sql` | AM | ALT/INDEX/TABLE/INS | am_region_program_density / am_region / - | Y | Y |
| 113a | `wave24_113a_programs_jsic.sql` | JPI | ALT/INDEX/UPDATE | - / houjin_master,programs / - | Y | Y |
| 113b | `wave24_113b_jpi_programs_jsic.sql` | AM | ALT/INDEX | - / jpi_programs / - | Y | Y |
| 113c | `wave24_113c_autonomath_houjin_master_jsic.sql` | AM | ALT/INDEX | - / houjin_master / - | Y | Y |
| 126 | `wave24_126_am_recommended_programs.sql` | AM | INDEX/TABLE/INS | am_recommended_programs / - / - | Y | Y |
| 127 | `wave24_127_am_program_combinations.sql` | AM | INDEX/TABLE | am_program_combinations / - / - | Y | Y |
| 128 | `wave24_128_am_program_calendar_12mo.sql` | AM | INDEX/TABLE/INS | am_program_calendar_12mo / - / - | Y | Y |
| 129 | `wave24_129_am_enforcement_industry_risk.sql` | AM | INDEX/TABLE/INS | am_enforcement_industry_risk / - / - | Y | Y |
| 130 | `wave24_130_am_case_study_similarity.sql` | AM | INDEX/TABLE | am_case_study_similarity / - / - | Y | Y |
| 131 | `wave24_131_am_houjin_360_snapshot.sql` | AM | INDEX/TABLE/INS | am_houjin_360_snapshot / - / - | Y | Y |
| 132 | `wave24_132_am_tax_amendment_history.sql` | AM | INDEX/TABLE/INS | am_tax_amendment_history / - / - | Y | Y |
| 133 | `wave24_133_am_invoice_buyer_seller_graph.sql` | AM | INDEX/TABLE/INS | am_invoice_buyer_seller_graph / - / - | Y | Y |
| 134 | `wave24_134_am_capital_band_program_match.sql` | AM | INDEX/TABLE/INS | am_capital_band_program_match / - / - | Y | Y |
| 135 | `wave24_135_am_program_adoption_stats.sql` | AM | INDEX/TABLE/INS | am_program_adoption_stats / - / - | Y | Y |
| 136 | `wave24_136_am_program_narrative.sql` | AM | INDEX/TABLE/TRIGGER/VTABLE/DELETE/INS/UPDATE | am_program_narrative,am_program_narrative_fts / - / - | Y | Y |
| 137 | `wave24_137_am_program_eligibility_predicate.sql` | AM | INDEX/TABLE/VIEW | am_program_eligibility_predicate v:v_am_program_required_predicates / - / - | Y | Y |
| 138 | `wave24_138_am_program_documents.sql` | AM | INDEX/TABLE/INS | am_program_documents / - / - | Y | Y |
| 139 | `wave24_139_am_region_program_density.sql` | AM | INDEX/TABLE/INS | am_region_program_density,am_region_program_density_breakdown / - / - | Y | Y |
| 140 | `wave24_140_am_narrative_extracted_entities.sql` | AM | INDEX/TABLE/INS | am_narrative_extracted_entities / - / - | Y | Y |
| 141 | `wave24_141_am_narrative_quarantine.sql` | AM | ALT/INDEX/TABLE/INS/UPDATE | am_case_study_narrative,am_enforcement_summary,am_houjin_360_narrative,am_law_article_summary,am_narrative_... | Y | Y |
| 142 | `wave24_142_am_narrative_customer_reports.sql` | AM | INDEX/TABLE | am_narrative_customer_reports,am_narrative_serve_log / - / - | Y | Y |
| 143 | `wave24_143_customer_webhooks_test_hits.sql` | JPI | INDEX/TABLE | customer_webhooks_test_hits / - / - | Y | Y |
| 144 | `wave24_144_narrative_quality_kpi_view.sql` | AM | VIEW/D VIEW | -v:am_narrative_quality_kpi / - / - | Y | Y |
| 145 | `wave24_145_am_data_quality_snapshot.sql` | AM | INDEX/TABLE | am_data_quality_snapshot / - / - | Y | Y |
| 148 | `wave24_148_am_credit_pack_purchase.sql` | AM | INDEX/TABLE/UPDATE | am_credit_pack_purchase / - / - | Y | Y |
| 149 | `wave24_149_am_program_narrative_full.sql` | AM | INDEX/TABLE | am_program_narrative_full / - / - | Y | Y |
| 152 | `wave24_152_am_5hop_graph.sql` | AM | INDEX/TABLE | am_5hop_graph / - / - | Y | Y |
| 153 | `wave24_153_am_entity_appearance_count.sql` | AM | INDEX/TABLE/VIEW/D VIEW | am_entity_appearance_count v:v_houjin_appearances / - / - | Y | Y |
| 155 | `wave24_155_am_geo_industry_density.sql` | AM | INDEX/TABLE | am_geo_industry_density / - / - | Y | Y |
| 157 | `wave24_157_am_adopted_company_features.sql` | AM | INDEX/TABLE/INS | am_adopted_company_features / - / - | Y | Y |
| 163 | `wave24_163_am_citation_network.sql` | AM | INDEX/TABLE/INS | am_citation_network / - / - | Y | Y |

Legend: `JPI*` = no header (defaults to jpintel). `JPI` = explicit `-- target_db: jpintel`. `AM` = `-- target_db: autonomath`.
Ops abbrev: TABLE / VTABLE / VIEW / INDEX / TRIGGER / ALT / D TABLE / D INDEX / D VIEW / INS / UPDATE / DELETE.

## Per-target group

### autonomath.db (72 migrations)

Applied by `entrypoint.sh §4` self-heal loop on each Fly boot. Files all begin with `-- target_db: autonomath` header. NEVER auto-run by `migrate.py` against jpintel.db (recorded-as-applied to keep `schema_migrations` consistent).

Files:
- `046_annotation_layer.sql`
- `047_validation_layer.sql`
- `049_provenance_strengthen.sql`
- `052_perf_indexes.sql`
- `055_acceptance_stats_index.sql`
- `064_unified_rule_view.sql`
- `065_compat_matrix_uni_id_backfill.sql`
- `067_dataset_versioning_autonomath.sql`
- `069_uncertainty_view.sql`
- `070_programs_active_at_v2.sql`
- `075_am_amendment_diff.sql`
- `077_compat_matrix_quality.sql`
- `078_amount_condition_quarantine.sql`
- `082_relation_density_expansion.sql`
- `090_law_article_body_en.sql`
- `091_tax_treaty.sql`
- `092_foreign_capital_eligibility.sql`
- `101_trust_infrastructure.sql`
- `103_nta_corpus.sql`
- `104_wave22_dd_question_templates.sql`
- `107_cross_source_baseline_state.sql`
- `110_autonomath_drop_cross_pollution.sql`
- `114_adoption_program_join.sql`
- `115_source_manifest_view.sql`
- `120_drop_dead_vec_unifts.sql`
- `121_jpi_programs_subsidy_rate_text_column.sql`
- `125_tax_treaty_backfill_30_countries.sql`
- `146_audit_merkle_anchor.sql`
- `147_am_entities_vec_tables.sql`
- `150_am_amount_condition_quality_tier.sql`
- `154_am_temporal_correlation.sql`
- `155_am_geo_industry_density.sql`
- `156_am_funding_stack_empirical.sql`
- `158_am_entity_density_score.sql`
- `159_am_id_bridge.sql`
- `160_am_adoption_trend_monthly.sql`
- `161_am_enforcement_anomaly.sql`
- `162_am_entity_pagerank.sql`
- `wave24_106_amendment_snapshot_rebuild.sql`
- `wave24_107_am_compat_matrix_visibility.sql`
- `wave24_109_am_amount_condition_is_authoritative.sql`
- `wave24_110_am_entities_vec_v2.sql`
- `wave24_111_am_entity_monthly_snapshot.sql`
- `wave24_112_am_region_extension.sql`
- `wave24_113b_jpi_programs_jsic.sql`
- `wave24_113c_autonomath_houjin_master_jsic.sql`
- `wave24_126_am_recommended_programs.sql`
- `wave24_127_am_program_combinations.sql`
- `wave24_128_am_program_calendar_12mo.sql`
- `wave24_129_am_enforcement_industry_risk.sql`
- `wave24_130_am_case_study_similarity.sql`
- `wave24_131_am_houjin_360_snapshot.sql`
- `wave24_132_am_tax_amendment_history.sql`
- `wave24_133_am_invoice_buyer_seller_graph.sql`
- `wave24_134_am_capital_band_program_match.sql`
- `wave24_135_am_program_adoption_stats.sql`
- `wave24_136_am_program_narrative.sql`
- `wave24_137_am_program_eligibility_predicate.sql`
- `wave24_138_am_program_documents.sql`
- `wave24_139_am_region_program_density.sql`
- `wave24_140_am_narrative_extracted_entities.sql`
- `wave24_141_am_narrative_quarantine.sql`
- `wave24_142_am_narrative_customer_reports.sql`
- `wave24_144_narrative_quality_kpi_view.sql`
- `wave24_145_am_data_quality_snapshot.sql`
- `wave24_148_am_credit_pack_purchase.sql`
- `wave24_149_am_program_narrative_full.sql`
- `wave24_152_am_5hop_graph.sql`
- `wave24_153_am_entity_appearance_count.sql`
- `wave24_155_am_geo_industry_density.sql`
- `wave24_157_am_adopted_company_features.sql`
- `wave24_163_am_citation_network.sql`

### jpintel.db (89 migrations)

Applied by `migrate.py` (lexicographic order). Includes 49 implicit-default files (no `target_db` marker) + 46 explicit `-- target_db: jpintel`.

## Risk surface

### Non-idempotent suspects (8)

Files where the parser could not confirm `IF NOT EXISTS` / `INSERT OR REPLACE` / etc. Safe to re-apply only if the runner has bookkeeping or if the wave plan executed it once.

- `010_email_schedule_day0_day1.sql` ((default=jpintel)) — DROP without IF EXISTS
- `016_court_decisions.sql` ((default=jpintel)) — DROP without IF EXISTS
- `052_api_keys_subscription_status.sql` ((default=jpintel)) — DROP without IF EXISTS
- `079_saved_searches.sql` (jpintel) — DROP without IF EXISTS
- `096_client_profiles.sql` (jpintel) — DROP without IF EXISTS
- `098_program_post_award_calendar.sql` (jpintel) — DROP without IF EXISTS
- `108_api_keys_id_unique_nonpartial.sql` (jpintel) — INSERT without conflict-handling
- `109_case_studies_fts_dedup.sql` (jpintel) — INSERT without conflict-handling

### DROP TABLE statements (40)

- `010_email_schedule_day0_day1.sql` drops `email_schedule`
- `110_autonomath_drop_cross_pollution.sql` drops `programs`
- `110_autonomath_drop_cross_pollution.sql` drops `programs_fts`
- `110_autonomath_drop_cross_pollution.sql` drops `programs_fts_config`
- `110_autonomath_drop_cross_pollution.sql` drops `programs_fts_content`
- `110_autonomath_drop_cross_pollution.sql` drops `programs_fts_data`
- `110_autonomath_drop_cross_pollution.sql` drops `programs_fts_docsize`
- `110_autonomath_drop_cross_pollution.sql` drops `programs_fts_idx`
- `120_drop_dead_vec_unifts.sql` drops `am_entities_fts_uni`
- `120_drop_dead_vec_unifts.sql` drops `am_entities_fts_uni_config`
- `120_drop_dead_vec_unifts.sql` drops `am_entities_fts_uni_content`
- `120_drop_dead_vec_unifts.sql` drops `am_entities_fts_uni_data`
- `120_drop_dead_vec_unifts.sql` drops `am_entities_fts_uni_docsize`
- `120_drop_dead_vec_unifts.sql` drops `am_entities_fts_uni_idx`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_rowid_map`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_a`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_a_chunks`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_a_info`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_a_rowids`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_a_vector_chunks00`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_dealbreakers`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_dealbreakers_chunks`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_dealbreakers_info`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_dealbreakers_rowids`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_dealbreakers_vector_chunks00`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_eligibility`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_eligibility_chunks`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_eligibility_info`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_eligibility_rowids`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_eligibility_vector_chunks00`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_exclusions`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_exclusions_chunks`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_exclusions_info`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_exclusions_rowids`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_exclusions_vector_chunks00`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_obligations`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_obligations_chunks`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_obligations_info`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_obligations_rowids`
- `120_drop_dead_vec_unifts.sql` drops `am_vec_tier_b_obligations_vector_chunks00`

### DROP COLUMN statements (0)

None.

## Apply-order graph

`migrate.py` walks files in lexicographic order. Same-number collisions resolve as `NNN_xxx.sql < wave24_NNN_xxx.sql` because `0` < `w` in ASCII. Within each target_db, the order is therefore deterministic.

### Table-creator → consumer (ALTER) edges (22)

Edges show which migration created a table, and which later migration ALTERs it. The consumer must run AFTER the creator. All current edges respect numeric order — no out-of-order ALTERs detected by this scan.

- `email_schedule`: created in `008_email_schedule.sql` → altered in `009_email_schedule_retry.sql`
- `loan_programs`: created in `011_external_data_tables.sql` → altered in `013_loan_risk_structure.sql`
- `bids`: created in `017_bids.sql` → altered in `067_dataset_versioning.sql`
- `case_studies`: created in `011_external_data_tables.sql` → altered in `067_dataset_versioning.sql`
- `court_decisions`: created in `016_court_decisions.sql` → altered in `067_dataset_versioning.sql`
- `enforcement_cases`: created in `011_external_data_tables.sql` → altered in `067_dataset_versioning.sql`
- `laws`: created in `015_laws.sql` → altered in `067_dataset_versioning.sql`
- `loan_programs`: created in `011_external_data_tables.sql` → altered in `067_dataset_versioning.sql`
- `tax_rulesets`: created in `018_tax_rulesets.sql` → altered in `067_dataset_versioning.sql`
- `saved_searches`: created in `079_saved_searches.sql` → altered in `097_saved_searches_profile_ids.sql`
- `saved_searches`: created in `079_saved_searches.sql` → altered in `099_recurring_engagement.sql`
- `saved_searches`: created in `079_saved_searches.sql` → altered in `105_integrations.sql`
- `analytics_events`: created in `111_analytics_events.sql` → altered in `113_weekly_digest_state.sql`
- `saved_searches`: created in `079_saved_searches.sql` → altered in `113_weekly_digest_state.sql`
- `audit_seals`: created in `089_audit_seal_table.sql` → altered in `119_audit_seal_seal_id_columns.sql`
- `analytics_events`: created in `111_analytics_events.sql` → altered in `123_funnel_events.sql`
- `analytics_events`: created in `111_analytics_events.sql` → altered in `124_src_attribution.sql`
- `funnel_events`: created in `123_funnel_events.sql` → altered in `124_src_attribution.sql`
- `audit_seals`: created in `089_audit_seal_table.sql` → altered in `wave24_105_audit_seal_key_version.sql`
- `houjin_master`: created in `014_business_intelligence_layer.sql` → altered in `wave24_113a_programs_jsic.sql`
- `houjin_master`: created in `014_business_intelligence_layer.sql` → altered in `wave24_113c_autonomath_houjin_master_jsic.sql`
- `am_program_narrative`: created in `wave24_136_am_program_narrative.sql` → altered in `wave24_141_am_narrative_quarantine.sql`

## Archive / removed surface

### Draft / disabled files

- `006_adoption.sql.draft` — never enabled, `.draft` suffix excludes it from runner glob.

### Tables dropped by later migrations

- `email_schedule` dropped in `010_email_schedule_day0_day1.sql`
- `programs` dropped in `110_autonomath_drop_cross_pollution.sql`
- `programs_fts` dropped in `110_autonomath_drop_cross_pollution.sql`
- `programs_fts_config` dropped in `110_autonomath_drop_cross_pollution.sql`
- `programs_fts_content` dropped in `110_autonomath_drop_cross_pollution.sql`
- `programs_fts_data` dropped in `110_autonomath_drop_cross_pollution.sql`
- `programs_fts_docsize` dropped in `110_autonomath_drop_cross_pollution.sql`
- `programs_fts_idx` dropped in `110_autonomath_drop_cross_pollution.sql`
- `am_entities_fts_uni` dropped in `120_drop_dead_vec_unifts.sql`
- `am_entities_fts_uni_config` dropped in `120_drop_dead_vec_unifts.sql`
- `am_entities_fts_uni_content` dropped in `120_drop_dead_vec_unifts.sql`
- `am_entities_fts_uni_data` dropped in `120_drop_dead_vec_unifts.sql`
- `am_entities_fts_uni_docsize` dropped in `120_drop_dead_vec_unifts.sql`
- `am_entities_fts_uni_idx` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_rowid_map` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_a` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_a_chunks` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_a_info` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_a_rowids` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_a_vector_chunks00` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_dealbreakers` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_dealbreakers_chunks` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_dealbreakers_info` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_dealbreakers_rowids` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_dealbreakers_vector_chunks00` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_eligibility` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_eligibility_chunks` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_eligibility_info` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_eligibility_rowids` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_eligibility_vector_chunks00` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_exclusions` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_exclusions_chunks` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_exclusions_info` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_exclusions_rowids` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_exclusions_vector_chunks00` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_obligations` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_obligations_chunks` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_obligations_info` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_obligations_rowids` dropped in `120_drop_dead_vec_unifts.sql`
- `am_vec_tier_b_obligations_vector_chunks00` dropped in `120_drop_dead_vec_unifts.sql`

### Columns dropped

- (none)

---

Generation: read-only static audit of `scripts/migrations/*.sql` (regex parse). No DB inspection performed; verify against runtime `schema_migrations` table for actual applied set.
