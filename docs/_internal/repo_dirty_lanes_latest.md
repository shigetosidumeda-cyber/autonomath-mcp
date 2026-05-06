# Repo Dirty Lane Report

- generated_at: `2026-05-06T17:56:40+09:00`
- repo: `/Users/shigetoumeda/jpcite`
- dirty_entries: `850`

## Lane Summary

| lane | total | modified | untracked | deleted | added/renamed/other |
|---|---:|---:|---:|---:|---:|
| runtime_code | 90 | 36 | 54 | 0 | 0 |
| billing_auth_security | 10 | 9 | 1 | 0 | 0 |
| migrations | 153 | 1 | 152 | 0 | 0 |
| cron_etl_ops | 58 | 0 | 58 | 0 | 0 |
| tests | 127 | 16 | 111 | 0 | 0 |
| workflows | 18 | 5 | 13 | 0 | 0 |
| generated_public_site | 82 | 54 | 28 | 0 | 0 |
| openapi_distribution | 6 | 5 | 1 | 0 | 0 |
| sdk_distribution | 55 | 29 | 25 | 1 | 0 |
| public_docs | 73 | 40 | 33 | 0 | 0 |
| internal_docs | 79 | 14 | 65 | 0 | 0 |
| operator_offline | 29 | 1 | 28 | 0 | 0 |
| benchmarks_monitoring | 28 | 0 | 28 | 0 | 0 |
| data_or_local_seed | 1 | 1 | 0 | 0 | 0 |
| root_release_files | 10 | 9 | 1 | 0 | 0 |
| misc_review | 31 | 24 | 7 | 0 | 0 |

## Review Order

1. Review `billing_auth_security`, `runtime_code`, `migrations`, and `workflows` before deployment.
2. Regenerate and compare `openapi_distribution`, `sdk_distribution`, and `generated_public_site` as one bundle.
3. Commit `internal_docs`, `operator_offline`, and `benchmarks_monitoring` only when they describe repeatable protocols or compact rollups.
4. Keep bulky local data and raw run outputs ignored; commit source tables, migrations, and small manifests instead.

## Entries By Lane

### runtime_code

- `modified` `src/jpintel_mcp/api/_response_models.py`
- `modified` `src/jpintel_mcp/api/advisors.py`
- `modified` `src/jpintel_mcp/api/audit.py`
- `modified` `src/jpintel_mcp/api/compliance.py`
- `modified` `src/jpintel_mcp/api/deps.py`
- `modified` `src/jpintel_mcp/api/evidence.py`
- `modified` `src/jpintel_mcp/api/funding_stack.py`
- `modified` `src/jpintel_mcp/api/houjin.py`
- `modified` `src/jpintel_mcp/api/intelligence.py`
- `modified` `src/jpintel_mcp/api/main.py`
- `modified` `src/jpintel_mcp/api/middleware/customer_cap.py`
- `modified` `src/jpintel_mcp/api/openapi_agent.py`
- `modified` `src/jpintel_mcp/api/widget_auth.py`
- `modified` `src/jpintel_mcp/config.py`
- `modified` `src/jpintel_mcp/email/templates/onboarding_day1.html`
- `modified` `src/jpintel_mcp/email/templates/onboarding_day1.txt`
- `modified` `src/jpintel_mcp/email/templates/onboarding_day3.html`
- `modified` `src/jpintel_mcp/email/templates/onboarding_day3.txt`
- `modified` `src/jpintel_mcp/email/templates/onboarding_trial_day_0.html`
- `modified` `src/jpintel_mcp/email/templates/onboarding_trial_day_0.txt`
- `modified` `src/jpintel_mcp/email/templates/onboarding_trial_day_11.html`
- `modified` `src/jpintel_mcp/email/templates/onboarding_trial_day_11.txt`
- `modified` `src/jpintel_mcp/email/templates/trial_magic_link.html`
- `modified` `src/jpintel_mcp/email/templates/trial_magic_link.txt`
- `modified` `src/jpintel_mcp/line/flow.py`
- `modified` `src/jpintel_mcp/mcp/_http_fallback.py`
- `modified` `src/jpintel_mcp/mcp/autonomath_tools/__init__.py`
- `modified` `src/jpintel_mcp/mcp/autonomath_tools/composition_tools.py`
- `modified` `src/jpintel_mcp/mcp/autonomath_tools/envelope_wrapper.py`
- `modified` `src/jpintel_mcp/mcp/autonomath_tools/error_envelope.py`
- `modified` `src/jpintel_mcp/mcp/autonomath_tools/industry_packs.py`
- `modified` `src/jpintel_mcp/mcp/autonomath_tools/wave22_tools.py`
- `modified` `src/jpintel_mcp/mcp/real_estate_tools/__init__.py`
- `modified` `src/jpintel_mcp/mcp/server.py`
- `modified` `src/jpintel_mcp/services/evidence_packet.py`
- `modified` `src/jpintel_mcp/services/funding_stack_checker.py`
- `untracked` `src/jpintel_mcp/api/_compact_envelope.py`
- `untracked` `src/jpintel_mcp/api/_field_filter.py`
- `untracked` `src/jpintel_mcp/api/artifacts.py`
- `untracked` `src/jpintel_mcp/api/calculator.py`
- `untracked` `src/jpintel_mcp/api/eligibility_predicate.py`
- `untracked` `src/jpintel_mcp/api/english_wedge.py`
- `untracked` `src/jpintel_mcp/api/evidence_batch.py`
- `untracked` `src/jpintel_mcp/api/intel.py`
- `untracked` `src/jpintel_mcp/api/intel_actionable.py`
- `untracked` `src/jpintel_mcp/api/intel_bundle_optimal.py`
- `untracked` `src/jpintel_mcp/api/intel_citation_pack.py`
- `untracked` `src/jpintel_mcp/api/intel_competitor_landscape.py`
- `untracked` `src/jpintel_mcp/api/intel_conflict.py`
- `untracked` `src/jpintel_mcp/api/intel_cross_jurisdiction.py`
- `untracked` `src/jpintel_mcp/api/intel_diff.py`
- `untracked` `src/jpintel_mcp/api/intel_houjin_full.py`
- `untracked` `src/jpintel_mcp/api/intel_news_brief.py`
- `untracked` `src/jpintel_mcp/api/intel_onboarding_brief.py`
- `untracked` `src/jpintel_mcp/api/intel_path.py`
- `untracked` `src/jpintel_mcp/api/intel_peer_group.py`
- `untracked` `src/jpintel_mcp/api/intel_portfolio_heatmap.py`
- `untracked` `src/jpintel_mcp/api/intel_program_full.py`
- `untracked` `src/jpintel_mcp/api/intel_refund_risk.py`
- `untracked` `src/jpintel_mcp/api/intel_regulatory_context.py`
- `untracked` `src/jpintel_mcp/api/intel_risk_score.py`
- `untracked` `src/jpintel_mcp/api/intel_scenario_simulate.py`
- `untracked` `src/jpintel_mcp/api/intel_timeline.py`
- `untracked` `src/jpintel_mcp/api/intel_why_excluded.py`
- `untracked` `src/jpintel_mcp/api/narrative.py`
- `untracked` `src/jpintel_mcp/api/narrative_report.py`
- `untracked` `src/jpintel_mcp/api/wave24_endpoints.py`
- `untracked` `src/jpintel_mcp/billing/credit_pack.py`
- `untracked` `src/jpintel_mcp/ingest/_gbiz_attribution.py`
- `untracked` `src/jpintel_mcp/ingest/_gbiz_rate_limiter.py`
- `untracked` `src/jpintel_mcp/ingest/normalizers/public_source_foundation.py`
- `untracked` `src/jpintel_mcp/ingest/plain_japanese_dict.py`
- `untracked` `src/jpintel_mcp/ingest/quote_check.py`
- `untracked` `src/jpintel_mcp/ingest/schemas/__init__.py`
- `untracked` `src/jpintel_mcp/ingest/schemas/eligibility_predicate.py`
- `untracked` `src/jpintel_mcp/ingest/schemas/enforcement_summary.py`
- `untracked` `src/jpintel_mcp/ingest/schemas/exclusion_rule.py`
- `untracked` `src/jpintel_mcp/ingest/schemas/houjin_360_narrative.py`
- `untracked` `src/jpintel_mcp/ingest/schemas/invoice_buyer_seller.py`
- `untracked` `src/jpintel_mcp/ingest/schemas/jsic_tag.py`
- ... `10` more

### billing_auth_security

- `modified` `src/jpintel_mcp/api/_audit_seal.py`
- `modified` `src/jpintel_mcp/api/anon_limit.py`
- `modified` `src/jpintel_mcp/api/appi_deletion.py`
- `modified` `src/jpintel_mcp/api/appi_disclosure.py`
- `modified` `src/jpintel_mcp/api/billing.py`
- `modified` `src/jpintel_mcp/api/line_webhook.py`
- `modified` `src/jpintel_mcp/api/middleware/cost_cap.py`
- `modified` `src/jpintel_mcp/api/middleware/idempotency.py`
- `modified` `src/jpintel_mcp/api/middleware/origin_enforcement.py`
- `untracked` `src/jpintel_mcp/api/audit_proof.py`

### migrations

- `modified` `scripts/migrations/007_anon_rate_limit.sql`
- `untracked` `scripts/migrations/146_audit_merkle_anchor.sql`
- `untracked` `scripts/migrations/147_am_entities_vec_tables.sql`
- `untracked` `scripts/migrations/148_programs_jsic_majors.sql`
- `untracked` `scripts/migrations/148_programs_jsic_majors_rollback.sql`
- `untracked` `scripts/migrations/150_am_amount_condition_quality_tier.sql`
- `untracked` `scripts/migrations/150_am_amount_condition_quality_tier_rollback.sql`
- `untracked` `scripts/migrations/151_programs_cross_source_verified.sql`
- `untracked` `scripts/migrations/154_am_temporal_correlation.sql`
- `untracked` `scripts/migrations/154_am_temporal_correlation_rollback.sql`
- `untracked` `scripts/migrations/155_am_geo_industry_density.sql`
- `untracked` `scripts/migrations/155_am_geo_industry_density_rollback.sql`
- `untracked` `scripts/migrations/156_am_funding_stack_empirical.sql`
- `untracked` `scripts/migrations/156_am_funding_stack_empirical_rollback.sql`
- `untracked` `scripts/migrations/158_am_entity_density_score.sql`
- `untracked` `scripts/migrations/158_am_entity_density_score_rollback.sql`
- `untracked` `scripts/migrations/159_am_id_bridge.sql`
- `untracked` `scripts/migrations/159_am_id_bridge_rollback.sql`
- `untracked` `scripts/migrations/160_am_adoption_trend_monthly.sql`
- `untracked` `scripts/migrations/160_am_adoption_trend_monthly_rollback.sql`
- `untracked` `scripts/migrations/161_am_enforcement_anomaly.sql`
- `untracked` `scripts/migrations/161_am_enforcement_anomaly_rollback.sql`
- `untracked` `scripts/migrations/162_am_entity_pagerank.sql`
- `untracked` `scripts/migrations/162_am_entity_pagerank_rollback.sql`
- `untracked` `scripts/migrations/164_am_program_eligibility_predicate.sql`
- `untracked` `scripts/migrations/164_am_program_eligibility_predicate_rollback.sql`
- `untracked` `scripts/migrations/165_usage_events_tokens_saved.sql`
- `untracked` `scripts/migrations/165_usage_events_tokens_saved_rollback.sql`
- `untracked` `scripts/migrations/166_am_canonical_vec_tables.sql`
- `untracked` `scripts/migrations/166_am_canonical_vec_tables_rollback.sql`
- `untracked` `scripts/migrations/167_programs_audit_quarantined.sql`
- `untracked` `scripts/migrations/167_programs_audit_quarantined_rollback.sql`
- `untracked` `scripts/migrations/168_am_actionable_answer_cache.sql`
- `untracked` `scripts/migrations/168_am_actionable_answer_cache_rollback.sql`
- `untracked` `scripts/migrations/169_am_actionable_qa_cache.sql`
- `untracked` `scripts/migrations/169_am_actionable_qa_cache_rollback.sql`
- `untracked` `scripts/migrations/170_program_decision_layer.sql`
- `untracked` `scripts/migrations/170_program_decision_layer_rollback.sql`
- `untracked` `scripts/migrations/171_corporate_risk_layer.sql`
- `untracked` `scripts/migrations/171_corporate_risk_layer_rollback.sql`
- `untracked` `scripts/migrations/172_corpus_snapshot.sql`
- `untracked` `scripts/migrations/172_corpus_snapshot_rollback.sql`
- `untracked` `scripts/migrations/173_artifact.sql`
- `untracked` `scripts/migrations/173_artifact_rollback.sql`
- `untracked` `scripts/migrations/174_source_document.sql`
- `untracked` `scripts/migrations/174_source_document_rollback.sql`
- `untracked` `scripts/migrations/175_extracted_fact.sql`
- `untracked` `scripts/migrations/175_extracted_fact_rollback.sql`
- `untracked` `scripts/migrations/176_source_foundation_domain_tables.sql`
- `untracked` `scripts/migrations/176_source_foundation_domain_tables_rollback.sql`
- `untracked` `scripts/migrations/README.md`
- `untracked` `scripts/migrations/wave24_105_audit_seal_key_version.sql`
- `untracked` `scripts/migrations/wave24_105_audit_seal_key_version_rollback.sql`
- `untracked` `scripts/migrations/wave24_106_amendment_snapshot_rebuild.sql`
- `untracked` `scripts/migrations/wave24_106_amendment_snapshot_rebuild_rollback.sql`
- `untracked` `scripts/migrations/wave24_107_am_compat_matrix_visibility.sql`
- `untracked` `scripts/migrations/wave24_107_am_compat_matrix_visibility_rollback.sql`
- `untracked` `scripts/migrations/wave24_108_programs_source_verified_at.sql`
- `untracked` `scripts/migrations/wave24_108_programs_source_verified_at_rollback.sql`
- `untracked` `scripts/migrations/wave24_109_am_amount_condition_is_authoritative.sql`
- `untracked` `scripts/migrations/wave24_109_am_amount_condition_is_authoritative_rollback.sql`
- `untracked` `scripts/migrations/wave24_110_am_entities_vec_v2.sql`
- `untracked` `scripts/migrations/wave24_110_am_entities_vec_v2_rollback.sql`
- `untracked` `scripts/migrations/wave24_110a_tier_c_cleanup.sql`
- `untracked` `scripts/migrations/wave24_110a_tier_c_cleanup_rollback.sql`
- `untracked` `scripts/migrations/wave24_111_am_entity_monthly_snapshot.sql`
- `untracked` `scripts/migrations/wave24_111_am_entity_monthly_snapshot_rollback.sql`
- `untracked` `scripts/migrations/wave24_112_am_region_extension.sql`
- `untracked` `scripts/migrations/wave24_112_am_region_extension_rollback.sql`
- `untracked` `scripts/migrations/wave24_113a_programs_jsic.sql`
- `untracked` `scripts/migrations/wave24_113a_programs_jsic_rollback.sql`
- `untracked` `scripts/migrations/wave24_113b_jpi_programs_jsic.sql`
- `untracked` `scripts/migrations/wave24_113b_jpi_programs_jsic_rollback.sql`
- `untracked` `scripts/migrations/wave24_113c_autonomath_houjin_master_jsic.sql`
- `untracked` `scripts/migrations/wave24_113c_autonomath_houjin_master_jsic_rollback.sql`
- `untracked` `scripts/migrations/wave24_126_am_recommended_programs.sql`
- `untracked` `scripts/migrations/wave24_126_am_recommended_programs_rollback.sql`
- `untracked` `scripts/migrations/wave24_127_am_program_combinations.sql`
- `untracked` `scripts/migrations/wave24_127_am_program_combinations_rollback.sql`
- `untracked` `scripts/migrations/wave24_128_am_program_calendar_12mo.sql`
- ... `73` more

### cron_etl_ops

- `untracked` `scripts/cron/ingest_gbiz_bulk_jsonl_monthly.py`
- `untracked` `scripts/cron/ingest_gbiz_certification_v2.py`
- `untracked` `scripts/cron/ingest_gbiz_commendation_v2.py`
- `untracked` `scripts/cron/ingest_gbiz_corporate_v2.py`
- `untracked` `scripts/cron/ingest_gbiz_procurement_v2.py`
- `untracked` `scripts/cron/ingest_gbiz_subsidy_v2.py`
- `untracked` `scripts/cron/ingest_offline_inbox.py`
- `untracked` `scripts/cron/jcrb_publish_results.py`
- `untracked` `scripts/cron/merkle_anchor_daily.py`
- `untracked` `scripts/cron/meta_analysis_daily.py`
- `untracked` `scripts/cron/narrative_audit_push.py`
- `untracked` `scripts/cron/narrative_drift_detect.py`
- `untracked` `scripts/cron/narrative_report_sla_breach.py`
- `untracked` `scripts/cron/populate_program_calendar_12mo.py`
- `untracked` `scripts/cron/precompute_actionable_answers.py`
- `untracked` `scripts/cron/precompute_actionable_cache.py`
- `untracked` `scripts/cron/precompute_data_quality.py`
- `untracked` `scripts/cron/precompute_recommended_programs.py`
- `untracked` `scripts/cron/refresh_amendment_diff_history.py`
- `untracked` `scripts/cron/stripe_version_check.py`
- `untracked` `scripts/etl/auto_tag_program_jsic.py`
- `untracked` `scripts/etl/build_5hop_graph.py`
- `untracked` `scripts/etl/build_adopted_company_features.py`
- `untracked` `scripts/etl/build_adoption_trend.py`
- `untracked` `scripts/etl/build_citation_network.py`
- `untracked` `scripts/etl/build_enforcement_anomaly.py`
- `untracked` `scripts/etl/build_entity_density_score.py`
- `untracked` `scripts/etl/build_entity_pagerank.py`
- `untracked` `scripts/etl/build_geo_industry_density.py`
- `untracked` `scripts/etl/build_id_bridge.py`
- `untracked` `scripts/etl/build_temporal_correlation.py`
- `untracked` `scripts/etl/extract_eligibility_predicate.py`
- `untracked` `scripts/etl/ingest_egov_law_translation.py`
- `untracked` `scripts/etl/ingest_inbox_law.py`
- `untracked` `scripts/etl/ingest_inbox_tsutatsu.py`
- `untracked` `scripts/etl/ingest_mof_tax_treaty.py`
- `untracked` `scripts/etl/ingest_nta_kfs_saiketsu.py`
- `untracked` `scripts/etl/mine_program_law_refs_deep_bridge.py`
- `untracked` `scripts/etl/populate_cross_source_verification.py`
- `untracked` `scripts/etl/populate_entity_appearance_count.py`
- `untracked` `scripts/etl/populate_geo_industry_density.py`
- `untracked` `scripts/etl/populate_program_law_refs_from_inbox.py`
- `untracked` `scripts/etl/quarantine_zero_source_programs.py`
- `untracked` `scripts/etl/rebuild_amendment_snapshot.py`
- `untracked` `scripts/etl/revalidate_amount_conditions.py`
- `untracked` `scripts/ops/cloudflare_redirect.sh`
- `untracked` `scripts/ops/discover_secrets.sh`
- `untracked` `scripts/ops/harvest_value_growth_dual.py`
- `untracked` `scripts/ops/mcp_manifest_deep_diff.py`
- `untracked` `scripts/ops/migration_inventory.py`
- `untracked` `scripts/ops/perf_smoke.py`
- `untracked` `scripts/ops/pre_deploy_verify.py`
- `untracked` `scripts/ops/preflight_production_improvement.py`
- `untracked` `scripts/ops/production_deploy_go_gate.py`
- `untracked` `scripts/ops/release_readiness.py`
- `untracked` `scripts/ops/repo_dirty_lane_report.py`
- `untracked` `scripts/ops/repo_hygiene_inventory.py`
- `untracked` `scripts/ops/repo_value_asset_report.py`

### tests

- `modified` `tests/conftest.py`
- `modified` `tests/test_anon_429_friction.py`
- `modified` `tests/test_appi_deletion.py`
- `modified` `tests/test_audit_seal_wire.py`
- `modified` `tests/test_billing_webhook_idempotency.py`
- `modified` `tests/test_cron_heartbeat.py`
- `modified` `tests/test_distribution_manifest.py`
- `modified` `tests/test_evidence_packet.py`
- `modified` `tests/test_funding_stack_checker.py`
- `modified` `tests/test_houjin_endpoint.py`
- `modified` `tests/test_intelligence_api.py`
- `modified` `tests/test_main.py`
- `modified` `tests/test_mcp_http_fallback.py`
- `modified` `tests/test_openapi_agent.py`
- `modified` `tests/test_openapi_export.py`
- `modified` `tests/test_schema_guard.py`
- `untracked` `tests/eval/practitioner_output_acceptance_queries_2026-05-06.jsonl`
- `untracked` `tests/mcp/test_http_fallback_all_120.py`
- `untracked` `tests/smoke/verify_120_tools.py`
- `untracked` `tests/test_amount_gate.py`
- `untracked` `tests/test_anon_limit_fail_closed.py`
- `untracked` `tests/test_appi_deletion_turnstile.py`
- `untracked` `tests/test_appi_turnstile.py`
- `untracked` `tests/test_artifact_evidence_contract.py`
- `untracked` `tests/test_artifacts_application_strategy_pack.py`
- `untracked` `tests/test_artifacts_company_public_packs.py`
- `untracked` `tests/test_artifacts_houjin_dd_pack.py`
- `untracked` `tests/test_audit_seal_persist_fail.py`
- `untracked` `tests/test_audit_seal_rotation.py`
- `untracked` `tests/test_boot_gate.py`
- `untracked` `tests/test_calculator.py`
- `untracked` `tests/test_ci_workflows.py`
- `untracked` `tests/test_compact_envelope.py`
- `untracked` `tests/test_composite_benchmark_guard.py`
- `untracked` `tests/test_corpus_snapshot_id_envelope.py`
- `untracked` `tests/test_cors_hardcoded_fallback.py`
- `untracked` `tests/test_credit_pack.py`
- `untracked` `tests/test_credit_pack_idempotency.py`
- `untracked` `tests/test_customer_cap_fail_closed.py`
- `untracked` `tests/test_customer_e2e.py`
- `untracked` `tests/test_customer_webhooks_test_rate_persisted.py`
- `untracked` `tests/test_data_quality_endpoint.py`
- `untracked` `tests/test_derived_data_layer_migrations.py`
- `untracked` `tests/test_english_wedge.py`
- `untracked` `tests/test_entrypoint_vec0_boot_gate.py`
- `untracked` `tests/test_evidence_batch.py`
- `untracked` `tests/test_field_filter.py`
- `untracked` `tests/test_gbiz_ingest_workflow.py`
- `untracked` `tests/test_gbiz_v2_m01_contract.py`
- `untracked` `tests/test_get_law_article_lang.py`
- `untracked` `tests/test_get_program_narrative_reading_level.py`
- `untracked` `tests/test_gzip_middleware.py`
- `untracked` `tests/test_harvest_value_growth_dual.py`
- `untracked` `tests/test_http_fallback_error_envelope.py`
- `untracked` `tests/test_industry_packs_billing.py`
- `untracked` `tests/test_industry_packs_envelope_compat.py`
- `untracked` `tests/test_ingest_offline_inbox.py`
- `untracked` `tests/test_ingest_offline_inbox_force_retag.py`
- `untracked` `tests/test_intel_actionable.py`
- `untracked` `tests/test_intel_audit_chain.py`
- `untracked` `tests/test_intel_bundle_optimal.py`
- `untracked` `tests/test_intel_citation_pack.py`
- `untracked` `tests/test_intel_conflict.py`
- `untracked` `tests/test_intel_cross_jurisdiction.py`
- `untracked` `tests/test_intel_diff.py`
- `untracked` `tests/test_intel_houjin_full.py`
- `untracked` `tests/test_intel_match.py`
- `untracked` `tests/test_intel_news_brief.py`
- `untracked` `tests/test_intel_onboarding_brief.py`
- `untracked` `tests/test_intel_path.py`
- `untracked` `tests/test_intel_peer_group.py`
- `untracked` `tests/test_intel_program_full.py`
- `untracked` `tests/test_intel_refund_risk.py`
- `untracked` `tests/test_intel_regulatory_context.py`
- `untracked` `tests/test_intel_risk_score.py`
- `untracked` `tests/test_intel_scenario_simulate.py`
- `untracked` `tests/test_intel_timeline.py`
- `untracked` `tests/test_intel_wave32_mcp.py`
- `untracked` `tests/test_intel_why_excluded.py`
- `untracked` `tests/test_invoice_pii_attribution.py`
- ... `47` more

### workflows

- `modified` `.github/workflows/deploy.yml`
- `modified` `.github/workflows/distribution-manifest-check.yml`
- `modified` `.github/workflows/openapi.yml`
- `modified` `.github/workflows/release.yml`
- `modified` `.github/workflows/test.yml`
- `untracked` `.github/workflows/README.md`
- `untracked` `.github/workflows/gbiz-ingest-monthly.yml`
- `untracked` `.github/workflows/idempotency-sweep-hourly.yml`
- `untracked` `.github/workflows/ingest-offline-inbox-hourly.yml`
- `untracked` `.github/workflows/narrative-audit-monthly.yml`
- `untracked` `.github/workflows/narrative-sla-breach-hourly.yml`
- `untracked` `.github/workflows/populate-calendar-monthly.yml`
- `untracked` `.github/workflows/practitioner-eval-publish.yml`
- `untracked` `.github/workflows/precompute-actionable-daily.yml`
- `untracked` `.github/workflows/precompute-recommended-monthly.yml`
- `untracked` `.github/workflows/refresh-sources-daily.yml`
- `untracked` `.github/workflows/refresh-sources-weekly.yml`
- `untracked` `.github/workflows/trust-center-publish.yml`

### generated_public_site

- `modified` `overrides/partials/index_jsonld.html`
- `modified` `site/.well-known/trust.json`
- `modified` `site/404.html`
- `modified` `site/_data/public_counts.json`
- `modified` `site/audiences/dev.html`
- `modified` `site/audiences/shinkin.html`
- `modified` `site/audiences/shokokai.html`
- `modified` `site/calculator.html`
- `modified` `site/compare.html`
- `modified` `site/compare/diy-scraping/index.html`
- `modified` `site/compare/freee/index.html`
- `modified` `site/compare/gbizinfo/index.html`
- `modified` `site/compare/japan-corporate-mcp/index.html`
- `modified` `site/compare/jgrants-mcp/index.html`
- `modified` `site/compare/jgrants/index.html`
- `modified` `site/compare/mirasapo/index.html`
- `modified` `site/compare/moneyforward/index.html`
- `modified` `site/compare/navit/index.html`
- `modified` `site/compare/nta-invoice/index.html`
- `modified` `site/compare/tax-law-mcp/index.html`
- `modified` `site/compare/tdb/index.html`
- `modified` `site/compare/tsr/index.html`
- `modified` `site/downloads/autonomath-mcp.mcpb`
- `modified` `site/en/404.html`
- `modified` `site/en/about.html`
- `modified` `site/en/audiences/dev.html`
- `modified` `site/en/audiences/foreign-investor.html`
- `modified` `site/en/audiences/index.html`
- `modified` `site/en/audiences/tax-advisor.html`
- `modified` `site/en/audiences/vc.html`
- `modified` `site/en/compare.html`
- `modified` `site/en/getting-started.html`
- `modified` `site/en/glossary.html`
- `modified` `site/en/index.html`
- `modified` `site/en/llms.txt`
- `modified` `site/en/pricing.html`
- `modified` `site/en/products.html`
- `modified` `site/en/success.html`
- `modified` `site/facts.html`
- `modified` `site/index.html`
- `modified` `site/integrations/chatgpt.html`
- `modified` `site/integrations/openai-custom-gpt.html`
- `modified` `site/llms.en.txt`
- `modified` `site/llms.txt`
- `modified` `site/playground.html`
- `modified` `site/press/about.md`
- `modified` `site/press/fact-sheet.md`
- `modified` `site/pricing.html`
- `modified` `site/qa/llm-evidence/chatgpt-vs-jpcite.html`
- `modified` `site/qa/llm-evidence/context-savings.html`
- `modified` `site/qa/mcp/what-can-jpcite-mcp-do.html`
- `modified` `site/sitemap-index.xml`
- `modified` `site/stats.html`
- `modified` `site/trial.html`
- `untracked` `site/README.md`
- `untracked` `site/benchmark/index.html`
- `untracked` `site/benchmark/results.csv`
- `untracked` `site/benchmark/results.json`
- `untracked` `site/blog/v0.3.4-release.html`
- `untracked` `site/calculator/index.html`
- `untracked` `site/changelog/index.html`
- `untracked` `site/dashboard/savings.html`
- `untracked` `site/en/foreign-investor.html`
- `untracked` `site/intel/index.html`
- `untracked` `site/practitioner-eval/ai_dev.html`
- `untracked` `site/practitioner-eval/foreign_fdi_compliance.html`
- `untracked` `site/practitioner-eval/foreign_fdi_investor.html`
- `untracked` `site/practitioner-eval/index.html`
- `untracked` `site/practitioner-eval/industry_pack_construction.html`
- `untracked` `site/practitioner-eval/industry_pack_real_estate.html`
- `untracked` `site/practitioner-eval/kaikeishi.html`
- `untracked` `site/practitioner-eval/kaikeishi_audit.html`
- `untracked` `site/practitioner-eval/kokusai_zeimu.html`
- `untracked` `site/practitioner-eval/ma_analyst.html`
- `untracked` `site/practitioner-eval/ma_valuation.html`
- `untracked` `site/practitioner-eval/monitoring_pic.html`
- `untracked` `site/practitioner-eval/shinkin_shokokai.html`
- `untracked` `site/practitioner-eval/subsidy_consultant.html`
- `untracked` `site/practitioner-eval/template.html`
- `untracked` `site/practitioner-eval/zeirishi.html`
- ... `2` more

### openapi_distribution

- `modified` `docs/openapi/agent.json`
- `modified` `docs/openapi/v1.json`
- `modified` `site/mcp-server.json`
- `modified` `site/openapi.agent.json`
- `modified` `site/server.json`
- `untracked` `site/mcp-server.full.json`

### sdk_distribution

- `modified` `dxt/README.md`
- `modified` `dxt/manifest.json`
- `modified` `mcp-server.composition.json`
- `modified` `mcp-server.core.json`
- `modified` `mcp-server.full.json`
- `modified` `mcp-server.json`
- `modified` `sdk/.gitignore`
- `modified` `sdk/README.md`
- `modified` `sdk/agents/README.md`
- `modified` `sdk/agents/package-lock.json`
- `modified` `sdk/agents/src/index.ts`
- `modified` `sdk/agents/src/lib/jpcite_client.ts`
- `modified` `sdk/npm-package/README.md`
- `modified` `sdk/npm-package/src/index.ts`
- `modified` `sdk/npm-package/test/index.test.ts`
- `modified` `sdk/python/README.md`
- `modified` `sdk/python/autonomath/__init__.py`
- `modified` `sdk/python/autonomath/_shared.py`
- `modified` `sdk/python/autonomath/client.py`
- `modified` `sdk/python/autonomath/client_async.py`
- `modified` `sdk/python/autonomath/types.py`
- `modified` `sdk/python/tests/test_client.py`
- `modified` `sdk/python/uv.lock`
- `modified` `sdk/typescript/README.md`
- `deleted` `sdk/typescript/autonomath-sdk-0.2.0.tgz`
- `modified` `sdk/typescript/src/index.ts`
- `modified` `sdk/typescript/src/mcp.ts`
- `modified` `sdk/typescript/src/types.ts`
- `modified` `server.json`
- `modified` `smithery.yaml`
- `untracked` `sdk/browser-extension/README.md`
- `untracked` `sdk/browser-extension/background.js`
- `untracked` `sdk/browser-extension/content.css`
- `untracked` `sdk/browser-extension/content.js`
- `untracked` `sdk/browser-extension/icons/icon128.png`
- `untracked` `sdk/browser-extension/icons/icon16.png`
- `untracked` `sdk/browser-extension/icons/icon32.png`
- `untracked` `sdk/browser-extension/icons/icon48.png`
- `untracked` `sdk/browser-extension/manifest.json`
- `untracked` `sdk/browser-extension/options.html`
- `untracked` `sdk/browser-extension/options.js`
- `untracked` `sdk/browser-extension/popup.html`
- `untracked` `sdk/browser-extension/popup.js`
- `untracked` `sdk/vscode-extension/.vscodeignore`
- `untracked` `sdk/vscode-extension/LICENSE`
- `untracked` `sdk/vscode-extension/README.md`
- `untracked` `sdk/vscode-extension/icon.png`
- `untracked` `sdk/vscode-extension/package-lock.json`
- `untracked` `sdk/vscode-extension/package.json`
- `untracked` `sdk/vscode-extension/src/extension.ts`
- `untracked` `sdk/vscode-extension/src/jpciteClient.ts`
- `untracked` `sdk/vscode-extension/src/lawCodeLensProvider.ts`
- `untracked` `sdk/vscode-extension/src/lawHoverProvider.ts`
- `untracked` `sdk/vscode-extension/src/lawIdRegex.ts`
- `untracked` `sdk/vscode-extension/tsconfig.json`

### public_docs

- `modified` `docs/api-reference.md`
- `modified` `docs/bench_results_template.md`
- `modified` `docs/blog/2026-05-5_audience_pitch.md`
- `modified` `docs/blog/2026-05-launch-intro.md`
- `modified` `docs/compare_matrix.csv`
- `modified` `docs/cookbook/r20-openai-agents.md`
- `modified` `docs/getting-started.md`
- `modified` `docs/healthcare_v3_plan.md`
- `modified` `docs/honest_capabilities.md`
- `modified` `docs/index.md`
- `modified` `docs/integrations/ai-recommendation-template.md`
- `modified` `docs/launch/README.md`
- `modified` `docs/launch/devto.md`
- `modified` `docs/launch/hn.md`
- `modified` `docs/launch/lobsters.md`
- `modified` `docs/launch/reddit_claudeai.md`
- `modified` `docs/launch/reddit_entrepreneur.md`
- `modified` `docs/launch/reddit_localllama.md`
- `modified` `docs/launch/reddit_programming.md`
- `modified` `docs/launch/reddit_sideproject.md`
- `modified` `docs/launch/twitter_x_thread.md`
- `modified` `docs/launch_assets/hn_show_post.md`
- `modified` `docs/launch_assets/linkedin_post.md`
- `modified` `docs/launch_assets/reddit_post.md`
- `modified` `docs/launch_assets/twitter_thread.md`
- `modified` `docs/launch_assets/x_thread_thread.md`
- `modified` `docs/launch_assets/zenn_intro_published.md`
- `modified` `docs/launch_checklist.md`
- `modified` `docs/mcp-tools.md`
- `modified` `docs/organic_outreach_templates.md`
- `modified` `docs/partnerships/anthropic_directory.md`
- `modified` `docs/per_tool_precision.md`
- `modified` `docs/press_kit.md`
- `modified` `docs/pricing.md`
- `modified` `docs/real_estate_v5_plan.md`
- `modified` `docs/recommendation-scenarios.md`
- `modified` `docs/roadmap.md`
- `modified` `docs/sdks/typescript.md`
- `modified` `examples/README.md`
- `modified` `examples/python/04_pandas_export_csv.py`
- `untracked` `docs/SYSTEM_INDEX.md`
- `untracked` `docs/en/foreign_investor.md`
- `untracked` `docs/integrations/README.md`
- `untracked` `docs/integrations/agent-routing-and-cta-spec.md`
- `untracked` `docs/integrations/ai-agent-recommendation-plan.md`
- `untracked` `docs/integrations/artifact-catalog.md`
- `untracked` `docs/integrations/cache_hit_rates.md`
- `untracked` `docs/integrations/compact_response.md`
- `untracked` `docs/integrations/composite-bench-results.md`
- `untracked` `docs/integrations/composite-vs-multicall.md`
- `untracked` `docs/integrations/deep-paid-output-and-data-foundation-plan.md`
- `untracked` `docs/integrations/derived-data-layer-spec.md`
- `untracked` `docs/integrations/implementation-loop-log.md`
- `untracked` `docs/integrations/output-satisfaction-spec.md`
- `untracked` `docs/integrations/partial_response.md`
- `untracked` `docs/integrations/token-efficiency-proof.md`
- `untracked` `docs/integrations/use_predicate_for_certainty.md`
- `untracked` `docs/integrations/use_predicate_for_savings.md`
- `untracked` `docs/integrations/w32-composite-surfaces.md`
- `untracked` `docs/legal/gbizinfo_terms_compliance.md`
- `untracked` `docs/runbook/README.md`
- `untracked` `docs/runbook/cloudflare_redirect.md`
- `untracked` `docs/runbook/freee_mf_marketplace_submit.md`
- `untracked` `docs/runbook/github_rename.md`
- `untracked` `docs/runbook/litestream_setup.md`
- `untracked` `docs/runbook/npm_publish_jpcite_sdk.md`
- `untracked` `docs/runbook/pypi_jpcite_meta.md`
- `untracked` `docs/runbook/secret_rotation.md`
- `untracked` `docs/runbook/stripe_meter_events_migration.md`
- `untracked` `docs/schemas/client_company_folder_v1_request.schema.json`
- `untracked` `docs/schemas/client_company_folder_v1_response.schema.json`
- `untracked` `pypi-jpcite-meta/README.md`
- `untracked` `pypi-jpcite-meta/pyproject.toml`

### internal_docs

- `modified` `docs/_internal/INDEX.md`
- `modified` `docs/_internal/W21_WORKFLOWS_PENDING.md`
- `modified` `docs/_internal/_INDEX.md`
- `modified` `docs/_internal/capacity_plan.md`
- `modified` `docs/_internal/deploy_gotchas.md`
- `modified` `docs/_internal/deploy_staging.md`
- `modified` `docs/_internal/env_setup_guide.md`
- `modified` `docs/_internal/fallback_plan.md`
- `modified` `docs/_internal/incident_runbook.md`
- `modified` `docs/_internal/ingest_automation.md`
- `modified` `docs/_internal/launch_dday_matrix.md`
- `modified` `docs/_internal/launch_war_room.md`
- `modified` `docs/_internal/observability_dashboard.md`
- `modified` `docs/_internal/operators_playbook.md`
- `untracked` `docs/_internal/CURRENT_SOT_2026-05-06.md`
- `untracked` `docs/_internal/INDEX_2026-05-05.md`
- `untracked` `docs/_internal/MIGRATION_INDEX.md`
- `untracked` `docs/_internal/PRODUCTION_DEPLOY_PACKET_2026-05-06.md`
- `untracked` `docs/_internal/README.md`
- `untracked` `docs/_internal/REPO_HYGIENE_TRIAGE_2026-05-06.md`
- `untracked` `docs/_internal/SECRETS_REGISTRY.md`
- `untracked` `docs/_internal/TABLE_CATALOG.md`
- `untracked` `docs/_internal/TEST_CATALOG.md`
- `untracked` `docs/_internal/TRACEABILITY_MATRIX.md`
- `untracked` `docs/_internal/W19_PYPI_PUBLISH_READY.md`
- `untracked` `docs/_internal/W19_USER_ACTION_CHECKLIST.md`
- `untracked` `docs/_internal/W19_VENV312_README.md`
- `untracked` `docs/_internal/W19_github_rename_diff.md`
- `untracked` `docs/_internal/W19_github_rename_runbook.md`
- `untracked` `docs/_internal/W19_lawyer_consult_outline.md`
- `untracked` `docs/_internal/W19_legal_self_audit.md`
- `untracked` `docs/_internal/W20_AMOUNT_VALIDATION_REPORT.md`
- `untracked` `docs/_internal/W20_CLAUDE_DESKTOP_SUBMISSION.md`
- `untracked` `docs/_internal/W20_NARRATIVE_BATCH_RUNNER.md`
- `untracked` `docs/_internal/W20_PYPI_OIDC_SETUP.md`
- `untracked` `docs/_internal/W21_VEC_BENCH.md`
- `untracked` `docs/_internal/W22_INBOX_QUALITY_AUDIT.md`
- `untracked` `docs/_internal/W22_NEW_LAW_PROGRAM_LINKS.md`
- `untracked` `docs/_internal/W22_NEW_LAW_PROGRAM_LINKS.tsv`
- `untracked` `docs/_internal/W22_SENSITIVE_LAW_MAP.md`
- `untracked` `docs/_internal/W24_BRAND_AUDIT.md`
- `untracked` `docs/_internal/W24_DEAD_CODE_AUDIT.md`
- `untracked` `docs/_internal/W24_PENDING_WORKFLOWS_REAUDIT.md`
- `untracked` `docs/_internal/W24_SOT_SYNC_AUDIT.md`
- `untracked` `docs/_internal/W28_DATA_QUALITY_DEEP_AUDIT.md`
- `untracked` `docs/_internal/W28_NARRATIVE_DISPATCH.md`
- `untracked` `docs/_internal/W28_PAYLOAD_AUDIT.md`
- `untracked` `docs/_internal/ai_professional_public_layer_implementation_blueprint_2026-05-06.md`
- `untracked` `docs/_internal/ai_professional_public_layer_plan_2026-05-06.md`
- `untracked` `docs/_internal/artifact_api_contract_2026-05-06.md`
- `untracked` `docs/_internal/bpo_shigyo_paid_value_plan_2026-05-06.md`
- `untracked` `docs/_internal/company_public_baseline_demand_analysis_2026-05-06.md`
- `untracked` `docs/_internal/dirty_tree_release_classification_2026-05-06.md`
- `untracked` `docs/_internal/evidence_packet_persistence_design_2026-05-06.md`
- `untracked` `docs/_internal/generated_artifacts_map_2026-05-06.md`
- `untracked` `docs/_internal/info_collection_cli_latest_implementation_handoff_2026-05-06.md`
- `untracked` `docs/_internal/information_collection_cli_prompts_2026-05-06.md`
- `untracked` `docs/_internal/main_execution_queue_2026-05-06.md`
- `untracked` `docs/_internal/main_implementation_preparation_2026-05-06.md`
- `untracked` `docs/_internal/marketplace_application/common_company_profile.md`
- `untracked` `docs/_internal/marketplace_application/freee_apps_application.md`
- `untracked` `docs/_internal/marketplace_application/moneyforward_marketplace_application.md`
- `untracked` `docs/_internal/mcp_manifest_deep_diff_latest.md`
- `untracked` `docs/_internal/migration_inventory_latest.md`
- `untracked` `docs/_internal/offline_cli_inbox_contract_2026-05-06.md`
- `untracked` `docs/_internal/openapi_distribution_sync_2026-05-06.md`
- `untracked` `docs/_internal/practitioner_output_catalog_2026-05-06.md`
- `untracked` `docs/_internal/production_full_improvement_start_queue_2026-05-06.md`
- `untracked` `docs/_internal/public_source_foundation_reingest_plan_2026-05-06.md`
- `untracked` `docs/_internal/release_readiness_2026-05-06.md`
- `untracked` `docs/_internal/repo_cleanup_loop_report_2026-05-06.md`
- `untracked` `docs/_internal/repo_dirty_lanes_latest.md`
- `untracked` `docs/_internal/repo_hygiene_inventory_latest.md`
- `untracked` `docs/_internal/repo_organization_assessment_2026-05-06.md`
- `untracked` `docs/_internal/repo_value_assets_latest.md`
- `untracked` `docs/_internal/source_foundation_triage_2026-05-06.md`
- `untracked` `docs/_internal/value_productization_queue_2026-05-06.md`
- `untracked` `docs/_internal/waf_deploy_gate_prepare_2026-05-06.md`
- `untracked` `docs/_internal/wave24_migrations.sql.bundle`

### operator_offline

- `modified` `tools/offline/README.md`
- `untracked` `tools/offline/INFO_COLLECTOR_LOOP.md`
- `untracked` `tools/offline/INFO_COLLECTOR_LOOP_B.md`
- `untracked` `tools/offline/INFO_COLLECTOR_LOOP_C.md`
- `untracked` `tools/offline/INFO_COLLECTOR_OUTPUT_MARKET_2026-05-06.md`
- `untracked` `tools/offline/INFO_COLLECTOR_PUBLIC_SOURCES_2026-05-06.md`
- `untracked` `tools/offline/INFO_COLLECTOR_VALUE_GROWTH_2026-05-06.md`
- `untracked` `tools/offline/INFO_COLLECTOR_VALUE_GROWTH_DUAL_CLI_300_AGENTS_2026-05-06.md`
- `untracked` `tools/offline/_inbox_audit.json`
- `untracked` `tools/offline/_runner_common.py`
- `untracked` `tools/offline/bench_vec_search.py`
- `untracked` `tools/offline/dispatch_narrative_batches.sh`
- `untracked` `tools/offline/embed_canonical_entities.py`
- `untracked` `tools/offline/embed_corpus_local.py`
- `untracked` `tools/offline/extract_narrative_entities.py`
- `untracked` `tools/offline/generate_program_narratives.py`
- `untracked` `tools/offline/ingest_narrative_inbox.py`
- `untracked` `tools/offline/iter_egov_c.py`
- `untracked` `tools/offline/narrative_rollback.py`
- `untracked` `tools/offline/rotate_audit_seal.py`
- `untracked` `tools/offline/run_app_documents_batch.py`
- `untracked` `tools/offline/run_enforcement_amount_extract_batch.py`
- `untracked` `tools/offline/run_enforcement_summary_batch.py`
- `untracked` `tools/offline/run_extract_eligibility_predicates_batch.py`
- `untracked` `tools/offline/run_extract_exclusion_rules_batch.py`
- `untracked` `tools/offline/run_houjin_360_narrative_batch.py`
- `untracked` `tools/offline/run_invoice_buyer_seller_batch.py`
- `untracked` `tools/offline/run_narrative_batch.py`
- `untracked` `tools/offline/run_tag_jsic_batch.py`

### benchmarks_monitoring

- `untracked` `benchmarks/README.md`
- `untracked` `benchmarks/composite_vs_naive/README.md`
- `untracked` `benchmarks/composite_vs_naive/results.jsonl`
- `untracked` `benchmarks/composite_vs_naive/run.py`
- `untracked` `benchmarks/composite_vs_naive/summary.md`
- `untracked` `benchmarks/jcrb_v1/README.md`
- `untracked` `benchmarks/jcrb_v1/expected_baseline.md`
- `untracked` `benchmarks/jcrb_v1/questions.jsonl`
- `untracked` `benchmarks/jcrb_v1/questions_50q.jsonl`
- `untracked` `benchmarks/jcrb_v1/results/token_savings.csv`
- `untracked` `benchmarks/jcrb_v1/results/token_savings_50q.csv`
- `untracked` `benchmarks/jcrb_v1/run.py`
- `untracked` `benchmarks/jcrb_v1/run_token_benchmark.py`
- `untracked` `benchmarks/jcrb_v1/scoring.py`
- `untracked` `benchmarks/jcrb_v1/submissions/SAMPLE_README.md`
- `untracked` `benchmarks/jcrb_v1/submissions/SEED_claude_opus_47__with.json`
- `untracked` `benchmarks/jcrb_v1/submissions/SEED_claude_opus_47__without.json`
- `untracked` `benchmarks/jcrb_v1/submissions/SEED_gemini_2_5__with.json`
- `untracked` `benchmarks/jcrb_v1/submissions/SEED_gemini_2_5__without.json`
- `untracked` `benchmarks/jcrb_v1/submissions/SEED_gpt_5__with.json`
- `untracked` `benchmarks/jcrb_v1/submissions/SEED_gpt_5__without.json`
- `untracked` `benchmarks/jcrb_v1/token_estimator.py`
- `untracked` `benchmarks/jcrb_v1/token_savings_50q_report.md`
- `untracked` `benchmarks/jcrb_v1/token_savings_report.md`
- `untracked` `benchmarks/sims/zeirishi_1month.py`
- `untracked` `benchmarks/sims/zeirishi_1month_report.md`
- `untracked` `monitoring/README.md`
- `untracked` `monitoring/sla_targets.yaml`

### data_or_local_seed

- `modified` `data/source_freshness_report.json`

### root_release_files

- `modified` `.dockerignore`
- `modified` `.gitignore`
- `modified` `CLAUDE.md`
- `modified` `DIRECTORY.md`
- `modified` `README.md`
- `modified` `entrypoint.sh`
- `modified` `mkdocs.yml`
- `modified` `pyproject.toml`
- `modified` `uv.lock`
- `untracked` `MASTER_PLAN_v1.md`

### misc_review

- `modified` `.env.example`
- `modified` `.pre-commit-config.yaml`
- `modified` `scripts/_build_compare_csv.py`
- `modified` `scripts/check_distribution_manifest_drift.py`
- `modified` `scripts/distribution_manifest.yml`
- `modified` `scripts/distribution_manifest_README.md`
- `modified` `scripts/export_agent_openapi.py`
- `modified` `scripts/export_openapi.py`
- `modified` `scripts/generate_compare_pages.py`
- `modified` `scripts/generate_geo_citation_pages.py`
- `modified` `scripts/generate_public_counts.py`
- `modified` `scripts/mcp_registries.md`
- `modified` `scripts/mcp_registries_submission.json`
- `modified` `scripts/regen_llms_full.py`
- `modified` `scripts/regen_llms_full_en.py`
- `modified` `scripts/registry_submissions/README.md`
- `modified` `scripts/registry_submissions/anthropic_directory_submission.md`
- `modified` `scripts/registry_submissions/cline_pr.md`
- `modified` `scripts/registry_submissions/cursor_submission.md`
- `modified` `scripts/registry_submissions/mcp_hunt_submission.md`
- `modified` `scripts/registry_submissions/mcp_server_finder_email.md`
- `modified` `scripts/registry_submissions/mcp_so_submission.md`
- `modified` `scripts/registry_submissions/pulsemcp_submission.md`
- `modified` `scripts/schema_guard.py`
- `untracked` `scripts/MANIFEST.md`
- `untracked` `scripts/eval/__init__.py`
- `untracked` `scripts/eval/_persona_index.py`
- `untracked` `scripts/eval/assemble_trust_matrix.py`
- `untracked` `scripts/eval/run_practitioner_eval.py`
- `untracked` `scripts/generate_geo_industry_pages.py`
- `untracked` `scripts/notify_existing_users.py`

