"""AutonoMath am_* MCP tool package.

Importing this package triggers @mcp.tool registration of the 11 tools:

  tools.py           (10 tools: search_tax_incentives / search_certifications
                      / list_open_programs / enum_values_am / search_by_law
                      / active_programs_at / related_programs
                      / search_acceptance_stats_am / intent_of / reason_answer)
  tax_rule_tool.py   (1 tool:  get_am_tax_rule)

Registration runs at import time — the submodules `from jpintel_mcp.mcp.server
import mcp, _READ_ONLY` and decorate their functions with that shared mcp
instance. Side-effect only; no symbols are re-exported.

NOT registered:
  acceptance_stats_tool.py  — cross-DB JOIN (jpintel.programs × am.am_acceptance_stat)
                              via single connect(), broken until ATTACH-DATABASE
                              wiring lands. Superseded by tools.search_acceptance_stats_am
                              which reads am_entities directly.
"""

import os
from importlib import import_module

from jpintel_mcp.mcp.server import mcp as _mcp

from . import (
    annotation_tools,  # noqa: F401  — V4 Phase 4: get_annotations (am_entity_annotation, migration 046)
    autonomath_wrappers,  # noqa: F401  — decorator side-effect (5 wrappers; sib_tool intentionally skipped — am_sib_contract has 35 rows from Wave 19 backfill but tool not yet stabilized)
    benchmark_tools,  # noqa: F401  — R8 (2026-05-07): benchmark_cohort_average_am — 業種 × 規模 × 地域 cohort average + outlier (top 10%) over case_studies + jpi_adoption_records.
    citations_tools,  # noqa: F401  — 2026-04-30: verify_citations (api/citations.py companion). LR plan §28.2 verification path.
    cohort_match_tools,  # noqa: F401  — R8 (2026-05-07): case_cohort_match_am — 同業 (JSIC) × 同規模 (employees + revenue) × 同地域 (prefecture) cohort matcher over case_studies + jpi_adoption_records. AUTONOMATH_COHORT_MATCH_ENABLED gate (default ON). NO LLM, single ¥3/req billing event. §52 / §47条の2 / §1 envelope. REST companion at POST /v1/cases/cohort_match.
    cohort_risk_chain,  # noqa: F401  — Wave 33 Axis 2a/2b/2c (2026-05-12): 3 precompute MCP tools (match_cohort_5d_am / program_risk_score_am / supplier_chain_am) over am_cohort_5d (mig 231) + am_program_risk_4d (mig 232) + am_supplier_chain (mig 233). AUTONOMATH_COHORT_RISK_CHAIN_ENABLED gate (default ON). NO LLM. REST companion at POST /v1/cohort/5d/match + GET /v1/programs/{id}/risk + GET /v1/supplier/chain/{houjin}.
    compatibility_tools,  # noqa: F401  — R8 (2026-05-07): am_compat_matrix 43,966 row full surface. 2 tools (portfolio_optimize_am / program_compatibility_pair_am) over am_compat_matrix + am_funding_stack_empirical + am_program_eligibility_predicate + am_relation. AUTONOMATH_COMPATIBILITY_TOOLS_ENABLED gate (default ON). NO LLM, single ¥3/req billing event. §52/§1/§72 envelope. REST companion at POST /v1/programs/portfolio_optimize + GET /v1/programs/{a}/compatibility/{b}.
    composition_tools,  # noqa: F401  — Wave 21: 5 composition tools (apply_eligibility_chain_am / find_complementary_programs_am / simulate_application_am / track_amendment_lineage_am / program_active_periods_am, AUTONOMATH_COMPOSITION_ENABLED gate)
    corporate_form_tools,  # noqa: F401  — M02 (2026-05-07): 2 法人格 × 制度 matrix tools (programs_by_corporate_form_am / program_eligibility_by_form_am) over am_program_eligibility_predicate_json $.target_entity_types axis. AUTONOMATH_CORPORATE_FORM_ENABLED gate (default ON). NO LLM, single ¥3/req billing event. §52 / 行政書士法 §1 envelope.
    corporate_layer_tools,  # noqa: F401  — P12 §4.8 (2026-05-04): 3 corporate-layer tools (get_houjin_360_am / list_edinet_disclosures / search_invoice_by_houjin_partial). Direct competitor coverage vs japan-corporate-mcp. AUTONOMATH_CORPORATE_LAYER_ENABLED gate (default ON), §52 envelope on the 2 sensitive tools, EDINET pointer surface (no live HTTP).
    cross_reference_tools,  # noqa: F401  — R8 cross-reference deep link (2026-05-07): 3 tools (program_full_context / law_related_programs_cross / cases_by_industry_size_pref) over jpintel programs / laws / program_law_refs / court_decisions / case_studies / enforcement_cases / exclusion_rules + best-effort autonomath am_amendment_diff. AUTONOMATH_CROSS_REFERENCE_ENABLED gate (default ON). NO LLM, single ¥3/req billing event. §72/§52/§1/§27 envelope on the 2 sensitive tools.
    discover,  # noqa: F401  — Multi-axis Discover Related (5 axes: via_law_ref / via_vector / via_co_adoption / via_density_neighbors / via_5hop). REST companion at GET /v1/discover/related/{entity_id}. AUTONOMATH_DISCOVER_ENABLED gate (default ON).
    eligibility_tools,  # noqa: F401  — R8 (2026-05-07): 2 dynamic eligibility check tools (dynamic_eligibility_check_am / program_eligibility_for_houjin_am) joining am_enforcement_detail × exclusion_rules. AUTONOMATH_ELIGIBILITY_CHECK_ENABLED gate (default ON). NO LLM.
    evidence_packet_tools,  # noqa: F401  — 2026-04-30: get_evidence_packet (api/evidence.py companion). LR plan §6 Evidence Packet composer.
    funding_stack_tools,  # noqa: F401  — 2026-04-30: check_funding_stack_am (api/funding_stack.py companion). Pure rule engine.
    funding_stage_tools,  # noqa: F401  — 2026-05-07: match_programs_by_funding_stage_am (api/funding_stage.py companion). 5 stage (seed/early/growth/ipo/succession) keyword fence + age/capital/revenue band over jpintel.programs. AUTONOMATH_FUNDING_STAGE_ENABLED gate (default ON). NO LLM, single ¥3/req billing event.
    graph_traverse_tool,  # noqa: F401  — O7 Wave 18: graph_traverse (heterogeneous 1-3 hop KG walk over v_am_relation_all, AUTONOMATH_GRAPH_TRAVERSE_ENABLED gate)
    health_tool,  # noqa: F401  — Phase A: deep_health_am (10-check aggregate)
    industry_packs,  # noqa: F401  — Wave 23 (2026-04-29): 3 industry-specific cohort wrappers (pack_construction / pack_manufacturing / pack_real_estate). Top 10 programs + 5 saiketsu + 3 通達 per call. AUTONOMATH_INDUSTRY_PACKS_ENABLED gate (default ON). NO LLM, single ¥3/req billing event. §52/§47条の2 envelope.
    invoice_risk_tools,  # noqa: F401  — R8 (2026-05-07): 3 invoice-risk lookup tools (invoice_risk_lookup / invoice_risk_batch / houjin_invoice_status). Composes invoice_registrants (PDL v1.0) × houjin_master + 6m/1y registration-age heuristic into 0-100 risk_score + tax_credit_eligible boolean. AUTONOMATH_INVOICE_RISK_ENABLED gate (default ON). NO LLM, single ¥3/req billing event. §52 fence on 仕入税額控除 territory.
    kokkai_tools,  # noqa: F401  — DEEP-39 (2026-05-07): 2 kokkai/shingikai surface tools (search_kokkai_utterance / search_shingikai_minutes) over kokkai_utterance + shingikai_minutes (migration wave24_185). AUTONOMATH_KOKKAI_ENABLED gate (default ON). NO LLM, single ¥3/req billing. §52/§47条の2/§72/§3 envelope.
    lifecycle_calendar_tool,  # noqa: F401  — O4 Wave 18: unified_lifecycle_calendar (tax+program sunset + app close + law cliff merge, AUTONOMATH_LIFECYCLE_CALENDAR_ENABLED gate)
    lifecycle_tool,  # noqa: F401  — O4 Wave 18: program_lifecycle (8-step deterministic status over am_amendment_snapshot + am_relation, AUTONOMATH_LIFECYCLE_ENABLED gate)
    multilingual_abstract_tool,  # noqa: F401  — R7: program_abstract_structured (closed-vocab JA-only abstract; customer LLM translates)
    municipality_tools,  # noqa: F401  — DEEP-44 (2026-05-07): 自治体 1,741 補助金 page diff (1st pass 67 自治体 = 47 都道府県 + 20 政令市). 1 tool (search_municipality_subsidies) over municipality_subsidy (jpintel.db, migration wave24_191). AUTONOMATH_MUNICIPALITY_ENABLED gate (default ON). NO LLM, single ¥3/req billing. 政府著作物 §13 license — source_attribution envelope per row, NO _disclaimer (pure 1次資料 listing).
    nta_corpus_tools,  # noqa: F401  — migration 103: 4 tools (find_saiketsu / cite_tsutatsu / find_shitsugi / find_bunsho_kaitou) over nta_saiketsu / nta_tsutatsu_index / nta_shitsugi / nta_bunsho_kaitou; AUTONOMATH_NTA_CORPUS_ENABLED gate (default ON), §52 envelope on every result.
    policy_upstream_tools,  # noqa: F401  — DEEP-46 (2026-05-07): 2 政策 上流 signal 統合 tools (policy_upstream_watch / policy_upstream_timeline) cross-axis rollup over kokkai_utterance + shingikai_minutes + pubcomment_announcement + am_amendment_diff + jpi_programs. AUTONOMATH_POLICY_UPSTREAM_ENABLED gate (default ON). NO LLM, single ¥3/req billing. §52/§47条の2/§72/§1 envelope mandatory.
    prerequisite_chain_tool,  # noqa: F401  — R5: prerequisite_chain (am_prerequisite_bundle, 1.6% coverage surfaced honestly, AUTONOMATH_PREREQUISITE_CHAIN_ENABLED gate)
    provenance_tools,  # noqa: F401  — V4 Phase 4: get_provenance + get_provenance_for_fact (am_source.license, migration 049)
    pubcomment_tools,  # noqa: F401  — DEEP-45 (2026-05-07): 1 e-Gov パブコメ surface tool (get_pubcomment_status) over pubcomment_announcement (migration wave24_192). AUTONOMATH_PUBCOMMENT_ENABLED gate (default ON). NO LLM, single ¥3/req billing. §52/§47条の2/§72/§1 envelope. Lead time 30-60 日.
    recommend_similar,  # noqa: F401  — 2026-05-05: 3 vector k-NN recommend tools (recommend_similar_program / _case / _court_decision) over am_entities_vec_S/C/J post 91% embedding backfill. AUTONOMATH_RECOMMEND_SIMILAR_ENABLED gate (default ON). 行政書士法 §1 / 弁護士法 §72 / 税理士法 §52 envelope on all 3.
    region_tools,  # noqa: F401  — R8 GEO REGION API (2026-05-07): 3 region hit-map tools (programs_by_region_am / region_coverage_am / search_regions_am) over am_region (1,966 rows: 1 nation + 47 prefectures + 20 designated cities + 171 wards + 1,727 municipalities) × jpintel.programs. AUTONOMATH_REGION_API_ENABLED gate (default ON). NO LLM, single ¥3/req billing event. REST companion at /v1/programs/by_region/{code} + /v1/regions/{code}/coverage + /v1/regions/search.
    rule_engine_tool,  # noqa: F401  — R9 unified rule_engine_check (am_unified_rule view, migration 064)
    shihoshoshi_tools,  # noqa: F401  — DEEP-30 (2026-05-07): 司法書士 cohort dedicated DD pack (shihoshoshi_dd_pack_am). Compounds wave22 cross_check_jurisdiction + corporate_layer get_houjin_360_am + check_enforcement_am into 1 ¥3/req call. AUTONOMATH_SHIHOSHOSHI_PACK_ENABLED gate (default ON). §3 fence (司法書士独占業務) + §52/§72/§1 disclaimer envelope. NO LLM.
    snapshot_tool,  # noqa: F401  — R8: query_at_snapshot (dataset versioning, migration 067)
    source_manifest_tools,  # noqa: F401  — 2026-04-30: get_source_manifest (api/source_manifest.py companion). Per-program provenance rollup.
    static_resources_tool,  # noqa: F401  — Phase A: 4 tools (list/get static resources + example profiles)
    succession_tools,  # noqa: F401  — 2026-05-07: 2 tools (match_succession_am / succession_playbook_am) over jpintel.programs + laws. M&A pillar of cohort revenue model. AUTONOMATH_SUCCESSION_ENABLED gate (default ON). NO LLM, single ¥3/req billing event. §52 / §72 envelope. REST companion at POST /v1/succession/match + GET /v1/succession/playbook.
    sunset_tool,  # noqa: F401  — V1 feature #11 (dd_v4_05): list_tax_sunset_alerts
    tax_chain_tools,  # noqa: F401  - 2026-05-07: tax_rule_full_chain (1 tool wrapping /v1/tax_rules/{rule_id}/full_chain - 税制 + 法令 + 通達 + 裁決 + 判例 + 改正履歴 chain). AUTONOMATH_TAX_CHAIN_ENABLED gate (default ON). NO LLM, single ¥3/req billing event. §52/§72/§47条の2 envelope.
    tax_rule_tool,  # noqa: F401  — decorator side-effect (1 tool)
    template_tool,  # noqa: F401  — Phase A: render_36_kyotei_am + get_36_kyotei_metadata_am
    time_machine_tools,  # noqa: F401  — DEEP-22 (2026-05-07): 2 tools (query_at_snapshot_v2 / query_program_evolution) over am_amendment_snapshot 14,596 captures + 144 definitive-dated. AUTONOMATH_SNAPSHOT_ENABLED gate (default ON post-DEEP-22). NO LLM, single ¥3/req billing.
    timeline_trend_tools,  # noqa: F401  — R8 (2026-05-07): 3 timeline + trend tools (program_timeline_am / cases_timeline_trend_am / upcoming_rounds_for_my_profile_am) over jpi_adoption_records (201,845) + am_application_round (1,256) + client_profiles. AUTONOMATH_TIMELINE_TREND_ENABLED gate (default ON). NO LLM, single ¥3/req billing event. §52/§47条の2/§1 envelope on the 2 trend surfaces; §1 only on upcoming-rounds. REST companion at /v1/programs/{id}/timeline + /v1/cases/timeline_trend + /v1/me/upcoming_rounds_for_my_profile.
    tools,  # noqa: F401  — decorator side-effect (10 tools)
    validation_tools,  # noqa: F401  — V4 Phase 4: validate (am_validation_rule dispatcher, migration 047)
    wave22_tools,  # noqa: F401  — Wave 22: 5 composition tools (match_due_diligence_questions / prepare_kessan_briefing / forecast_program_renewal / cross_check_jurisdiction / bundle_application_kit, AUTONOMATH_WAVE22_ENABLED gate). Adds dd_question_templates DB (migration 104).
)

# MCP resources + prompts registration (Wave 17 — kept dormant until v8 wiring).
# Importing here triggers register_*(mcp) which adds the autonomath:// resource
# URIs and prompt templates to the FastMCP capability surface.
from .prompts import register_prompts as _register_prompts
from .resources import register_resources as _register_resources


def _experimental_mcp_enabled() -> bool:
    return os.getenv("AUTONOMATH_EXPERIMENTAL_MCP_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


if _experimental_mcp_enabled():
    for _module_name in (
        "jpintel_mcp.mcp.autonomath_tools.intel_wave31",
        "jpintel_mcp.mcp.autonomath_tools.wave24_tools_first_half",
        "jpintel_mcp.mcp.autonomath_tools.wave24_tools_second_half",
    ):
        import_module(_module_name)


_register_resources(_mcp)
_register_prompts(_mcp)
