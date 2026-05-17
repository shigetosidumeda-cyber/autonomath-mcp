# Niche Moat Lane N10 — MCP wrapper layer (2026-05-17)

Lane N10 wraps every moat lane (M1-M11 + N1-N9) as MCP tools so an agent
that connects to the jpcite MCP server reaches the full moat surface
through a single endpoint. The wrapper layer sits between the FastMCP
server and the per-lane implementations — its job is to:

1. Register every lane's public surface on the shared FastMCP instance.
2. Stamp a uniform envelope (`tool_name` / `schema_version` /
   `_billing_unit=1` / `_disclaimer` / `provenance`) on every response.
3. Hand back a `PENDING <lane>` envelope when the upstream lane has not
   yet landed, so contract-side agent code can integrate today.

The N10 layer is gated by `JPCITE_MOAT_LANES_ENABLED` (default ON). The
master gate is also implicitly gated by `settings.autonomath_enabled` in
`server.py` so the moat layer turns off cleanly when autonomath rolls back.

## Tool count

* baseline (pre-N10): **184 tools**
* N10 layer adds: **32 moat tools** (31 in-package + 1 M10 via
  `autonomath_tools.opensearch_hybrid_tools`)
* total: **216 tools** at default gates (`len(await mcp.list_tools())`)

Verify with:

```python
import asyncio
from jpintel_mcp.mcp.server import mcp
asyncio.run(mcp.list_tools())  # → 216 entries
```

> The earlier internal scaffold targeted 220 tools (184 + 36), but four
> lanes consolidated their surface during the LIVE landings: N6 collapsed
> `ack_alert` semantics into the same module that hosts the alert read
> path; N8 chose `list_recipes` / `get_recipe` over an explicit
> `recipe_inputs_schema` (the schema is embedded in `get_recipe`); N9
> dropped `list_placeholder_kinds` + `placeholder_required_fields` after
> the placeholder bank was fixed at ~207 canonical names. The wire
> contract is the live count from `mcp.list_tools()`, not the historical
> spec number.

## Wrapper roster (by lane)

Each row links the canonical MCP tool name to its current state. PENDING
wrappers return a structural envelope until the upstream lane lands; LIVE
wrappers read from `autonomath.db` (or a file-backed corpus) directly.

| Lane | Tool name(s) | Module | Status |
|------|--------------|--------|--------|
| M1   | `extract_kg_from_text`, `get_entity_relations` | `moat_m1_kg.py` | PENDING M1 |
| M2   | `search_case_facts`, `get_case_extraction` | `moat_m2_case.py` | PENDING M2 |
| M3   | `search_figures_by_topic`, `get_figure_caption` | `moat_m3_figure.py` | PENDING M3 |
| M4   | `semantic_search_law_articles` | `moat_m4_law_embed.py` | PENDING M4 |
| M5   | `jpcite_bert_v1_encode` | `moat_m5_simcse.py` | PENDING M5 |
| M6   | `rerank_results` | `moat_m6_cross_encoder.py` | PENDING M6 |
| M7   | `predict_related_entities` | `moat_m7_kg_completion.py` | PENDING M7 |
| M8   | `find_cases_citing_law`, `find_laws_cited_by_case` | `moat_m8_citation.py` | PENDING M8 |
| M9   | `search_chunks` | `moat_m9_chunks.py` | PENDING M9 |
| M10  | `opensearch_hybrid_search` | `moat_m10_opensearch.py` (no-op stub) + `autonomath_tools.opensearch_hybrid_tools` | LIVE |
| M11  | `multitask_predict` | `moat_m11_multitask.py` | PENDING M11 |
| N1   | `get_artifact_template`, `list_artifact_templates` | `moat_n1_artifact.py` | LIVE (am_artifact_templates) |
| N2   | `get_houjin_portfolio`, `find_gap_programs` | `moat_n2_portfolio.py` | LIVE (am_houjin_program_portfolio) |
| N3   | `get_reasoning_chain`, `walk_reasoning_chain` | `moat_n3_reasoning.py` | LIVE (am_legal_reasoning_chain) |
| N4   | `find_filing_window`, `list_windows` | `moat_n4_window.py` | LIVE (am_window_directory) |
| N5   | `resolve_alias` | `moat_n5_synonym.py` | LIVE (am_alias) |
| N6   | `list_pending_alerts`, `get_alert_detail`, `ack_alert` | `moat_n6_alert.py` | LIVE (am_amendment_alert_impact) |
| N7   | `get_segment_view`, `segment_summary` | `moat_n7_segment.py` | LIVE (am_segment_view) |
| N8   | `list_recipes`, `get_recipe` | `moat_n8_recipe.py` | LIVE (data/recipes/*.yaml) |
| N9   | `resolve_placeholder` | `moat_n9_placeholder.py` | LIVE (am_placeholder_mapping) |

## Envelope contract

Every wrapper returns a `dict[str, Any]` with the following keys (PENDING
+ LIVE share the same canonical shape; PENDING additionally sets
`_pending_marker`):

* `tool_name: str` — public MCP tool name.
* `schema_version: str` — `moat.<lane>.v1` for PENDING; LIVE wrappers
  may use a richer string but always include the version.
* `primary_result: dict` — main payload (LIVE) or
  `{"status": "pending_upstream_lane", ...}` (PENDING).
* `results: list` / `total: int` / `limit: int` / `offset: int` — pagination
  envelope.
* `citations: list[dict]` — list of `{"kind", "text", "source_url"?}` entries.
* `provenance: dict` — `{"source_module", "lane_id", "wrap_kind", "observed_at"}`.
* `_billing_unit: 1` — ¥3 metered. Always 1 per call.
* `_disclaimer: str` — covers §52 / §47条の2 / §72 / §1 / §3 + 社労士法 / 行政書士法.
* `_pending_marker: "PENDING <lane>"` — present iff PENDING.

## Constraints honoured

* **NO LLM** — no `anthropic` / `openai` / `google.generativeai` / `claude_agent_sdk`
  imports under any moat_lane_tools/* file. Enforced by the package-wide
  CI guard (`tests/test_no_llm_in_production.py`) + an inline assertion in
  `tests/test_moat_lane_tools.py::test_no_llm_sdk_imports_in_moat_lane_tools`.
* **§52 / §47条の2 / §72 / §1 / §3 / 社労士法 / 行政書士法** — every
  envelope carries the canonical disclaimer.
* **mypy --strict 0 errors** — verified on
  `src/jpintel_mcp/mcp/moat_lane_tools/`.
* **ruff 0 errors** — verified on the same path + the test file.
* **¥3/req metered** — one billable unit per call (`_billing_unit=1`).

## Registration seam

`src/jpintel_mcp/mcp/server.py` imports `moat_lane_tools` after
`autonomath_tools`, inside the same `if settings.autonomath_enabled:` block.
The wrapper package's `__init__.py` walks `_SUBMODULES` and imports each
one via `importlib.import_module` — missing submodules are silently
skipped (partial checkouts do not break MCP server boot).

```
src/jpintel_mcp/mcp/server.py:
    if settings.autonomath_enabled:
        ...
        from jpintel_mcp.mcp import autonomath_tools  # noqa: F401
        from jpintel_mcp.mcp import moat_lane_tools   # noqa: F401  ← N10
```

## Tests

`tests/test_moat_lane_tools.py` covers:

* PENDING envelope shape per PENDING wrapper (13 tests).
* Aggregate registration: every roster entry appears in
  `await mcp.list_tools()`.
* Total tool count ≥ 216.
* Shared helpers (`DISCLAIMER`, `pending_envelope`, `today_iso_utc`) exist
  and round-trip cleanly.
* No LLM SDK leaks under the package.
* Pydantic `Field(...)` metadata is present on every PENDING wrapper
  parameter (so FastMCP can synthesize a JSON Schema at the wire layer).

Run the test:

```bash
.venv/bin/python -m pytest tests/test_moat_lane_tools.py -v
```

Per-LIVE-module deeper integration tests live alongside:

* `tests/test_moat_n1_artifact.py`
* `tests/test_moat_n2_portfolio.py`
* `tests/test_moat_n3_reasoning.py`
* `tests/test_moat_n4_n5.py`
* `tests/test_moat_n6_n7.py`

## Operator notes

* Flip `JPCITE_MOAT_LANES_ENABLED=0` to disable the entire wrapper
  package — useful for emergency rollback if a PENDING wrapper starts
  emitting bad envelopes after a refactor.
* Manifest counts (`pyproject.toml` / `server.json` / `dxt/manifest.json`
  / `smithery.yaml` / `mcp-server.json`) are intentionally held at the
  previous default-gate baseline. A bump should be intentional and
  coupled to a release.
