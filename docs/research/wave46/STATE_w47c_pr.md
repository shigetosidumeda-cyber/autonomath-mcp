# STATE: Wave 46 task 47.C — autonomath_tools/ → jpcite_tools/ alias

Date: 2026-05-12
Branch: `feat/jpcite_2026_05_12_wave46_rename_47c_file_path`
Worktree: `/tmp/jpcite-w46-rename-47c`
Memory anchors: `project_jpcite_internal_autonomath_rename` /
`feedback_destruction_free_organization` (rm/mv 禁止) /
`feedback_dual_cli_lane_atomic`

## Scope

Implement axis **47.C** of the brand-rename plan: deliver a file-path-level
alias package `src/jpintel_mcp/mcp/jpcite_tools/` that re-exports every
module in the legacy `src/jpintel_mcp/mcp/autonomath_tools/` package so
that downstream callers can migrate their import paths from
`jpintel_mcp.mcp.autonomath_tools.*` to `jpintel_mcp.mcp.jpcite_tools.*`
without any change to the canonical implementation.

Destruction-free per `feedback_destruction_free_organization`: zero
`rm`/`mv`, zero file rewrite under `autonomath_tools/`. The alias layer is
strictly additive — overlay only.

No duplicate MCP-tool registration per `feedback_dual_cli_lane_atomic`:
each wrapper is a pure `from autonomath_tools.<name> import *` so the
underlying `@mcp.tool` decorators run exactly once (Python module cache
keeps the import idempotent).

## Files touched

| File                                                              | Change        |   Δ LOC |
|-------------------------------------------------------------------|---------------|---------|
| `src/jpintel_mcp/mcp/jpcite_tools/__init__.py`                    | new package init | +52 |
| `src/jpintel_mcp/mcp/jpcite_tools/<73 sibling wrappers>.py`       | new wrappers (1:1) | +1027 (avg 14 LOC each) |
| `tests/test_w47c_jpcite_tools_alias.py`                           | new test (10 cases) | +313 |
| `docs/research/wave46/STATE_w47c_pr.md`                           | this STATE doc | ~150 |
| **Total**                                                         |               | **~1542** |

Sibling wrapper count: 74 `.py` files in `autonomath_tools/` minus
`__init__.py` = 73 wrappers + 1 alias `__init__.py` = **74 files** in the
new `jpcite_tools/` directory.

The legacy `src/jpintel_mcp/mcp/autonomath_tools/` directory is
untouched (74 `.py` files, same on-disk hashes as `main`).

## Wrapper pattern

Each `jpcite_tools/<name>.py` is a strict 14-LOC re-export shell:

```python
"""jpcite_tools.<name> — Wave 46.47.C re-export alias for autonomath_tools.<name>.
…
"""

from jpintel_mcp.mcp.autonomath_tools.<name> import *  # noqa: F401, F403
```

The `__init__.py` mirrors the package-level surface with the same
star-import idiom. Total wrapper body is 1 statement so there is zero
risk of double-registration or shadowing.

Python `from X import *` semantics caveat: without `__all__` defined on
the canonical module, the star-import re-exports only the names that
the canonical module *owns* (functions, classes, module-level globals).
Transitively imported names (e.g. `typing.Annotated`, `pydantic.Field`)
are intentionally NOT re-exported — this is correct: callers who need
typing imports should pull them from the canonical source, not from a
brand-rename alias.

## Verification

### bug-free verify chain

1. **Import path compatibility** — `python -c "from jpintel_mcp.mcp.jpcite_tools import health_tool"`
   completes without error and exposes `deep_health_am` (the canonical
   MCP tool function). Same identity check holds for all 5 sampled
   submodules in the test suite.

2. **No duplicate MCP-tool registration** — importing
   `jpintel_mcp.mcp.jpcite_tools` *after* `jpintel_mcp.mcp.autonomath_tools`
   does NOT change FastMCP's tool count. Python module cache makes the
   wrapper `from autonomath_tools.X import *` resolve to an already-imported
   module so the `@mcp.tool` decorators never run a second time. Test
   `test_alias_does_not_duplicate_mcp_tool_registration` enforces this.

3. **Pre-existing test green** — re-ran the autonomath-importing test
   surface (`test_mcp_resources`, `test_evidence_packet`, `test_saburoku_gate`,
   `test_funding_stack_checker`): **109 passed**.

4. **Pre-existing `Tool already exists: compose_audit_workpaper` warning**
   reproduces on plain `import jpintel_mcp.mcp.autonomath_tools` *before*
   any of the 47.C changes — it is not introduced by this PR.

### New test result

```
tests/test_w47c_jpcite_tools_alias.py::test_legacy_autonomath_dir_untouched PASSED
tests/test_w47c_jpcite_tools_alias.py::test_jpcite_alias_dir_exists PASSED
tests/test_w47c_jpcite_tools_alias.py::test_jpcite_alias_mirrors_every_autonomath_file PASSED
tests/test_w47c_jpcite_tools_alias.py::test_every_wrapper_is_pure_reexport PASSED
tests/test_w47c_jpcite_tools_alias.py::test_jpcite_alias_package_imports PASSED
tests/test_w47c_jpcite_tools_alias.py::test_jpcite_submodule_equivalence_smoke PASSED
tests/test_w47c_jpcite_tools_alias.py::test_alias_does_not_duplicate_mcp_tool_registration PASSED
tests/test_w47c_jpcite_tools_alias.py::test_wrapper_files_are_small_and_disciplined PASSED
tests/test_w47c_jpcite_tools_alias.py::test_alias_count_matches_canonical_count_exactly PASSED
tests/test_w47c_jpcite_tools_alias.py::test_no_legacy_brand_logic_imported_into_alias PASSED

10 passed in 1.96s
```

### Compatibility verdict

- **Backward**: `from jpintel_mcp.mcp.autonomath_tools.tools import …` still
  works — the legacy path is the canonical implementation.
- **Forward**: `from jpintel_mcp.mcp.jpcite_tools.tools import …` now works
  and resolves to the same module objects (identity check passes).
- **MCP surface**: tool registration count is unchanged. No new tools
  registered. No tools shadowed.
- **Brand visibility**: callers can migrate import paths file-by-file at
  their leisure. Both styles can co-exist in the same codebase during
  the migration window.

## What this PR does NOT do

- Does NOT delete or rename any file under `autonomath_tools/`.
- Does NOT touch the `AUTONOMATH_*` environment variables (covered by
  task 46.E aliaschoices).
- Does NOT touch the `autonomath.db` filename (covered by task 46.C
  symlink overlay).
- Does NOT touch the manifest file (covered by task 46.F dual-read).
- Does NOT modify any canonical module — the rename is overlay-only.
- Does NOT add a separate `__all__` list to `autonomath_tools.<X>`
  (call-site migration is fine without `__all__` because the public
  surface is the set of `@mcp.tool`-decorated functions, which are
  module-local and DO get re-exported by `import *`).
