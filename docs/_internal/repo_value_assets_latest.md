# Repo Value Asset Report

- generated_at: `2026-05-06T14:19:23+09:00`
- repo: `/Users/shigetoumeda/jpcite`
- value_asset_entries: `911`

## Summary

| category | entries | untracked/modified/deleted | value | next action |
|---|---:|---:|---|---|
| internal_sensitive_only | 8 | 7 | Operator control material that may protect the business but should not be marketed directly. | Keep internal, inspect before publishing, and summarize only safe conclusions. |
| ai_first_hop_distribution | 253 | 82 | Assets that help ChatGPT, Claude, Cursor, MCP clients, and agents discover or call jpcite first. | Keep manifests synchronized and turn integration docs into copy-paste onboarding paths. |
| customer_output_surfaces | 40 | 39 | API/MCP/doc assets that can return concrete practitioner outputs instead of generic LLM advice. | Bundle by persona and prove each surface with acceptance queries. |
| data_foundation | 368 | 174 | Tables, ETL, and cron jobs that make jpcite cheaper and more useful than ad-hoc web research. | Convert raw joins into stable derived tables and documented refresh jobs. |
| trust_quality_proof | 56 | 35 | Benchmarks, smoke tests, evals, monitoring, and release gates that can prove reliability. | Publish only conservative summaries; keep raw fixtures and internal gates as support. |
| operator_research_to_product | 25 | 17 | Large research loops that can become roadmaps, packs, source matrices, and internal playbooks. | Promote compact rollups and repeatable prompts; keep raw run output ignored. |
| public_conversion_copy | 161 | 38 | Docs, pages, examples, and launch collateral that can turn discovered value into paid usage. | Tie each page to one concrete artifact, benchmark, or first-hop integration path. |

## Productization Ideas

1. Turn `customer_output_surfaces` into persona packs: tax advisor, BPO/AI ops, M&A, finance, municipal, and foreign FDI.
2. Turn `data_foundation` into derived answer tables: eligibility predicates, source verification, entity timelines, risk layers, and program combinations.
3. Turn `ai_first_hop_distribution` into agent onboarding: MCP manifest, OpenAPI agent spec, SDK snippets, and `llms.txt` discovery paths.
4. Turn `trust_quality_proof` into conservative proof pages: benchmark method, acceptance queries, source freshness, and uptime/SLA targets.
5. Turn `operator_research_to_product` into compact public artifacts only after license, citation, and claim review.

## Category Details

### Internal Sensitive Only

- value: Operator control material that may protect the business but should not be marketed directly.
- action: Keep internal, inspect before publishing, and summarize only safe conclusions.
- risk: Secrets, legal drafts, and marketplace applications can leak strategy or credentials.

- `untracked` `docs/_internal/SECRETS_REGISTRY.md`
- `untracked` `docs/_internal/W19_lawyer_consult_outline.md`
- `untracked` `docs/_internal/W19_legal_self_audit.md`
- `tracked` `docs/_internal/legal_contacts.md`
- `untracked` `docs/_internal/marketplace_application/common_company_profile.md`
- `untracked` `docs/_internal/marketplace_application/freee_apps_application.md`
- `untracked` `docs/_internal/marketplace_application/moneyforward_marketplace_application.md`
- `untracked` `tools/offline/_inbox_audit.json`

### AI First-Hop Distribution

- value: Assets that help ChatGPT, Claude, Cursor, MCP clients, and agents discover or call jpcite first.
- action: Keep manifests synchronized and turn integration docs into copy-paste onboarding paths.
- risk: Version drift or broken manifests make agents stop trusting the endpoint.

- `untracked` `docs/integrations/README.md`
- `untracked` `docs/integrations/agent-routing-and-cta-spec.md`
- `untracked` `docs/integrations/ai-agent-recommendation-plan.md`
- `modified` `docs/integrations/ai-recommendation-template.md`
- `untracked` `docs/integrations/artifact-catalog.md`
- `tracked` `docs/integrations/bookmarklet.md`
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
- `modified` `dxt/README.md`
- `tracked` `dxt/icon.png`
- `modified` `dxt/manifest.json`
- `modified` `mcp-server.composition.json`
- `modified` `mcp-server.core.json`
- `modified` `mcp-server.full.json`
- `modified` `mcp-server.json`
- `modified` `sdk/.gitignore`
- `modified` `sdk/README.md`
- `tracked` `sdk/agents/LICENSE`
- `modified` `sdk/agents/README.md`
- `tracked` `sdk/agents/examples/due_diligence.ts`
- `tracked` `sdk/agents/examples/invoice_check.ts`
- `tracked` `sdk/agents/examples/kessan_brief.ts`
- `tracked` `sdk/agents/examples/law_amendment_watch.ts`
- `tracked` `sdk/agents/examples/subsidy_match.ts`
- `modified` `sdk/agents/package-lock.json`
- `tracked` `sdk/agents/package.json`
- `tracked` `sdk/agents/src/agents/due_diligence.ts`
- `tracked` `sdk/agents/src/agents/invoice_check.ts`
- `tracked` `sdk/agents/src/agents/kessan_brief.ts`
- `tracked` `sdk/agents/src/agents/law_amendment_watch.ts`
- `tracked` `sdk/agents/src/agents/subsidy_match.ts`
- `modified` `sdk/agents/src/index.ts`
- `modified` `sdk/agents/src/lib/jpcite_client.ts`
- `tracked` `sdk/agents/tsconfig.json`
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
- `tracked` `sdk/chrome-extension/README.md`
- `tracked` `sdk/chrome-extension/background.js`
- ... `193` more

### Customer Output Surfaces

- value: API/MCP/doc assets that can return concrete practitioner outputs instead of generic LLM advice.
- action: Bundle by persona and prove each surface with acceptance queries.
- risk: Public/paywalled boundaries, citation quality, and quota behavior must be checked before promotion.

- `modified` `docs/api-reference.md`
- `modified` `docs/mcp-tools.md`
- `untracked` `src/jpintel_mcp/api/artifacts.py`
- `untracked` `src/jpintel_mcp/api/calculator.py`
- `untracked` `src/jpintel_mcp/api/eligibility_predicate.py`
- `modified` `src/jpintel_mcp/api/evidence.py`
- `untracked` `src/jpintel_mcp/api/evidence_batch.py`
- `modified` `src/jpintel_mcp/api/funding_stack.py`
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
- `modified` `src/jpintel_mcp/api/intelligence.py`
- `untracked` `src/jpintel_mcp/api/narrative.py`
- `untracked` `src/jpintel_mcp/api/narrative_report.py`
- `untracked` `src/jpintel_mcp/api/wave24_endpoints.py`
- `untracked` `src/jpintel_mcp/mcp/autonomath_tools/eligibility_predicate_tool.py`
- `untracked` `src/jpintel_mcp/mcp/autonomath_tools/evidence_batch.py`
- `tracked` `src/jpintel_mcp/mcp/autonomath_tools/evidence_packet_tools.py`
- `untracked` `src/jpintel_mcp/mcp/autonomath_tools/intel_wave31.py`
- `untracked` `src/jpintel_mcp/mcp/autonomath_tools/intel_wave32.py`
- `untracked` `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py`
- `untracked` `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py`

### Data Foundation

- value: Tables, ETL, and cron jobs that make jpcite cheaper and more useful than ad-hoc web research.
- action: Convert raw joins into stable derived tables and documented refresh jobs.
- risk: Migrations, destructive rebuilds, and source-license constraints need review before production runs.

- `tracked` `data/autonomath_static/MANIFEST.md`
- `tracked` `data/autonomath_static/agri/crop_library.json`
- `tracked` `data/autonomath_static/agri/exclusion_rules.json`
- `tracked` `data/autonomath_static/dealbreakers.json`
- `tracked` `data/autonomath_static/example_profiles/A_ichigo_20a.json`
- `tracked` `data/autonomath_static/example_profiles/D_rice_200a.json`
- `tracked` `data/autonomath_static/example_profiles/J_new_corp.json`
- `tracked` `data/autonomath_static/example_profiles/N_minimal.json`
- `tracked` `data/autonomath_static/example_profiles/Q_dairy_100head.json`
- `tracked` `data/autonomath_static/example_profiles/README.md`
- `tracked` `data/autonomath_static/example_profiles/bc666_plan_map.yml`
- `tracked` `data/autonomath_static/glossary.json`
- `tracked` `data/autonomath_static/money_types.json`
- `tracked` `data/autonomath_static/obligations.json`
- `tracked` `data/autonomath_static/sector_combos.json`
- `tracked` `data/autonomath_static/seido.json`
- `tracked` `data/autonomath_static/templates/36_kyotei_template.txt`
- `tracked` `data/hallucination_guard.yaml`
- `tracked` `scripts/cron/ingest_nta_corpus_incremental.py`
- `tracked` `scripts/cron/ingest_nta_invoice_bulk.py`
- `untracked` `scripts/cron/ingest_offline_inbox.py`
- `untracked` `scripts/cron/meta_analysis_daily.py`
- `untracked` `scripts/cron/populate_program_calendar_12mo.py`
- `untracked` `scripts/cron/precompute_actionable_answers.py`
- `untracked` `scripts/cron/precompute_actionable_cache.py`
- `untracked` `scripts/cron/precompute_data_quality.py`
- `untracked` `scripts/cron/precompute_recommended_programs.py`
- `tracked` `scripts/cron/precompute_refresh.py`
- `tracked` `scripts/cron/refresh_amendment_diff.py`
- `untracked` `scripts/cron/refresh_amendment_diff_history.py`
- `tracked` `scripts/etl/analyze_source_verification_logs.py`
- `tracked` `scripts/etl/audit_known_gaps_inventory.py`
- `untracked` `scripts/etl/auto_tag_program_jsic.py`
- `tracked` `scripts/etl/backfill_am_source_content_hash.py`
- `tracked` `scripts/etl/backfill_am_source_last_verified.py`
- `tracked` `scripts/etl/backfill_amendment_diff_from_snapshots.py`
- `tracked` `scripts/etl/backfill_estat_fact_provenance.py`
- `tracked` `scripts/etl/backfill_missing_authorities.py`
- `tracked` `scripts/etl/backfill_program_aliases_json.py`
- `tracked` `scripts/etl/backfill_program_fact_source_ids.py`
- `tracked` `scripts/etl/backfill_program_locality_metadata.py`
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
- `tracked` `scripts/etl/close_stale_application_rounds.py`
- `tracked` `scripts/etl/corporate_bulk_preflight.py`
- `tracked` `scripts/etl/enrich_court_decisions_excerpt.py`
- `tracked` `scripts/etl/export_hf_embeddings.py`
- `tracked` `scripts/etl/export_license_review_queue.py`
- `tracked` `scripts/etl/export_placeholder_amount_review.py`
- `untracked` `scripts/etl/extract_eligibility_predicate.py`
- `tracked` `scripts/etl/fetch_egov_law_fulltext_batch.py`
- `tracked` `scripts/etl/fix_subsidy_rate_text_values.py`
- ... `308` more

### Trust And Quality Proof

- value: Benchmarks, smoke tests, evals, monitoring, and release gates that can prove reliability.
- action: Publish only conservative summaries; keep raw fixtures and internal gates as support.
- risk: Overclaiming token savings, speedups, or success rates can create marketing and trust risk.

- `untracked` `benchmarks/README.md`
- `untracked` `benchmarks/composite_vs_naive/README.md`
- `untracked` `benchmarks/composite_vs_naive/results.jsonl`
- `untracked` `benchmarks/composite_vs_naive/run.py`
- `untracked` `benchmarks/composite_vs_naive/summary.md`
- `tracked` `benchmarks/japanese_subsidy_rag/PR_TEMPLATE.md`
- `tracked` `benchmarks/japanese_subsidy_rag/README.md`
- `tracked` `benchmarks/japanese_subsidy_rag/baseline_scores.md`
- `tracked` `benchmarks/japanese_subsidy_rag/examples.jsonl`
- `tracked` `benchmarks/japanese_subsidy_rag/helm_format.json`
- `tracked` `benchmarks/japanese_subsidy_rag/task.json`
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
- `tracked` `monitoring/sentry_alert_rules.yml`
- `tracked` `monitoring/sentry_dashboard.json`
- `tracked` `monitoring/seo_metrics.md`
- `tracked` `monitoring/sla_targets.md`
- `untracked` `monitoring/sla_targets.yaml`
- `tracked` `monitoring/uptime_metrics_endpoint.md`
- `tracked` `tests/eval/README.md`
- `tracked` `tests/eval/__init__.py`
- `tracked` `tests/eval/conftest.py`
- `untracked` `tests/eval/practitioner_output_acceptance_queries_2026-05-06.jsonl`
- `tracked` `tests/eval/run_eval.py`
- `tracked` `tests/eval/test_tier_a_seeds.py`
- `tracked` `tests/eval/tier_a_seed.yaml`
- `tracked` `tests/eval/tier_b_template.py`
- `tracked` `tests/eval/tier_c_adversarial.yaml`
- `tracked` `tests/smoke/pre_launch_2026_04_24.md`
- `tracked` `tests/smoke/smoke_pre_launch.py`
- `untracked` `tests/smoke/verify_120_tools.py`
- `untracked` `tests/test_practitioner_output_acceptance_queries.py`
- `untracked` `tests/test_pre_deploy_verify.py`
- `untracked` `tests/test_production_improvement_preflight.py`
- `untracked` `tests/test_production_smoke_3axis.py`
- `untracked` `tests/test_release_readiness.py`

### Operator Research To Product

- value: Large research loops that can become roadmaps, packs, source matrices, and internal playbooks.
- action: Promote compact rollups and repeatable prompts; keep raw run output ignored.
- risk: Raw research may contain unverified claims, duplicated findings, or third-party rights constraints.

- `tracked` `docs/_internal/_archive/2026-04/ministry_source_audit_2026-04-29.md`
- `tracked` `docs/_internal/_archive/2026-04/value_maximization_plan_no_llm_api.md`
- `untracked` `docs/_internal/ai_professional_public_layer_implementation_blueprint_2026-05-06.md`
- `untracked` `docs/_internal/ai_professional_public_layer_plan_2026-05-06.md`
- `untracked` `docs/_internal/bpo_shigyo_paid_value_plan_2026-05-06.md`
- `tracked` `docs/_internal/capacity_plan.md`
- `tracked` `docs/_internal/fallback_plan.md`
- `untracked` `docs/_internal/info_collection_cli_latest_implementation_handoff_2026-05-06.md`
- `tracked` `docs/_internal/jpcite_ai_discovery_paid_adoption_plan_2026-05-04.md`
- `tracked` `docs/_internal/jpcite_user_value_execution_plan_2026-05-03.md`
- `tracked` `docs/_internal/llm_resilient_business_plan_2026-04-30.md`
- `untracked` `docs/_internal/main_implementation_preparation_2026-05-06.md`
- `untracked` `docs/_internal/practitioner_output_catalog_2026-05-06.md`
- `untracked` `docs/_internal/public_source_foundation_reingest_plan_2026-05-06.md`
- `untracked` `docs/_internal/repo_value_assets_latest.md`
- `untracked` `docs/_internal/source_foundation_triage_2026-05-06.md`
- `tracked` `docs/_internal/templates/data_correction_source_needed.md`
- `untracked` `docs/_internal/value_productization_queue_2026-05-06.md`
- `untracked` `tools/offline/INFO_COLLECTOR_LOOP.md`
- `untracked` `tools/offline/INFO_COLLECTOR_LOOP_B.md`
- `untracked` `tools/offline/INFO_COLLECTOR_LOOP_C.md`
- `untracked` `tools/offline/INFO_COLLECTOR_OUTPUT_MARKET_2026-05-06.md`
- `untracked` `tools/offline/INFO_COLLECTOR_PUBLIC_SOURCES_2026-05-06.md`
- `untracked` `tools/offline/INFO_COLLECTOR_VALUE_GROWTH_2026-05-06.md`
- `untracked` `tools/offline/INFO_COLLECTOR_VALUE_GROWTH_DUAL_CLI_300_AGENTS_2026-05-06.md`

### Public Conversion Copy

- value: Docs, pages, examples, and launch collateral that can turn discovered value into paid usage.
- action: Tie each page to one concrete artifact, benchmark, or first-hop integration path.
- risk: Copy must avoid unsupported superiority, speed, savings, or legal-advice claims.

- `modified` `README.md`
- `tracked` `docs/blog/2026-05-06-launch-day-developer.md`
- `tracked` `docs/blog/2026-05-06-launch-day-mcp-agent.md`
- `modified` `docs/blog/2026-05-5_audience_pitch.md`
- `tracked` `docs/blog/2026-05-architecture.md`
- `modified` `docs/blog/2026-05-launch-intro.md`
- `modified` `docs/getting-started.md`
- `modified` `docs/index.md`
- `modified` `docs/launch/README.md`
- `modified` `docs/launch/devto.md`
- `modified` `docs/launch/hn.md`
- `modified` `docs/launch/lobsters.md`
- `tracked` `docs/launch/note_com.md`
- `modified` `docs/launch/reddit_claudeai.md`
- `modified` `docs/launch/reddit_entrepreneur.md`
- `tracked` `docs/launch/reddit_japan.md`
- `tracked` `docs/launch/reddit_japanfinance.md`
- `modified` `docs/launch/reddit_localllama.md`
- `modified` `docs/launch/reddit_programming.md`
- `modified` `docs/launch/reddit_sideproject.md`
- `modified` `docs/launch/twitter_x_thread.md`
- `tracked` `docs/launch_assets/email_first_500.md`
- `modified` `docs/launch_assets/hn_show_post.md`
- `modified` `docs/launch_assets/linkedin_post.md`
- `modified` `docs/launch_assets/reddit_post.md`
- `modified` `docs/launch_assets/twitter_thread.md`
- `modified` `docs/launch_assets/x_thread_thread.md`
- `modified` `docs/launch_assets/zenn_intro_published.md`
- `modified` `docs/press_kit.md`
- `modified` `docs/pricing.md`
- `modified` `docs/roadmap.md`
- `tracked` `site/audiences/admin-scrivener.html`
- `tracked` `site/audiences/construction.html`
- `modified` `site/audiences/dev.html`
- `tracked` `site/audiences/index.html`
- `tracked` `site/audiences/journalist.html`
- `tracked` `site/audiences/manufacturing.html`
- `tracked` `site/audiences/real_estate.html`
- `modified` `site/audiences/shinkin.html`
- `modified` `site/audiences/shokokai.html`
- `tracked` `site/audiences/smb.html`
- `tracked` `site/audiences/subsidy-consultant.html`
- `tracked` `site/audiences/tax-advisor.html`
- `tracked` `site/audiences/vc.html`
- `tracked` `site/en/audiences/admin-scrivener.html`
- `modified` `site/en/audiences/dev.html`
- `modified` `site/en/audiences/foreign-investor.html`
- `modified` `site/en/audiences/index.html`
- `tracked` `site/en/audiences/smb.html`
- `modified` `site/en/audiences/tax-advisor.html`
- `modified` `site/en/audiences/vc.html`
- `tracked` `site/en/widget/demo.html`
- `modified` `site/index.html`
- `modified` `site/pricing.html`
- `tracked` `site/qa/bcp-plan/index.html`
- `tracked` `site/qa/bcp-plan/overview.html`
- `tracked` `site/qa/chinage-tax/index.html`
- `tracked` `site/qa/chinage-tax/overview.html`
- `tracked` `site/qa/chinage-tax/sme-requirements.html`
- `tracked` `site/qa/dencho/electronic-transactions.html`
- ... `101` more

