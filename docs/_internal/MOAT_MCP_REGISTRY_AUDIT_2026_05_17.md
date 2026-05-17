# MOAT MCP Registry Audit — D3 (2026-05-17)

Read-only audit of the FastMCP tool registry. Cross-checks the moat lane (M1-M11 + N1-N9 = 32 tools) against the live registry to detect name collisions, duplicate registrations, naming convention drift, and orphan modules.

## Headline numbers

| metric | value |
|---|---|
| Live runtime tool count (`await mcp.list_tools()`) | **216** |
| Moat lane tools (M1-M11 + N1-N9 + N10 wrappers) | **32** |
| Pre-existing core tools | **184** |
| New-collision count (moat × core) | **0** |
| Duplicate `@mcp.tool` definitions in source | **3** (orphan files) |
| Duplicate live registrations | **0** |
| Naming convention violations on moat | **0** |
| mypy --strict (moat_lane_tools/) | **0 errors** |
| ruff (src/jpintel_mcp/mcp/) | **0 errors** |

Source-of-truth invocation:

```bash
.venv/bin/python -c "import asyncio; from jpintel_mcp.mcp.server import mcp; print(len(asyncio.run(mcp.list_tools())))"
# → 216
```

## Collision detect

All 32 moat-lane tool names are surfaced in the live registry exactly once. **No collision with pre-existing core tools.**

| moat tool | live? | source file |
|---|---|---|
| `get_artifact_template` | LIVE | `moat_lane_tools/moat_n1_artifact.py` |
| `list_artifact_templates` | LIVE | `moat_lane_tools/moat_n1_artifact.py` |
| `get_houjin_portfolio` | LIVE | `moat_lane_tools/moat_n2_portfolio.py` |
| `find_gap_programs` | LIVE | `moat_lane_tools/moat_n2_portfolio.py` |
| `get_reasoning_chain` | LIVE | `moat_lane_tools/moat_n3_reasoning.py` |
| `walk_reasoning_chain` | LIVE | `moat_lane_tools/moat_n3_reasoning.py` |
| `find_filing_window` | LIVE | `moat_lane_tools/moat_n4_window.py` |
| `list_windows` | LIVE | `moat_lane_tools/moat_n4_window.py` |
| `resolve_alias` | LIVE | `moat_lane_tools/moat_n5_synonym.py` |
| `list_pending_alerts` | LIVE | `moat_lane_tools/moat_n6_alert.py` |
| `get_alert_detail` | LIVE | `moat_lane_tools/moat_n6_alert.py` |
| `ack_alert` | LIVE | `moat_lane_tools/moat_n6_alert.py` |
| `get_segment_view` | LIVE | `moat_lane_tools/moat_n7_segment.py` |
| `segment_summary` | LIVE | `moat_lane_tools/moat_n7_segment.py` |
| `list_recipes` | LIVE | `moat_lane_tools/moat_n8_recipe.py` |
| `get_recipe` | LIVE | `moat_lane_tools/moat_n8_recipe.py` |
| `resolve_placeholder` | LIVE | `moat_lane_tools/moat_n9_placeholder.py` |
| `extract_kg_from_text` | LIVE | `moat_lane_tools/moat_m1_kg.py` |
| `get_entity_relations` | LIVE | `moat_lane_tools/moat_m1_kg.py` |
| `search_case_facts` | LIVE | `moat_lane_tools/moat_m2_case.py` |
| `get_case_extraction` | LIVE | `moat_lane_tools/moat_m2_case.py` |
| `search_figures_by_topic` | LIVE | `moat_lane_tools/moat_m3_figure.py` |
| `get_figure_caption` | LIVE | `moat_lane_tools/moat_m3_figure.py` |
| `semantic_search_law_articles` | LIVE | `moat_lane_tools/moat_m4_law_embed.py` |
| `jpcite_bert_v1_encode` | LIVE | `moat_lane_tools/moat_m5_simcse.py` |
| `rerank_results` | LIVE | `moat_lane_tools/moat_m6_cross_encoder.py` |
| `predict_related_entities` | LIVE | `moat_lane_tools/moat_m7_kg_completion.py` |
| `find_cases_citing_law` | LIVE | `moat_lane_tools/moat_m8_citation.py` |
| `find_laws_cited_by_case` | LIVE | `moat_lane_tools/moat_m8_citation.py` |
| `search_chunks` | LIVE | `moat_lane_tools/moat_m9_chunks.py` |
| `opensearch_hybrid_search` | LIVE | `autonomath_tools/opensearch_hybrid_tools.py` (M10 deliberately registered in autonomath_tools; `moat_lane_tools/moat_m10_opensearch.py` is a documented no-op stub) |
| `multitask_predict` | LIVE | `moat_lane_tools/moat_m11_multitask.py` |

**Collision count: 0.** N6 carries 3 tools (not 2), so total moat = 32 not 31.

## Duplicate `@mcp.tool` source definitions (orphan files)

Three tool functions appear in **two** modules each. Live registry has only one entry for each — so the duplicates are dead code, not double-registration. Both autonomath_tools copies are never imported.

| tool | live source | orphan source |
|---|---|---|
| `get_recipe` | `moat_lane_tools/moat_n8_recipe.py` | `autonomath_tools/moat_n8_recipe.py` |
| `list_recipes` | `moat_lane_tools/moat_n8_recipe.py` | `autonomath_tools/moat_n8_recipe.py` |
| `resolve_placeholder` | `moat_lane_tools/moat_n9_placeholder.py` | `autonomath_tools/moat_n9_placeholder.py` |

The orphan files are reachable on disk but not imported via `autonomath_tools/__init__.py` and not transitively referenced from any source file (verified via `grep -rn "moat_n8_recipe\|moat_n9_placeholder"`). They sit dormant — runtime impact is zero, but they are a `git mv` waiting to happen (recommend removal in a follow-up cleanup tick).

## Registration source of truth

`src/jpintel_mcp/mcp/server.py:9659-9691` (paraphrased):

```python
if settings.autonomath_enabled:
    mcp.tool = _mcp_tool_with_envelope  # monkey-patch for telemetry+envelope
    try:
        from jpintel_mcp.mcp import (
            autonomath_tools,    # ~140 tools register on import
            moat_lane_tools,     # 31 tools register on import (M10 no-op)
        )
    finally:
        mcp.tool = _orig_mcp_tool
```

Import order is **autonomath_tools first, moat_lane_tools second**. Because `mcp.tool` keys by name and FastMCP rejects duplicate keys (`opensearch_hybrid_search` is M10 — the moat_lane_tools file is a deliberate no-op precisely for this reason), order matters only at the M10 seam, which is handled.

`moat_lane_tools/__init__.py` iterates `_SUBMODULES` (M1..M11 + N1..N9 = 20 entries) and `importlib.import_module`s each. Missing submodules log-and-skip silently (intentional, for partial-checkout robustness). M10 is in the tuple but its module body is empty.

## Naming convention check

Top prefixes across the full 216 registry:

| prefix | count |
|---|---|
| `get_*` | 30 |
| `search_*` | 24 |
| `list_*` | 12 |
| `find_*` | 10 |
| `outcome_*` | 10 |
| `program_*` | 10 |

Moat-only prefixes (32 tools):

| prefix | count |
|---|---|
| `get_*` | 9 |
| `list_*` | 4 |
| `find_*` | 4 |
| `search_*` | 3 |
| `resolve_*` | 2 |
| `walk_*` / `ack_*` / `segment_*` / `extract_*` / `semantic_*` / `jpcite_*` / `rerank_*` / `predict_*` / `opensearch_*` / `multitask_*` | 1 each |

All moat names follow the established `<verb>_<noun>` convention, all are snake_case, none collide with reserved suffixes (`_am` / `_chain` / `_composed` are kept exclusively for the pre-existing autonomath / chain / composed cohorts). **Naming convention violations: 0.**

Suffix tally for context:

- `*_am`: 52 (autonomath-DB-backed)
- `*_chain`: 14 (composed chains)
- `*_composed`: 4 (Wave 21 composition)

## Full live registry (216)

| # | Tool | Lane |
|---|------|------|
| 1 | `ack_alert` | moat |
| 2 | `active_programs_at` | core |
| 3 | `alliance_opportunities_am` | core |
| 4 | `anonymized_aggregate_query` | core |
| 5 | `anonymized_cohort_query_with_redact_chain` | core |
| 6 | `apply_eligibility_chain_am` | core |
| 7 | `audit_batch_evaluate` | core |
| 8 | `batch_get_programs` | core |
| 9 | `benchmark_cohort_average_am` | core |
| 10 | `bid_eligible_for_profile` | core |
| 11 | `bundle_application_kit` | core |
| 12 | `case_cohort_match_am` | core |
| 13 | `cases_by_industry_size_pref` | core |
| 14 | `cases_timeline_trend_am` | core |
| 15 | `check_enforcement_am` | core |
| 16 | `check_exclusions` | core |
| 17 | `check_funding_stack_am` | core |
| 18 | `cite_tsutatsu` | core |
| 19 | `combined_compliance_check` | core |
| 20 | `compose_audit_workpaper` | core |
| 21 | `compose_audit_workpaper_v2` | core |
| 22 | `counterfactual_diff_v2` | core |
| 23 | `cross_check_jurisdiction` | core |
| 24 | `dd_profile_am` | core |
| 25 | `deadline_calendar` | core |
| 26 | `deep_health_am` | core |
| 27 | `disaster_catalog` | core |
| 28 | `discover_related` | core |
| 29 | `dynamic_eligibility_check_am` | core |
| 30 | `eligibility_audit_workpaper_composed` | core |
| 31 | `enum_values` | core |
| 32 | `enum_values_am` | core |
| 33 | `evaluate_tax_applicability` | core |
| 34 | `evidence_with_provenance_chain` | core |
| 35 | `extract_kg_from_text` | moat |
| 36 | `fact_signature_verify_am` | core |
| 37 | `federated_handoff_with_audit_chain` | core |
| 38 | `find_bunsho_kaitou` | core |
| 39 | `find_cases_by_law` | core |
| 40 | `find_cases_citing_law` | moat |
| 41 | `find_complementary_programs_am` | core |
| 42 | `find_filing_window` | moat |
| 43 | `find_gap_programs` | moat |
| 44 | `find_laws_cited_by_case` | moat |
| 45 | `find_precedents_by_statute` | core |
| 46 | `find_saiketsu` | core |
| 47 | `find_shitsugi` | core |
| 48 | `forecast_program_renewal` | core |
| 49 | `foreign_fdi_country_am` | core |
| 50 | `foreign_fdi_list_am` | core |
| 51 | `get_alert_detail` | moat |
| 52 | `get_am_tax_rule` | core |
| 53 | `get_annotations` | core |
| 54 | `get_artifact_template` | moat |
| 55 | `get_bid` | core |
| 56 | `get_case_extraction` | moat |
| 57 | `get_case_study` | core |
| 58 | `get_court_decision` | core |
| 59 | `get_enforcement_case` | core |
| 60 | `get_entity_relations` | moat |
| 61 | `get_evidence_packet` | core |
| 62 | `get_example_profile_am` | core |
| 63 | `get_figure_caption` | moat |
| 64 | `get_houjin_360_am` | core |
| 65 | `get_houjin_portfolio` | moat |
| 66 | `get_law` | core |
| 67 | `get_law_article_am` | core |
| 68 | `get_loan_program` | core |
| 69 | `get_meta` | core |
| 70 | `get_program` | core |
| 71 | `get_provenance` | core |
| 72 | `get_provenance_for_fact` | core |
| 73 | `get_pubcomment_status` | core |
| 74 | `get_reasoning_chain` | moat |
| 75 | `get_recipe` | moat |
| 76 | `get_segment_view` | moat |
| 77 | `get_source_manifest` | core |
| 78 | `get_static_resource_am` | core |
| 79 | `get_tax_rule` | core |
| 80 | `get_usage_status` | core |
| 81 | `graph_traverse` | core |
| 82 | `graph_vec_search_am` | core |
| 83 | `houjin_invoice_status` | core |
| 84 | `houjin_risk_score_am` | core |
| 85 | `invoice_compatibility_check_composed` | core |
| 86 | `invoice_risk_batch` | core |
| 87 | `invoice_risk_lookup` | core |
| 88 | `jpcite_bert_v1_encode` | moat |
| 89 | `jpcite_execute_packet` | core |
| 90 | `jpcite_get_packet` | core |
| 91 | `jpcite_preview_cost` | core |
| 92 | `jpcite_route` | core |
| 93 | `law_related_programs_cross` | core |
| 94 | `list_active_disaster_programs` | core |
| 95 | `list_artifact_templates` | moat |
| 96 | `list_edinet_disclosures` | core |
| 97 | `list_example_profiles_am` | core |
| 98 | `list_exclusion_rules` | core |
| 99 | `list_law_revisions` | core |
| 100 | `list_open_programs` | core |
| 101 | `list_pending_alerts` | moat |
| 102 | `list_recipes` | moat |
| 103 | `list_static_resources_am` | core |
| 104 | `list_tax_sunset_alerts` | core |
| 105 | `list_windows` | moat |
| 106 | `ma_due_diligence_pack_composed` | core |
| 107 | `match_cohort_5d_am` | core |
| 108 | `match_disaster_programs` | core |
| 109 | `match_due_diligence_questions` | core |
| 110 | `match_programs_by_funding_stage_am` | core |
| 111 | `match_succession_am` | core |
| 112 | `multitask_predict` | moat |
| 113 | `opensearch_hybrid_search` | moat |
| 114 | `outcome_acceptance_probability` | core |
| 115 | `outcome_bid_announcement_seasonality` | core |
| 116 | `outcome_cross_prefecture_arbitrage` | core |
| 117 | `outcome_enforcement_seasonal_trend` | core |
| 118 | `outcome_houjin_360` | core |
| 119 | `outcome_prefecture_program_heatmap` | core |
| 120 | `outcome_program_lineage` | core |
| 121 | `outcome_regulatory_q_over_q_diff` | core |
| 122 | `outcome_succession_event_pulse` | core |
| 123 | `outcome_tax_ruleset_phase_change` | core |
| 124 | `pack_construction` | core |
| 125 | `pack_manufacturing` | core |
| 126 | `pack_real_estate` | core |
| 127 | `policy_upstream_timeline` | core |
| 128 | `policy_upstream_watch` | core |
| 129 | `portfolio_optimize_am` | core |
| 130 | `portfolio_optimize_precomputed_am` | core |
| 131 | `predict_related_entities` | moat |
| 132 | `predictive_subscriber_fanout_chain` | core |
| 133 | `prepare_kessan_briefing` | core |
| 134 | `prerequisite_chain` | core |
| 135 | `prescreen_programs` | core |
| 136 | `program_abstract_structured` | core |
| 137 | `program_active_periods_am` | core |
| 138 | `program_compatibility_pair_am` | core |
| 139 | `program_eligibility_by_form_am` | core |
| 140 | `program_eligibility_for_houjin_am` | core |
| 141 | `program_forecast_30yr_am` | core |
| 142 | `program_full_context` | core |
| 143 | `program_lifecycle` | core |
| 144 | `program_risk_score_am` | core |
| 145 | `program_timeline_am` | core |
| 146 | `programs_by_corporate_form_am` | core |
| 147 | `programs_by_region_am` | core |
| 148 | `query_at_snapshot_v2` | core |
| 149 | `query_program_evolution` | core |
| 150 | `query_snapshot_as_of_v2` | core |
| 151 | `recommend_partner_for_gap` | core |
| 152 | `recommend_similar_case` | core |
| 153 | `recommend_similar_court_decision` | core |
| 154 | `recommend_similar_program` | core |
| 155 | `region_coverage_am` | core |
| 156 | `regulatory_prep_pack` | core |
| 157 | `related_programs` | core |
| 158 | `rerank_results` | moat |
| 159 | `resolve_alias` | moat |
| 160 | `resolve_citation_chain` | core |
| 161 | `resolve_placeholder` | moat |
| 162 | `rule_engine_check` | core |
| 163 | `rule_tree_batch_eval_chain` | core |
| 164 | `search_acceptance_stats_am` | core |
| 165 | `search_bids` | core |
| 166 | `search_by_law` | core |
| 167 | `search_case_facts` | moat |
| 168 | `search_case_studies` | core |
| 169 | `search_certifications` | core |
| 170 | `search_chunks` | moat |
| 171 | `search_court_decisions` | core |
| 172 | `search_enforcement_cases` | core |
| 173 | `search_figures_by_topic` | moat |
| 174 | `search_gx_programs_am` | core |
| 175 | `search_invoice_by_houjin_partial` | core |
| 176 | `search_invoice_registrants` | core |
| 177 | `search_kokkai_utterance` | core |
| 178 | `search_laws` | core |
| 179 | `search_loan_programs` | core |
| 180 | `search_loans_am` | core |
| 181 | `search_municipality_subsidies` | core |
| 182 | `search_mutual_plans_am` | core |
| 183 | `search_programs` | core |
| 184 | `search_regions_am` | core |
| 185 | `search_shingikai_minutes` | core |
| 186 | `search_tax_incentives` | core |
| 187 | `search_tax_rules` | core |
| 188 | `segment_summary` | moat |
| 189 | `semantic_search_am` | core |
| 190 | `semantic_search_law_articles` | moat |
| 191 | `semantic_search_legacy_am` | core |
| 192 | `semantic_search_v2_am` | core |
| 193 | `session_aware_eligibility_check_chain` | core |
| 194 | `session_multi_step_eligibility_chain` | core |
| 195 | `shihoshoshi_dd_pack_am` | core |
| 196 | `sign_fact` | core |
| 197 | `similar_cases` | core |
| 198 | `simulate_application_am` | core |
| 199 | `smb_starter_pack` | core |
| 200 | `subsidy_combo_finder` | core |
| 201 | `subsidy_eligibility_full_composed` | core |
| 202 | `subsidy_roadmap_3yr` | core |
| 203 | `succession_playbook_am` | core |
| 204 | `supplier_chain_am` | core |
| 205 | `tax_rule_full_chain` | core |
| 206 | `temporal_compliance_audit_chain` | core |
| 207 | `time_machine_snapshot_walk_chain` | core |
| 208 | `trace_program_to_law` | core |
| 209 | `track_amendment_lineage_am` | core |
| 210 | `unified_lifecycle_calendar` | core |
| 211 | `upcoming_deadlines` | core |
| 212 | `upcoming_rounds_for_my_profile_am` | core |
| 213 | `validate` | core |
| 214 | `verify_citations` | core |
| 215 | `verify_fact` | core |
| 216 | `walk_reasoning_chain` | moat |

## Recommendations (non-blocking, for future tick)

1. **Delete orphan files** (`autonomath_tools/moat_n8_recipe.py`, `autonomath_tools/moat_n9_placeholder.py`) — 2 unused implementations. Live tool count unaffected; reduces source-of-truth ambiguity.
2. **Document M10 seam** in `moat_lane_tools/__init__.py` docstring — the deliberate no-op currently relies on the `moat_m10_opensearch.py` module docstring, which is correct but easy to miss when iterating the catalogue.
3. **Hold-at-184 core / 32 moat split** for the next manifest bump — current `tool_count` in `pyproject.toml` / `server.json` / `dxt/manifest.json` / `smithery.yaml` should be reconciled to **216** at the next intentional release.

last_updated: 2026-05-17
