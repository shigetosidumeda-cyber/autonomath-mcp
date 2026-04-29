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

from jpintel_mcp.mcp.server import mcp as _mcp

from . import (
    annotation_tools,  # noqa: F401  — V4 Phase 4: get_annotations (am_entity_annotation, migration 046)
    autonomath_wrappers,  # noqa: F401  — decorator side-effect (5 wrappers; sib_tool intentionally skipped — am_sib_contract has 35 rows from Wave 19 backfill but tool not yet stabilized)
    composition_tools,  # noqa: F401  — Wave 21: 5 composition tools (apply_eligibility_chain_am / find_complementary_programs_am / simulate_application_am / track_amendment_lineage_am / program_active_periods_am, AUTONOMATH_COMPOSITION_ENABLED gate)
    graph_traverse_tool,  # noqa: F401  — O7 Wave 18: graph_traverse (heterogeneous 1-3 hop KG walk over v_am_relation_all, AUTONOMATH_GRAPH_TRAVERSE_ENABLED gate)
    health_tool,  # noqa: F401  — Phase A: deep_health_am (10-check aggregate)
    lifecycle_calendar_tool,  # noqa: F401  — O4 Wave 18: unified_lifecycle_calendar (tax+program sunset + app close + law cliff merge, AUTONOMATH_LIFECYCLE_CALENDAR_ENABLED gate)
    lifecycle_tool,  # noqa: F401  — O4 Wave 18: program_lifecycle (8-step deterministic status over am_amendment_snapshot + am_relation, AUTONOMATH_LIFECYCLE_ENABLED gate)
    multilingual_abstract_tool,  # noqa: F401  — R7: program_abstract_structured (closed-vocab JA-only abstract; customer LLM translates)
    prerequisite_chain_tool,  # noqa: F401  — R5: prerequisite_chain (am_prerequisite_bundle, 1.6% coverage surfaced honestly, AUTONOMATH_PREREQUISITE_CHAIN_ENABLED gate)
    provenance_tools,  # noqa: F401  — V4 Phase 4: get_provenance + get_provenance_for_fact (am_source.license, migration 049)
    rule_engine_tool,  # noqa: F401  — R9 unified rule_engine_check (am_unified_rule view, migration 064)
    snapshot_tool,  # noqa: F401  — R8: query_at_snapshot (dataset versioning, migration 067)
    static_resources_tool,  # noqa: F401  — Phase A: 4 tools (list/get static resources + example profiles)
    sunset_tool,  # noqa: F401  — V1 feature #11 (dd_v4_05): list_tax_sunset_alerts
    tax_rule_tool,  # noqa: F401  — decorator side-effect (1 tool)
    template_tool,  # noqa: F401  — Phase A: render_36_kyotei_am + get_36_kyotei_metadata_am
    tools,  # noqa: F401  — decorator side-effect (10 tools)
    validation_tools,  # noqa: F401  — V4 Phase 4: validate (am_validation_rule dispatcher, migration 047)
    wave22_tools,  # noqa: F401  — Wave 22: 5 composition tools (match_due_diligence_questions / prepare_kessan_briefing / forecast_program_renewal / cross_check_jurisdiction / bundle_application_kit, AUTONOMATH_WAVE22_ENABLED gate). Adds dd_question_templates DB (migration 104).
    nta_corpus_tools,  # noqa: F401  — migration 103: 4 tools (find_saiketsu / cite_tsutatsu / find_shitsugi / find_bunsho_kaitou) over nta_saiketsu / nta_tsutatsu_index / nta_shitsugi / nta_bunsho_kaitou; AUTONOMATH_NTA_CORPUS_ENABLED gate (default ON), §52 envelope on every result.
    industry_packs,  # noqa: F401  — Wave 23 (2026-04-29): 3 industry-specific cohort wrappers (pack_construction / pack_manufacturing / pack_real_estate). Top 10 programs + 5 saiketsu + 3 通達 per call. AUTONOMATH_INDUSTRY_PACKS_ENABLED gate (default ON). NO LLM, single ¥3/req billing event. §52/§47条の2 envelope.
)

# MCP resources + prompts registration (Wave 17 — kept dormant until v8 wiring).
# Importing here triggers register_*(mcp) which adds the autonomath:// resource
# URIs and prompt templates to the FastMCP capability surface.
from .prompts import register_prompts as _register_prompts
from .resources import register_resources as _register_resources

_register_resources(_mcp)
_register_prompts(_mcp)
