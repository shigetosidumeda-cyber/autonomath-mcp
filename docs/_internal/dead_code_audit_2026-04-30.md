# Dead Code Audit 2026-04-30

Scope: `src/jpintel_mcp/` only. `data/` / `research/` / `analysis_wave18/` excluded.
Method: AST + grep across `src/`, `tests/`, `scripts/`. Pure analysis — no deletes.

Totals: 215 `.py` files in `src/jpintel_mcp/` (191 outside `_archive/`).

## A. Unused modules (0 inbound imports)

Modules below have **0 inbound imports** anywhere in `src/`, `tests/`, `scripts/`. Entry-point modules (`api/main.py`, `mcp/server.py`, `config.py`) and modules pulled in via package `__init__.py` side-effect (e.g. `mcp/autonomath_tools/*`) are filtered out.

- `src/jpintel_mcp/api/_universal_envelope.py` — 11 `next_calls_for_*` builders + license filter primitives. Last touched 2026-04-29. Designed as ARPU lift across search endpoints; never wired into any router. Recommend: archive to `_archive/universal_envelope_2026-04-30/` after one more pass to confirm no future-feature plan is depending on it.
- `src/jpintel_mcp/api/middleware/cost_cap.py` — defines `CostCapMiddleware`. NOT re-exported from `middleware/__init__.py`, NOT mounted in `main.py`. Only self-references. Last touched 2026-04-29.
- `src/jpintel_mcp/api/middleware/envelope_adapter.py` — defines `EnvelopeAdapterMiddleware`. Same pattern: not in `__init__.py` `__all__`, not mounted. Last touched 2026-04-30.
- `src/jpintel_mcp/api/middleware/idempotency.py` — defines `IdempotencyMiddleware`. Not re-exported, not mounted. Two stale comments mention it (`api/bulk_evaluate.py:334`, `scripts/cron/idempotency_cache_sweep.py:7`). Last touched 2026-04-29.

**4 unused modules** total (after filtering side-effect imports + entry points).

## B. Unused functions (no callers anywhere)

Top-level functions with **0 invocations** across `src/`, `tests/`, `scripts/`. AST-extracted; entry decorators (`@router.*`, `@app.*`, `@mcp.tool`, `@pytest.fixture`, etc.) excluded. 21 candidates total — listed below grouped by file:

In dead module `_universal_envelope.py` (12 functions, all dead because the module itself is unused):
- `parse_license_filter` (line 132)
- `filter_rows_by_license` (line 149)
- `_has_value` (line 224)
- `next_calls_for_program` (line 233)
- `next_calls_for_law` (line 272)
- `next_calls_for_court_decision` (line 284)
- `next_calls_for_case_study` (line 301)
- `next_calls_for_bid` (line 325)
- `next_calls_for_invoice_registrant` (line 349)
- `next_calls_for_loan` (line 371)
- `next_calls_for_tax_ruleset` (line 381)
- `next_calls_for_enforcement` (line 398)
- `next_calls_for_am_entity` (line 417)
- `build_envelope_extras` (line 435)

In live modules (genuine orphans inside otherwise-live files):
- `src/jpintel_mcp/api/me.py:865` — `_send_key_rotated_safe`. 0 callers.
- `src/jpintel_mcp/api/confidence.py:53` — `_reset_confidence_cache`. 0 callers (test-only helper, never wired to a fixture).
- `src/jpintel_mcp/api/formats/ics.py:85` — `_ics_escape`. RFC 5545 helper, not called inside `render_ics`.
- `src/jpintel_mcp/api/formats/ics.py:149` — `_fmt_dt_local`. Defined but `render_ics` formats inline.
- `src/jpintel_mcp/api/formats/ics.py:154` — `_fmt_dt_utc`. Same as above.
- `src/jpintel_mcp/mcp/autonomath_tools/prompts.py:511` — `get_prompt_meta`. `register_prompts` is wired but `get_prompt_meta` itself is not invoked.
- `src/jpintel_mcp/mcp/autonomath_tools/gx_tool.py:186` — `list_themes`. `gx_tool.search_gx_programs` is called by `autonomath_wrappers.py:188`; `list_themes` is not.

**21 unused functions** total. The 14 in `_universal_envelope.py` collapse to 0 once the module is archived — leaves 7 genuine orphans in live files.

Note on internal-only helpers: the AST scan flagged 378 functions whose only references are within their defining file (private `_helpers`, intra-module call). Those are **kept** — they are live, not dead. The conservative report lists only true 0-callers.

## C. _archive/ directories with code

`src/jpintel_mcp/_archive/` contains 3 sub-archives, 36 `.py` files total:

- `src/jpintel_mcp/_archive/reasoning_2026-04-25/` — 18 files. 0 outbound imports of `jpintel_mcp.*` from production code. Self-contained relative imports only. Includes a `README.md` documenting the rehoming. Recommend: **leave** (clearly archived, archive directory has 0 inbound refs).
- `src/jpintel_mcp/_archive/embedding_2026-04-25/` — 11 files. README explicitly states "src/ tests/ scripts/ 全体で 0 件". One stale outbound import (`unigram_fallback.py:50` references the now-archived `unigram_search`). Recommend: **leave**.
- `src/jpintel_mcp/_archive/autonomath_tools_dead_2026-04-25/` — 7 files (sib_tool, cache, batch_tool, batch_handler, unigram_search, acceptance_stats_tool, response_sanitizer). 0 inbound refs. Recommend: **leave**.

All three archives are properly isolated. The grep `from jpintel_mcp._archive` returns 0 hits in production paths.

## D. Dead MCP tools (defined but not registered)

`mcp/autonomath_tools/__init__.py` registers 21 submodules via `from . import (...)` side-effect. Files present in the directory but **not** in that list:

- `citations_tools.py` — defines `verify_citations` (`@mcp.tool` at line 180, `AUTONOMATH_CITATIONS_ENABLED` env gate). Not imported by `__init__.py` → tool never registers. REST counterpart at `api/citations.py:174` IS live; only the MCP surface is dead.
- `evidence_packet_tools.py` — defines `build_evidence_packet` (`@mcp.tool` at line 148). Same pattern — REST live, MCP unregistered. Tested via `tests/test_evidence_packet.py` direct import (test path forces registration but server boot does not).
- `funding_stack_tools.py` — defines a `funding_stack_check` tool (`@mcp.tool` at line 180). Same pattern.
- `source_manifest_tools.py` — defines `get_source_manifest` (`@mcp.tool` at line 30). Same pattern.

**4 dead MCP tool files**. Each is a standalone file with `@mcp.tool` registration that never fires because the package `__init__.py` does not import them. The `scripts/distribution_manifest.yml:27` comment claims `verify_citations` is "default ON" — that comment is stale.

The other unregistered files in `autonomath_tools/` (`db.py`, `error_envelope.py`, `envelope_wrapper.py`, `resources.py`, `static_resources.py`, `tools_envelope.py`, `cs_features.py`, `prompts.py`, `gx_tool.py`, `loan_tool.py`, `enforcement_tool.py`, `mutual_tool.py`, `law_article_tool.py`) are utility modules imported transitively by the registered ones — they are **live**, not dead.

## E. Schema migrations

Skipped per task spec (migrations are immutable history).

## F. Disabled / skipped Python files

`find src/ scripts/ -name "*.py.disabled" -o -name "*.py.skip" -o -name "*.py.dead" -o -name "*.py.bak" -o -name "*.py.old"` returns 0 matches.

**(none).**

## Acceptance summary

- Audit doc: `/Users/shigetoumeda/jpcite/docs/_internal/dead_code_audit_2026-04-30.md`
- Modules with 0 imports: **4** (`_universal_envelope.py`, `middleware/{cost_cap,envelope_adapter,idempotency}.py`)
- Functions with 0 invocations: **21** total (14 in dead module + 7 in live modules)
- Dead MCP tools: **4** (`citations_tools`, `evidence_packet_tools`, `funding_stack_tools`, `source_manifest_tools` — registration never fires)
- Top-3 archive candidates:
  1. `src/jpintel_mcp/api/_universal_envelope.py` — entire module unused, 14 sub-functions dead
  2. `src/jpintel_mcp/api/middleware/{cost_cap,envelope_adapter,idempotency}.py` — 3 middleware classes defined but unmounted
  3. `src/jpintel_mcp/mcp/autonomath_tools/{citations,evidence_packet,funding_stack,source_manifest}_tools.py` — 4 MCP tool registrations never fire (REST counterparts are live and unaffected)

Conservative caveat: the dead-MCP-tool files were touched 2026-04-30 (today) — they may be brand-new code awaiting wire-up in `__init__.py`. **Verify with the author before archiving** rather than assuming permanent dead.

No deletes performed.
