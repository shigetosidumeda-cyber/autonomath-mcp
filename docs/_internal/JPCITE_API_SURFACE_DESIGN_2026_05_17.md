# jpcite API Surface Design — F3 (2026-05-17)

> **Audit-only**: READ-ONLY enumeration of every `@mcp.tool` registration across
> `src/jpintel_mcp/mcp/server.py` + `mcp/autonomath_tools/` + `mcp/healthcare_tools/`
> + `mcp/real_estate_tools/` + `mcp/moat_lane_tools/` as of HEAD (`main`)
> 2026-05-17. Snapshot is post-Moat-N (`MOAT_INTEGRATION_MAP_2026_05_17.md`)
> +Wave 59-B outcome wrappers +Wave 51 dim K-S +HE-1/2/3/4 heavy endpoints.
> The 216-tool count from `MOAT_INTEGRATION_MAP_2026_05_17.md`
> ("184 baseline + 32 moat") is the user-snapshot anchor; today's distinct count
> is **284** (extra +68 = Wave 59-B outcome×10 + Wave 51 chains + intel_wave32
> +7 + wave24 first/second half +24 + a handful of healthcare/real_estate stubs).
> Per CLAUDE.md SOT note this doc is **additive**; historical
> 139/146/155/179/184/216 markers in CLAUDE.md and earlier moat docs remain
> authoritative for their respective snapshots.
>
> Extraction: static AST grep, no MCP server boot. Reproducer:
> `/tmp/classify_tools.py` (lives outside the repo tree on purpose — this is a
> design doc, not a generator).

## Executive summary

- **Distinct tool count**: **284** at default gates (server.py 45 +
  autonomath_tools 209 + healthcare_tools 6 + real_estate_tools 5 + moat_lane_tools 28
  − duplicate stubs in `moat_m10` already registered under
  `autonomath_tools/opensearch_hybrid_tools.py`).
- **216 baseline** = the user-facing surface anchor from
  `MOAT_INTEGRATION_MAP_2026_05_17.md` ("184 baseline + 32 moat"). The +68 above
  216 are post-Moat-N additions that have not yet been re-counted in a manifest
  bump.
- **4-layer taxonomy** (L1 atomic / L2 composed / L3 heavy_endpoint / L4 workflow):
  L1 = **171** / L2 = **56** / L3 = **4** / L4 = **53**. The target shape in the
  brief was 150/30/10/20; reality is heavier in L1 (over-decomposition) and
  heavier in L4 (intel_wave31/32 + outcome_wave59_b + wave51 chains created
  many small workflow-shaped tools) — see "Re-balance proposal" §.
- **L3 heavy_endpoints (the agent on-ramp)**: `agent_full_context` (HE-1) /
  `prepare_implementation_workpaper` (HE-2) / `agent_briefing_pack` (HE-3) /
  `multi_tool_orchestrate` (HE-4). All four are LIVE in
  `src/jpintel_mcp/mcp/moat_lane_tools/he{1,2,3,4}_*.py`.
- **Composability dead-ends**: **68 L1 atomics** (40% of L1) are never referenced
  by any L2/L3/L4 tool body. Not all are deletion candidates — many are
  legitimate stand-alone surfaces (e.g. region/foreign FDI / 36協定) — but each
  one is also an agent-discoverability tax that needs justification.

## 4-layer taxonomy

### L1 — atomic (171 tools)

Single-purpose search / get / list / find / walk / resolve / prepare / check /
lookup / probe primitives backed by one canonical SQLite query (or one
deterministic transform). 1 ¥3/req unit per call.

**Prefix distribution** (top 15, full inventory in `/tmp/tool_layers.json`):

| Prefix | Count | Examples |
| --- | --- | --- |
| `get_*` | 48 | `get_program`, `get_law`, `get_case_study`, `get_houjin_360_am`, `get_houjin_portfolio` |
| `search_*` | 30 | `search_programs`, `search_laws`, `search_bids`, `search_case_studies`, `search_court_decisions` |
| `intel_*` | 22 | `intel_match`, `intel_program_full`, `intel_houjin_full`, `intel_path`, `intel_timeline` |
| `find_*` | 17 | `find_precedents_by_statute`, `find_cases_by_law`, `find_saiketsu`, `find_filing_window` |
| `list_*` | 13 | `list_exclusion_rules`, `list_law_revisions`, `list_tax_sunset_alerts`, `list_open_programs` |
| `program_*` | 9 | `program_lifecycle`, `program_full_context`, `program_timeline_am`, `program_compatibility_pair_am` |
| `outcome_*` | 10 | `outcome_houjin_360`, `outcome_program_lineage`, `outcome_acceptance_probability` (these are L4, not L1 — counted under outcome_*) |
| `match_*` | 6 | `match_cohort_5d_am`, `match_due_diligence_questions`, `match_succession_am` |
| `check_*` | 5 | `check_exclusions`, `check_funding_stack_am`, `check_enforcement_am`, `check_drug_approval` |
| `recommend_*` | 5 | `recommend_similar_program`, `recommend_partner_for_gap`, `recommend_programs_for_houjin` |
| `jpcite_*` | 5 | P0 facade: `jpcite_route` / `jpcite_preview_cost` / `jpcite_execute_packet` / `jpcite_get_packet` / `jpcite_bert_v1_encode` |
| `semantic_*` | 4 | `semantic_search_am`, `semantic_search_v2_am`, `semantic_search_legacy_am`, `semantic_search_law_articles` |
| `dd_*` | 3 | `dd_profile_am`, `dd_medical_institution_am`, `dd_property_am` |
| `resolve_*` | 3 | `resolve_alias`, `resolve_placeholder`, `resolve_citation_chain` |

The convention is implicit but consistent enough that the four-character
prefixes `get_` / `search_` / `list_` / `find_` already cover 108 / 171
atomics (63%). Section "Prefix convention" below codifies it.

### L2 — composed (56 tools)

Tools that compose **2-5 L1 atomics** server-side. 1 ¥3/req unit per call.
Full inventory:

`find_precedents_by_statute`, `evaluate_tax_applicability`, `trace_program_to_law`,
`find_cases_by_law`, `combined_compliance_check`, `dynamic_eligibility_check_am`,
`program_eligibility_for_houjin_am`, `graph_traverse`, `fact_signature_verify_am`,
`benchmark_cohort_average_am`, `match_cohort_5d_am`, `houjin_360`,
`match_programs_by_funding_stage_am`, `program_lifecycle`, `match_succession_am`,
`find_combinable_programs`, `get_houjin_360_snapshot_history`,
`match_programs_by_capital`, `predict_rd_tax_credit`, `discover_related`,
`get_houjin_360_am`, `apply_eligibility_chain_am`,
`find_complementary_programs_am`, `simulate_application_am`,
`track_amendment_lineage_am`, `program_active_periods_am`,
`orchestrate_to_external_am`, `list_orchestrate_targets_am`,
`recommend_partner_for_gap`, `program_full_context`,
`law_related_programs_cross`, `cases_by_industry_size_pref`,
`policy_upstream_watch`, `anonymized_aggregate_query`, `rule_engine_check`,
`portfolio_optimize_am`, `program_compatibility_pair_am`,
`unified_lifecycle_calendar`, `jpcite_route`, `jpcite_preview_cost`,
`jpcite_execute_packet`, `jpcite_get_packet`, `case_cohort_match_am`,
`score_application_probability`, `get_compliance_risk_score`,
`find_complementary_subsidies`, `intel_portfolio_heatmap`, `invoice_risk_batch`,
`houjin_invoice_status`, `legal_chain_am`, `predict_related_entities`,
`jpcite_bert_v1_encode`, `rerank_results`, `get_houjin_portfolio`,
`find_gap_programs`, `multitask_predict`.

### L3 — heavy_endpoint (4 tools)

The "1-call complete" agent on-ramps. Each one absorbs **6-15 L1/L2 calls** into
a single MCP round trip with structured envelope output.

| ID | Tool | Module | Notes |
| --- | --- | --- | --- |
| HE-1 | `agent_full_context` | `moat_lane_tools/he1_full_context.py` | Full-context evidence packet for a single subject (houjin / program / law). Depth-scaled (1-5). |
| HE-2 | `prepare_implementation_workpaper` | `moat_lane_tools/he2_workpaper.py` | 監査ワークペーパー (PDF/CSV/MD) one-shot. §47条の2 + §52 envelope. |
| HE-3 | `agent_briefing_pack` | `moat_lane_tools/he3_briefing_pack.py` | Topic × 士業 segment briefing (current law + tsutatsu + judgment + pitfalls + next steps). Token-budget-aware. |
| HE-4 | `multi_tool_orchestrate` | `moat_lane_tools/he4_orchestrate.py` | Server-side parallel bundler. Up to 32 tool_calls in `asyncio.gather` with allowlist + denylist + recursion guard. ¥3 × N billing transparent. |

### L4 — workflow (53 tools)

Recipe / packet / outcome / chain / pack systems — each represents a complete
agent-facing answer rather than a primitive. Subcategories:

- **outcome_*** (10): `outcome_wave59_b.py` cohort — houjin_360 / program_lineage
  / acceptance_probability / tax_ruleset_phase_change / regulatory_q_over_q_diff
  / enforcement_seasonal_trend / bid_announcement_seasonality /
  succession_event_pulse / prefecture_program_heatmap / cross_prefecture_arbitrage.
- **wave51 chains (Stream B + chains)** (9): predictive_subscriber_fanout_chain
  / session_multi_step_eligibility_chain / rule_tree_batch_eval_chain /
  anonymized_cohort_query_with_redact_chain / time_machine_snapshot_walk_chain /
  evidence_with_provenance_chain / session_aware_eligibility_check_chain /
  federated_handoff_with_audit_chain / temporal_compliance_audit_chain.
- **wave51 dim P composed** (4): eligibility_audit_workpaper_composed /
  subsidy_eligibility_full_composed / ma_due_diligence_pack_composed /
  invoice_compatibility_check_composed.
- **wave22 composition** (5): match_due_diligence_questions / prepare_kessan_briefing
  / cross_check_jurisdiction / bundle_application_kit / forecast_program_renewal.
- **industry_packs** (3): pack_construction / pack_manufacturing / pack_real_estate.
- **smb/discovery one-shots** (5): smb_starter_pack / deadline_calendar /
  subsidy_combo_finder / subsidy_roadmap_3yr / regulatory_prep_pack.
- **dd packs** (4): dd_profile_am / dd_medical_institution_am / dd_property_am /
  shihoshoshi_dd_pack_am.
- **audit / citation** (3): compose_audit_workpaper / audit_batch_evaluate /
  resolve_citation_chain.
- **lifecycle / prerequisite / reasoning** (5): prerequisite_chain /
  get_reasoning_chain / walk_reasoning_chain / policy_upstream_timeline /
  tax_rule_full_chain.
- **misc**: succession_playbook_am, intel_audit_chain, intel_citation_pack,
  intel_onboarding_brief, get_recipe, list_recipes.

## Composability matrix

### L1 atomic usage histogram

Each L1 atomic is grep-counted against every L2/L3/L4 source body. Usage = "how
many higher-tier tools mention this atomic by name".

| Usage (# of L2+/L3/L4 consumers) | Number of L1 atomics |
| --- | --- |
| 0 (dead-end) | **68** |
| 1 | 14 |
| 2 | 12 |
| 3 | 22 |
| 4 | 6 |
| 7 | 8 |
| 14 | 23 |
| 15 | 4 |
| 16 | 2 |
| 17 | 2 |
| 18 | 1 |
| 19 | 2 |
| 20 | 2 |
| 21 | 3 |
| 22 | 1 |
| 52 | 1 |

### Top 15 most-composed L1 atomics

These are the "load-bearing" primitives; agents that learn just these get most
of jpcite's value.

| L1 atomic | Used by N higher-tier tools |
| --- | --- |
| `search_programs` | 52 |
| `validate` | 22 |
| `list_tax_sunset_alerts` | 21 |
| `list_open_programs` | 21 |
| `get_law_article_am` | 21 |
| `get_program` | 20 |
| `get_provenance` | 20 |
| `search_case_studies` | 19 |
| `check_enforcement_am` | 19 |
| `similar_cases` | 18 |
| `search_laws` | 17 |
| `search_tax_incentives` | 17 |
| `get_am_tax_rule` | 16 |
| `search_acceptance_stats_am` | 16 |
| `check_exclusions` | 15 |

These 15 atomics (8.8% of L1) participate in roughly half of all L2/L3/L4
bodies. They are the "core 15" that every agent integration should be aware of.

### Dead-end atomic inventory (68 — full list)

The following L1 atomics are not referenced anywhere in L2/L3/L4 source. Each
falls into one of four bins:

- **(K)** Keep — sole entry point for a 1次資料 surface that L2+/L3/L4 has not
  yet wrapped, but the surface is intentional (e.g. region / FDI / 36協定 / kgs).
- **(W)** Wrap — eligible for inclusion in an existing or new L2 composite.
- **(G)** Gate-rotate — gated-off by default; correct that they are absent
  from L2+.
- **(D)** Deprecation candidate — superseded by a v2 or a composed entry point.

| Tool | Bin | Reason |
| --- | --- | --- |
| `get_law` | W | Should appear inside `get_houjin_360_am` / `outcome_program_lineage` law lookups via id. |
| `get_bid` | W | Bids surface largely standalone; could fold into a future `procurement_pack`. |
| `query_snapshot_as_of_v2` | D | Superseded by `query_at_snapshot_v2` + `time_machine_snapshot_walk_chain`. |
| `counterfactual_diff_v2` | D | Wave 51 dim Q v2 — covered indirectly by `temporal_compliance_audit_chain`. |
| `recommend_similar_program` | W | Should be invoked from `discover_related` / `outcome_acceptance_probability`. |
| `recommend_similar_case` | W | Should appear in `outcome_acceptance_probability`. |
| `recommend_similar_court_decision` | W | Should appear in `law_related_programs_cross` (legal chain). |
| `get_static_resource_am` | K | Phase A static taxonomy probe — used by clients, not server. |
| `list_example_profiles_am` | K | Example profile catalogue — keep standalone. |
| `get_example_profile_am` | K | Same as above. |
| `resolve_alias` | W | Should be used inside `match_programs_by_*` cohort matchers. |
| `program_timeline_am` | W | Naturally folds into `outcome_program_lineage`. |
| `cases_timeline_trend_am` | W | Naturally folds into `outcome_acceptance_probability` / `outcome_enforcement_seasonal_trend`. |
| `upcoming_rounds_for_my_profile_am` | K | Client-side calendar surface. |
| `get_source_manifest` | K | Provenance probe; clients hit directly. |
| `get_evidence_packet` | K | Used by `jpcite_get_packet` indirectly (different code path). |
| `deep_health_am` | K | Health surface; intentional standalone. |
| `list_windows` | W | Should fold into `find_filing_window` callers. |
| `semantic_search_legacy_am` | D | Superseded by `semantic_search_v2_am` / `semantic_search_am`. |
| `sign_fact` | K | Wave 51 dim O Ed25519 — operator-side primitive. |
| `verify_fact` | W | Should appear inside `fact_signature_verify_am`. |
| `search_municipality_subsidies` | K | DEEP-44 1次資料 — intentionally a thin lookup. |
| `get_evidence_packet_batch` | K | Batch surface used by clients. |
| `search_laws_en` | K | English wedge — FDI cohort. |
| `get_law_article_en` | K | English wedge. |
| `get_tax_treaty` | K | English wedge. |
| `check_foreign_capital_eligibility` | W | Should fold into `find_fdi_friendly_subsidies`. |
| `find_fdi_friendly_subsidies` | K | Intentional FDI workflow entry. |
| `get_annotations` | W | V4 universal — should appear in `outcome_houjin_360`. |
| `programs_by_region_am` | W | Should fold into `outcome_prefecture_program_heatmap`. |
| `region_coverage_am` | W | Same as above. |
| `search_regions_am` | K | Region probe. |
| `opensearch_hybrid_search` | W | M10 LIVE — should be folded into `discover_related` as a backend. |
| `foreign_fdi_list_am` | K | FDI cohort surface. |
| `foreign_fdi_country_am` | K | FDI cohort surface. |
| `semantic_search_v2_am` | W | Should be folded under `semantic_search_am` alias unification. |
| `semantic_search_am` | W | Same — alias dedup. |
| `cross_source_score_am` | W | Should fold into `verify_citations`. |
| `verify_citations` | W | Should fold into `resolve_citation_chain` (already L4). |
| `render_36_kyotei_am` | K | 36協定 gated. |
| `get_36_kyotei_metadata_am` | K | 36協定 gated. |
| `search_gx_programs_am` | W | Should fold into `pack_manufacturing`. |
| `search_mutual_plans_am` | K | Mutual-aid surface. |
| `find_shitsugi` | W | Should fold into `resolve_citation_chain`. |
| `find_bunsho_kaitou` | W | Should fold into `resolve_citation_chain`. |
| `get_program_eligibility_predicate` | W | Should fold into `dynamic_eligibility_check_am`. |
| `query_at_snapshot_v2` | W | Should fold into `time_machine_snapshot_walk_chain`. |
| `query_program_evolution` | W | Same. |
| `programs_by_corporate_form_am` | W | Should fold into `outcome_houjin_360`. |
| `program_eligibility_by_form_am` | W | Same. |
| `list_pending_alerts` | K | Moat N6 alert surface — client-driven polling. |
| `get_alert_detail` | K | Same. |
| `ack_alert` | K | Same. |
| `find_cases_citing_law` | W | Should fold into `law_related_programs_cross`. |
| `find_laws_cited_by_case` | W | Should fold into `cases_by_industry_size_pref`. |
| `search_figures_by_topic` | K | Moat M3 figure surface — image lookup. |
| `get_figure_caption` | K | Same. |
| `search_case_facts` | K | Moat M2 case extraction — clients want raw. |
| `get_case_extraction` | K | Same. |
| `resolve_placeholder` | W | Should fold into `bundle_application_kit`. |
| `extract_kg_from_text` | K | Moat M1 — operator-side. |
| `get_entity_relations` | W | Should fold into `graph_traverse`. |
| `search_chunks` | K | Moat M9 chunk surface — used by clients/RAG. |
| `get_segment_view` | W | Moat N7 segment — should fold into `outcome_prefecture_program_heatmap`. |
| `segment_summary` | W | Same. |
| `get_artifact_template` | K | N1 template surface — client-driven. |
| `list_artifact_templates` | K | Same. |
| `semantic_search_law_articles` | W | Should fold into `legal_chain_am` / `tax_rule_full_chain`. |

**Tally**: K=38 / W=27 / G=0 / D=3. The 27 "wrap" candidates are the actionable
backlog — folding any one of them into an existing L2/L3/L4 body shrinks the
public surface without losing capability.

## Agent discoverability

### Tool name prefix convention (proposed)

Codify the implicit prefixes so MCP clients can build menus and so `llms.txt`
can offer "if you see prefix X, expect behavior Y":

| Prefix | Intent | Examples |
| --- | --- | --- |
| `search_` | FTS / structured filter over a corpus, returns a list. | `search_programs`, `search_laws`, `search_case_studies` |
| `get_` | Single-record fetch by primary id. | `get_program`, `get_law`, `get_houjin_360_am` |
| `list_` | Enumerate a small bounded set (rules / windows / templates). | `list_exclusion_rules`, `list_windows`, `list_recipes` |
| `find_` | Structured discovery (predicate-driven). | `find_precedents_by_statute`, `find_filing_window`, `find_gap_programs` |
| `match_` | Profile-driven matching (returns ranked list). | `match_programs_by_funding_stage_am`, `match_cohort_5d_am` |
| `check_` | Boolean / categorical answer (compliance, exclusion). | `check_exclusions`, `check_funding_stack_am` |
| `walk_` | Graph traversal over relations. | `walk_reasoning_chain`, `graph_traverse` (legacy — should be `walk_kg`) |
| `resolve_` | Alias / placeholder / citation resolution. | `resolve_alias`, `resolve_placeholder`, `resolve_citation_chain` |
| `prepare_` | Document / packet preparation. | `prepare_kessan_briefing`, `prepare_implementation_workpaper` |
| `outcome_` | Wave 59-B canonical outcome packets. | `outcome_houjin_360`, `outcome_program_lineage` |
| `pack_` | Industry / segment pack composer. | `pack_construction`, `pack_manufacturing`, `pack_real_estate` |
| `agent_` | L3 heavy_endpoint (1-call complete context). | `agent_full_context`, `agent_briefing_pack` |
| `jpcite_` | P0 facade (routing / preview / execute / get). | `jpcite_route`, `jpcite_preview_cost`, `jpcite_execute_packet` |

Drift to fix (not in this PR — design only):
- `graph_traverse` → `walk_kg` (prefix-consistent).
- `evaluate_tax_applicability` → `check_tax_applicability` (boolean answer).
- `trace_program_to_law` → `walk_program_to_law`.

### llms.txt — recommended structure

The current `site/llms.txt` ("First calls for agents") lists 5 REST endpoints
but does not order tools by usefulness. Recommended structure:

```
## First calls for agents (ordered by typical first-touch usefulness)

1. agent_full_context     — HE-1 heavy_endpoint. Use this first when you have a
                            houjin_bangou / program_unified_id / law_unified_id
                            and want everything in one round trip.
2. agent_briefing_pack    — HE-3 heavy_endpoint. Use for "what should this
                            tax/accounting/SR consultant know about topic X
                            in segment Y?" Token-budget aware.
3. multi_tool_orchestrate — HE-4 heavy_endpoint. Use when you already know the
                            3-10 atomic tools you want to call; one round trip
                            instead of N.
4. jpcite_route           — Free preflight. Routes intent → cheapest sufficient
                            outcome_contract_id.
5. search_programs        — The single most-composed L1 atomic (used in 52 of
                            the L2/L3/L4 bodies). Always available as fallback.
```

The point of the ordering: an agent that reads `llms.txt` top-to-bottom should
discover the heavy endpoints **before** the atomics, because the heavy endpoints
already encode the right multi-call recipe.

### `.well-known/jpcite-outcome-catalog.json` — recommended fields

The current `outcome_catalog.json` indexes 452 outcomes by `outcome_contract_id`
but does not bind them back to MCP tool names. Recommended additions per
outcome entry:

```json
{
  "outcome_contract_id": "company_public_baseline",
  "mcp_tool": "outcome_houjin_360",
  "mcp_tool_layer": "L4_workflow",
  "atomic_dependencies": [
    "search_invoice_registrants",
    "search_acceptance_stats_am",
    "check_enforcement_am",
    "list_edinet_disclosures"
  ],
  "replaces_calls": 4,
  "estimated_price_jpy": 900
}
```

This lets an agent harness compute: "if I pay ¥900 for the outcome, I avoid 4
×¥3 = ¥12 of atomic calls + the planning round trip." Agents that read the
catalog can decide explicitly when to compose vs. when to use an outcome.

### MCP server `list_tools()` ordering

FastMCP's default order is registration order. We should override it so the
L3 heavy_endpoints come first:

```
1. agent_full_context, agent_briefing_pack, multi_tool_orchestrate,
   prepare_implementation_workpaper   (L3, 4 tools)
2. jpcite_route, jpcite_preview_cost, jpcite_execute_packet,
   jpcite_get_packet                  (L2 P0 facade, 4 tools)
3. outcome_*                          (L4 wave59_b, 10 tools)
4. pack_*                             (L4 industry, 3 tools)
5. *_chain, *_composed, *_pack        (L4 composed, ~30 tools)
6. L2 composed                        (~52 tools)
7. L1 atomic                          (~171 tools)
```

This is a 1-line change in `server.py` boot — we don't ship it in this design
doc, but the order is what `MOAT_MCP_REGISTRY_AUDIT_2026_05_17.md` should
target.

## Agent UX improvement priorities (top 10)

Ranked by ASR / ARC impact (Agent Success Rate / Agent Retry Cost — see
`feedback_agent_new_kpis_8`).

1. **Move HE-1/2/3/4 to the top of `mcp.list_tools()`** — a 1-line FastMCP
   registration-order tweak. Today they are buried by registration order under
   200+ atomics; agents reading the tool list page-by-page never reach them.
2. **Add `mcp_tool` + `mcp_tool_layer` fields to every outcome catalog entry**
   — `site/.well-known/jpcite-outcome-catalog.json`. Today the binding is
   implicit (via `x-mcp-tool` in OpenAPI); make it explicit in the catalog.
3. **Re-order `llms.txt` "First calls" to put HE-1 first** — see proposed text
   above. Today `llms.txt` lists 5 REST endpoints; replacing the first three
   bullets with HE-1/3/4 raises ASR materially for first-time agent integrations.
4. **Codify the prefix convention in `docs/mcp-tools.md`** — document the
   13 prefixes above so agents (and humans) reading the docs can predict tool
   behavior from name.
5. **Surface the "core 15" most-composed atomics in `mcp-tools.md`** — the 15
   atomics that participate in half of all L2/L3/L4 bodies. Agents that only
   learn these still solve most workflows.
6. **Add a `recommended_for_first_call: true` flag to the MCP `annotations`**
   on HE-1/2/3/4 + the 4 jpcite facade tools — a FastMCP-native way to signal
   "start here" without depending on tool list ordering.
7. **Resolve the 3 deprecation candidates** (`query_snapshot_as_of_v2`,
   `counterfactual_diff_v2`, `semantic_search_legacy_am`) — gate them off by
   default, leave the wrapper for migration, drop them from manifests.
8. **Fold 5-7 of the 27 "wrap candidate" dead-end atomics into existing L2/L3/L4
   bodies** in the next manifest bump. Highest impact: `recommend_similar_*` →
   `discover_related`; `programs_by_corporate_form_am` → `outcome_houjin_360`;
   `query_at_snapshot_v2` / `query_program_evolution` →
   `time_machine_snapshot_walk_chain`; `verify_fact` → `fact_signature_verify_am`.
   This shrinks public surface from 284 → ~277 without losing capability.
9. **Add `agent_full_context` as the documented "first call" in
   `mcp-server.json` description** — today the description does not name a
   first tool. Specifying one shifts the agent's first move from
   `search_programs` (which it has to refine over 2-3 calls) to
   `agent_full_context` (which is depth-scaled and one round trip).
10. **Publish a `composability.json` artifact under
    `site/.well-known/`** — machine-readable version of the composability matrix
    here, so agents can plan calls offline. Schema:
    `{tool: {layer, prefix, used_by: [...], composes: [...], dead_end: bool}}`.

## Re-balance proposal (informational, not part of this PR)

The brief's target shape (L1 150 / L2 30 / L3 10 / L4 20) and reality (171 /
56 / 4 / 53) diverge mainly because:

- **L3 is the deliberate small set** (HE-1/2/3/4). 4 is the right number;
  10 would dilute the "start here" signal.
- **L4 is naturally large** because Wave 59-B outcome wrappers + Wave 51 chains
  + intel_wave31/32 each shipped 5-10 tools. The right move is **not** to
  shrink L4 but to acknowledge that L4 ≈ "domain-specific workflow library".
- **L1 is over-decomposed**: 171 atomics is more than agents can plausibly
  index. Most of the dead-end backlog (27 wrap candidates) sits here and could
  collapse upward.

A reasonable medium-term target (post-Wave-52) is **L1=140 / L2=60 / L3=4 / L4=55**,
which is what the dead-end folding + the prefix-convention cleanup
naturally produce.

## Reproducer

```
python3 /tmp/classify_tools.py
# DISTINCT TOOL COUNT: 284
# --- LAYER BREAKDOWN ---
# L1: 171  L2: 56  L3: 4  L4: 53
# --- ATOMIC DEAD-END COUNT: 68 / 171 ---
```

Source: `/tmp/classify_tools.py` (intentionally outside the repo tree — this
design doc is the artifact, the script is an audit reproducer, not a build
input).

last_updated: 2026-05-17
