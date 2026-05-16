# PERF-31: Lazy-load autonomath_tools chain modules — proposal

date: 2026-05-17
status: PROPOSAL (in-place refactor was auto-reverted by ruff TCH+I)
related tasks: PERF-31, PERF-33 (precedent for fastapi.openapi.models)

## Goal

Defer heavy `composable_tools` / `predictive_service` / `rule_tree` /
`session_context` / `time_machine` / `federated_mcp` imports out of
chain wrapper modules under `src/jpintel_mcp/mcp/autonomath_tools/`
(`wave51_chains.py`, `chain_wave51_b.py`, `composition_tools.py`,
`wave22_tools.py`, `industry_packs.py`, `prerequisite_chain_tool.py`)
so that server cold start skips ~95 ms of upstream package loading.

## Baseline (2026-05-17)

- `python -c "import jpintel_mcp.mcp.server"` cold 0.602 s / warm 0.336 s.
- `len(await mcp.list_tools())` = 184 (matches manifest).
- 95 ms cold cost from composable_tools / predictive_service / rule_tree
  / session_context / time_machine, dominated by wave51_chains.py +
  chain_wave51_b.py top-level imports.

## Refactor pattern attempted

`from __future__ import annotations` + TYPE_CHECKING block + function
body lazy imports. Tool wrappers (@mcp.tool) only call impl helpers;
heavy classes resolved at first invocation.

## Blocker

PERF-12 auto-format-on-save + ruff `I` + `TCH` rules consolidate
lazy imports back to module top-level within seconds. Verified via
mtime inspection.

## Recommended path forward

Option 3: per-file-ignore in pyproject.toml for the 6 chain modules
with `TCH002, TCH003, F401, I001`. Smallest blast radius, matches
existing `[tool.ruff.lint.per-file-ignores]` style. Then retry the
refactor and expect to save ~30-50 ms cold-start.

## Status

Not landed. Code unchanged. Operator decision needed on path forward.
