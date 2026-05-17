"""Smoke tests for the Niche Moat Lane N10 — MCP wrappers for M1-M11 + N1-N9.

The submodules under ``src/jpintel_mcp/mcp/moat_lane_tools/`` wrap the 20
moat lanes. Some are PENDING scaffolds returning a canonical
``pending_envelope``; others are LIVE db-backed implementations imported
from the same package. M10 is implemented LIVE in ``autonomath_tools`` so
the in-package M10 stub is a deliberate no-op.

Asserts:

* Canonical envelope shape per PENDING wrapper.
* Provenance + disclaimer bundles present on every wrapper.
* All wrappers appear in the live FastMCP tool list.
* Total tool count is at the post-N10 baseline (>= 216 = 184 + 32).
* No LLM SDK imports under the package.

No LLM. No HTTP. No mutation of real DB.
"""

from __future__ import annotations

import asyncio
from typing import Any

# Canonical N10 tool roster — (tool_name, lane_id, schema_version).
# schema_version=None means the wrapper is LIVE (db-backed) and the
# schema_version key is owned by the LIVE implementation, not the PENDING
# scaffold. Order matches the moat lane catalogue M1..M11 + N1..N9.
MOAT_LANE_TOOLS: tuple[tuple[str, str, str | None], ...] = (
    # M1 — KG extraction (2 wrappers, PENDING)
    ("extract_kg_from_text", "M1", "moat.m1.v1"),
    ("get_entity_relations", "M1", "moat.m1.v1"),
    # M2 — case extraction (2 wrappers, PENDING)
    ("search_case_facts", "M2", "moat.m2.v1"),
    ("get_case_extraction", "M2", "moat.m2.v1"),
    # M3 — figure search (2 wrappers, PENDING)
    ("search_figures_by_topic", "M3", "moat.m3.v1"),
    ("get_figure_caption", "M3", "moat.m3.v1"),
    # M4 — law embedding (1 wrapper, PENDING)
    ("semantic_search_law_articles", "M4", "moat.m4.v1"),
    # M5 — jpcite-BERT-v1 encode (1 wrapper, PENDING)
    ("jpcite_bert_v1_encode", "M5", "moat.m5.v1"),
    # M6 — cross-encoder rerank (1 wrapper, PENDING)
    ("rerank_results", "M6", "moat.m6.v1"),
    # M7 — KG completion (1 wrapper, PENDING)
    ("predict_related_entities", "M7", "moat.m7.v1"),
    # M8 — citation cross-lookup (2 wrappers, PENDING)
    ("find_cases_citing_law", "M8", "moat.m8.v1"),
    ("find_laws_cited_by_case", "M8", "moat.m8.v1"),
    # M9 — chunk search (1 wrapper, PENDING)
    ("search_chunks", "M9", "moat.m9.v1"),
    # M10 — OpenSearch hybrid (LIVE elsewhere)
    ("opensearch_hybrid_search", "M10", None),
    # M11 — multi-task predict (1 wrapper, PENDING)
    ("multitask_predict", "M11", "moat.m11.v1"),
    # N1 — artifact templates (2 wrappers, LIVE)
    ("get_artifact_template", "N1", None),
    ("list_artifact_templates", "N1", None),
    # N2 — houjin portfolio (2 wrappers, LIVE)
    ("get_houjin_portfolio", "N2", None),
    ("find_gap_programs", "N2", None),
    # N3 — reasoning chain (2 wrappers, LIVE)
    ("get_reasoning_chain", "N3", None),
    ("walk_reasoning_chain", "N3", None),
    # N4 — filing window (2 wrappers, LIVE)
    ("find_filing_window", "N4", None),
    ("list_windows", "N4", None),
    # N5 — synonym / alias resolver (1 wrapper, LIVE)
    ("resolve_alias", "N5", None),
    # N6 — alerts (3 wrappers, LIVE)
    ("list_pending_alerts", "N6", None),
    ("get_alert_detail", "N6", None),
    ("ack_alert", "N6", None),
    # N7 — segment views (2 wrappers, LIVE)
    ("get_segment_view", "N7", None),
    ("segment_summary", "N7", None),
    # N8 — recipes (2 wrappers, LIVE)
    ("list_recipes", "N8", None),
    ("get_recipe", "N8", None),
    # N9 — placeholders (1 wrapper, LIVE)
    ("resolve_placeholder", "N9", None),
)

# Roster count (one entry per registered MCP tool name).
MOAT_TOOL_COUNT = len(MOAT_LANE_TOOLS)


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def _pending_envelope_checks(
    envelope: dict[str, Any],
    *,
    expected_tool_name: str,
    expected_lane_id: str,
    expected_schema_version: str,
) -> None:
    """Assert the canonical PENDING envelope shape from ``_shared.pending_envelope``."""
    assert isinstance(envelope, dict), envelope
    assert envelope.get("tool_name") == expected_tool_name, envelope.get("tool_name")
    assert envelope.get("schema_version") == expected_schema_version, envelope.get("schema_version")
    assert envelope.get("_billing_unit") == 1, envelope.get("_billing_unit")
    disc = envelope.get("_disclaimer")
    assert isinstance(disc, str)
    assert "§52" in disc
    marker = envelope.get("_pending_marker")
    assert isinstance(marker, str)
    assert marker == f"PENDING {expected_lane_id}", marker
    prov = envelope.get("provenance")
    assert isinstance(prov, dict), prov
    assert prov.get("lane_id") == expected_lane_id, prov
    assert isinstance(prov.get("source_module"), str)
    assert isinstance(prov.get("observed_at"), str)
    primary = envelope.get("primary_result")
    assert isinstance(primary, dict), primary
    assert primary.get("status") == "pending_upstream_lane"
    assert primary.get("lane_id") == expected_lane_id


# ---------------------------------------------------------------------------
# PENDING-wrapper per-tool tests — one per PENDING wrapper.
# LIVE wrappers (N1/N2/N3/N6/N7/N8/N9 + M10) own their own per-module
# integration tests under tests/test_moat_n*_*.py so we don't re-test
# the LIVE db-backed envelope here.
# ---------------------------------------------------------------------------


def test_extract_kg_from_text_envelope() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_m1_kg import extract_kg_from_text

    out = extract_kg_from_text(text="サンプル", lang="ja")
    _pending_envelope_checks(
        out,
        expected_tool_name="extract_kg_from_text",
        expected_lane_id="M1",
        expected_schema_version="moat.m1.v1",
    )


def test_get_entity_relations_envelope() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_m1_kg import get_entity_relations

    out = get_entity_relations(entity_id="ent:001", limit=10)
    _pending_envelope_checks(
        out,
        expected_tool_name="get_entity_relations",
        expected_lane_id="M1",
        expected_schema_version="moat.m1.v1",
    )


def test_search_case_facts_envelope() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_m2_case import search_case_facts

    out = search_case_facts(query="所得税", limit=10)
    _pending_envelope_checks(
        out,
        expected_tool_name="search_case_facts",
        expected_lane_id="M2",
        expected_schema_version="moat.m2.v1",
    )


def test_get_case_extraction_envelope() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_m2_case import get_case_extraction

    out = get_case_extraction(case_id="case:001")
    _pending_envelope_checks(
        out,
        expected_tool_name="get_case_extraction",
        expected_lane_id="M2",
        expected_schema_version="moat.m2.v1",
    )


def test_search_figures_by_topic_envelope() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_m3_figure import search_figures_by_topic

    out = search_figures_by_topic(query="補助金", limit=5)
    _pending_envelope_checks(
        out,
        expected_tool_name="search_figures_by_topic",
        expected_lane_id="M3",
        expected_schema_version="moat.m3.v1",
    )


def test_get_figure_caption_envelope() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_m3_figure import get_figure_caption

    out = get_figure_caption(figure_id="fig:001")
    _pending_envelope_checks(
        out,
        expected_tool_name="get_figure_caption",
        expected_lane_id="M3",
        expected_schema_version="moat.m3.v1",
    )


def test_semantic_search_law_articles_envelope() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_m4_law_embed import (
        semantic_search_law_articles,
    )

    out = semantic_search_law_articles(query="租税特別措置法", limit=5)
    _pending_envelope_checks(
        out,
        expected_tool_name="semantic_search_law_articles",
        expected_lane_id="M4",
        expected_schema_version="moat.m4.v1",
    )


def test_jpcite_bert_v1_encode_envelope() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_m5_simcse import jpcite_bert_v1_encode

    out = jpcite_bert_v1_encode(text="サンプル")
    _pending_envelope_checks(
        out,
        expected_tool_name="jpcite_bert_v1_encode",
        expected_lane_id="M5",
        expected_schema_version="moat.m5.v1",
    )


def test_rerank_results_envelope() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_m6_cross_encoder import rerank_results

    out = rerank_results(query="補助金", candidates=["IT導入", "ものづくり"])
    _pending_envelope_checks(
        out,
        expected_tool_name="rerank_results",
        expected_lane_id="M6",
        expected_schema_version="moat.m6.v1",
    )


def test_predict_related_entities_envelope() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_m7_kg_completion import (
        predict_related_entities,
    )

    out = predict_related_entities(entity_id="program:001", limit=5)
    _pending_envelope_checks(
        out,
        expected_tool_name="predict_related_entities",
        expected_lane_id="M7",
        expected_schema_version="moat.m7.v1",
    )


def test_find_cases_citing_law_envelope() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_m8_citation import find_cases_citing_law

    out = find_cases_citing_law(law_id="law:42-4", limit=10)
    _pending_envelope_checks(
        out,
        expected_tool_name="find_cases_citing_law",
        expected_lane_id="M8",
        expected_schema_version="moat.m8.v1",
    )


def test_find_laws_cited_by_case_envelope() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_m8_citation import find_laws_cited_by_case

    out = find_laws_cited_by_case(case_id="case:001", limit=10)
    _pending_envelope_checks(
        out,
        expected_tool_name="find_laws_cited_by_case",
        expected_lane_id="M8",
        expected_schema_version="moat.m8.v1",
    )


def test_search_chunks_envelope() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_m9_chunks import search_chunks

    out = search_chunks(query="DX投資", limit=5)
    _pending_envelope_checks(
        out,
        expected_tool_name="search_chunks",
        expected_lane_id="M9",
        expected_schema_version="moat.m9.v1",
    )


def test_multitask_predict_envelope() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_m11_multitask import multitask_predict

    out = multitask_predict(text="サンプル", tasks=["ner", "rel"])
    _pending_envelope_checks(
        out,
        expected_tool_name="multitask_predict",
        expected_lane_id="M11",
        expected_schema_version="moat.m11.v1",
    )


# Note: N4 (find_filing_window / list_windows) and N5 (resolve_alias) are now
# LIVE db-backed wrappers; per-module integration coverage lives in the
# dedicated tests/test_moat_n4_n5.py file. Registration is still gated on
# the aggregate test_all_moat_tools_registered_on_mcp_server check below.


# ---------------------------------------------------------------------------
# Aggregate registration tests
# ---------------------------------------------------------------------------


def test_all_moat_tools_registered_on_mcp_server() -> None:
    """All N10 spec tools must appear in the live FastMCP tool list."""
    from jpintel_mcp.mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {getattr(t, "name", str(t)) for t in tools}
    expected = {row[0] for row in MOAT_LANE_TOOLS}
    missing = expected - names
    assert not missing, f"missing moat-lane tools: {sorted(missing)}"


def test_total_tool_count_at_least_216() -> None:
    """Baseline 184 + N10 layer (32 tools) = at least 216 at default gates."""
    from jpintel_mcp.mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    assert len(tools) >= 216, f"expected >= 216 tools (184 baseline + 32 moat), got {len(tools)}"


def test_shared_envelope_constants_exposed() -> None:
    """The package-level DISCLAIMER + helpers are importable + well-formed."""
    from jpintel_mcp.mcp.moat_lane_tools._shared import (
        DISCLAIMER,
        pending_envelope,
        today_iso_utc,
    )

    # Disclaimer references every regulated profession in scope.
    for token in ("§52", "§47条の2", "§72", "§1", "§3"):
        assert token in DISCLAIMER, token
    # ISO date string (YYYY-MM-DD).
    ts = today_iso_utc()
    assert isinstance(ts, str) and len(ts) == 10 and ts[4] == "-" and ts[7] == "-"
    # Round-trip pending_envelope keeps required keys stable.
    env = pending_envelope(
        tool_name="probe",
        lane_id="X9",
        upstream_module="jpintel_mcp.moat.test",
        schema_version="moat.x9.v1",
        primary_input={"k": "v"},
    )
    for key in (
        "tool_name",
        "schema_version",
        "primary_result",
        "results",
        "total",
        "limit",
        "offset",
        "citations",
        "provenance",
        "_billing_unit",
        "_disclaimer",
        "_pending_marker",
    ):
        assert key in env, key


def test_no_llm_sdk_imports_in_moat_lane_tools() -> None:
    """Re-assert the no-LLM-in-production contract for moat_lane_tools/."""
    import pkgutil
    import sys

    import jpintel_mcp.mcp.moat_lane_tools as pkg

    # Ensure submodules are loaded so sys.modules reflects the real import graph.
    for mod_info in pkgutil.walk_packages(pkg.__path__, prefix=f"{pkg.__name__}."):
        try:
            __import__(mod_info.name)
        except Exception:  # pragma: no cover — non-fatal for this check
            continue

    banned_prefixes = (
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
    )
    leaks = []
    for name in list(sys.modules):
        if not name.startswith(pkg.__name__):
            continue
        mod = sys.modules.get(name)
        if mod is None:
            continue
        for attr in dir(mod):
            if attr.startswith(banned_prefixes):
                leaks.append(f"{name}:{attr}")
    assert not leaks, f"LLM SDK leak in moat_lane_tools: {leaks[:5]}"


def test_pydantic_field_metadata_on_pending_wrappers() -> None:
    """Confirm PENDING wrappers carry pydantic.Field metadata on their params."""
    import inspect
    from typing import get_args, get_type_hints

    from pydantic.fields import FieldInfo

    from jpintel_mcp.mcp.moat_lane_tools.moat_m1_kg import extract_kg_from_text
    from jpintel_mcp.mcp.moat_lane_tools.moat_m6_cross_encoder import rerank_results

    def has_field_metadata(fn: Any, param_name: str) -> bool:
        hints = get_type_hints(fn, include_extras=True)
        annot = hints.get(param_name)
        if annot is None:
            return False
        if any(isinstance(meta, FieldInfo) for meta in get_args(annot)[1:]):
            return True
        sig = inspect.signature(fn)
        param = sig.parameters.get(param_name)
        if param is None or param.annotation is inspect.Parameter.empty:
            return False
        return any(isinstance(meta, FieldInfo) for meta in get_args(param.annotation)[1:])

    assert has_field_metadata(extract_kg_from_text, "text")
    assert has_field_metadata(extract_kg_from_text, "lang")
    assert has_field_metadata(rerank_results, "query")
    assert has_field_metadata(rerank_results, "candidates")
