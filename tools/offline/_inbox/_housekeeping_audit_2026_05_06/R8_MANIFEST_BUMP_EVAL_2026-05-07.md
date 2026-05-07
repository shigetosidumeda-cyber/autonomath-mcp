# R8 — Manifest tool-count bump 139→146 evaluation (2026-05-07)

**Goal**: read-only audit of whether the 7 post-manifest tools that R8_MCP_FULL_COHORT_2026-05-07.md surfaced are prod-ready enough to fold into the static manifests (v0.3.4 → v0.3.5 candidate). NO manifest mutation in this pass — the v0.3.5 bump is an operator decision held until launch hygiene allows it.

**Companion**: `R8_MCP_FULL_COHORT_2026-05-07.md` documents how the full cohort flag set drives `mcp.list_tools()` to 146 (139 manifest floor + 7 post-manifest landings). This doc is the prod-readiness gate evaluation.

**Constraints honored**

- Read-only — zero manifest / fixture / tool-source byte changes.
- LLM API budget = 0 (file inspection + grep + git status only; no model calls).
- Internal-hypothesis framing — 146 at runtime ≠ 146 launched. The launch surface is whichever floor we ship in `pyproject.toml` / `server.json` / `mcp-server.json` / `mcp-server.full.json` / `dxt/manifest.json` / `smithery.yaml` / `scripts/distribution_manifest.yml`.

## 1. Headline numbers

| Item | Value | Notes |
| --- | --- | --- |
| Current manifest floor | **139** | All 5 manifest surfaces + `distribution_manifest.yml` (`tool_count_default_gates: 139`). Verified 2026-05-07. |
| Runtime full-cohort count | **146** | `len(await mcp.list_tools())` with the doc §2 prod-equivalent flag set. |
| Post-manifest delta | **+7** | Tools landed 2026-05-07 *after* the v0.3.4 manifest cut. |
| Candidate bump version | **v0.3.5 (patch)** | Or v0.4.0 if we treat the +7 surface area as a minor expansion; per CHANGELOG cadence v0.3.x patch is sufficient (zero breaking change). |

## 2. The 7 post-manifest tools — prod-readiness audit

| # | Tool | Impl file | Decorator | Test file | Disclaimer envelope | sample_arguments in manifest | Sensitive cohort | Prod-ready? |
|---|------|-----------|-----------|-----------|---------------------|------------------------------|------------------|-------------|
| 1 | `query_at_snapshot_v2` | `src/jpintel_mcp/mcp/autonomath_tools/time_machine_tools.py` (525 lines) | `@mcp.tool(annotations=_READ_ONLY)` ✓ | `tests/test_time_machine.py` (8 tests) | `_DISCLAIMER` injected on every response (§52 / §47条の2 fence) ✓ | NOT in any manifest (post-cut) | DEEP-22 time machine — yes, sensitive | **READY** |
| 2 | `query_program_evolution` | `time_machine_tools.py` (same file) | `@mcp.tool(annotations=_READ_ONLY)` ✓ | `tests/test_time_machine.py` (covered) | `_DISCLAIMER` injected ✓ | NOT in any manifest (post-cut) | DEEP-22 sensitive | **READY** |
| 3 | `shihoshoshi_dd_pack_am` | `src/jpintel_mcp/mcp/autonomath_tools/shihoshoshi_tools.py` (488 lines) | `@mcp.tool(annotations=_READ_ONLY)` ✓ | `tests/test_shihoshoshi_tools.py` (6 tests) — has explicit `"shihoshoshi_dd_pack_am" in tool_names` registration assert | `_DISCLAIMER_SHIHOSHOSHI` injected (§52 / §72 / §1 fence) ✓ | NOT in any manifest (post-cut) | DEEP-30 司法書士 — sensitive | **READY** |
| 4 | `search_kokkai_utterance` | `src/jpintel_mcp/mcp/autonomath_tools/kokkai_tools.py` (402 lines) | `@mcp.tool(annotations=_READ_ONLY)` ✓ | `tests/test_kokkai_shingikai.py` (6 tests, including `test_search_kokkai_utterance_tool_integration` MCP envelope contract) | `_DISCLAIMER_KOKKAI` injected (§52 / §47条の2 / §72 / §3) ✓ | NOT in any manifest (post-cut) | DEEP-39 国会発言 — sensitive | **READY** |
| 5 | `search_shingikai_minutes` | `kokkai_tools.py` (same file) | `@mcp.tool(annotations=_READ_ONLY)` ✓ | `tests/test_kokkai_shingikai.py` (covered) | `_DISCLAIMER_SHINGIKAI` injected (§52 / §47条の2 / §72) ✓ | NOT in any manifest (post-cut) | DEEP-39 審議会議事録 — sensitive | **READY** |
| 6 | `search_municipality_subsidies` | `src/jpintel_mcp/mcp/autonomath_tools/municipality_tools.py` (277 lines) | `@mcp.tool(annotations=_READ_ONLY)` ✓ | `tests/test_municipality_subsidy.py` (5 tests) | **Intentionally NO `_disclaimer`** — `source_attribution` envelope only (政府著作物 §13, public-domain listing per DEEP-44 §7). Documented in module docstring lines 17-18. ✓ | NOT in any manifest (post-cut) | DEEP-44 自治体 — NOT sensitive (public-domain corpus) | **READY** |
| 7 | `get_pubcomment_status` | `src/jpintel_mcp/mcp/autonomath_tools/pubcomment_tools.py` (256 lines) | `@mcp.tool(annotations=_READ_ONLY)` ✓ | `tests/test_pubcomment.py` (5 tests) | `_DISCLAIMER_PUBCOMMENT` injected (§52 / §47条の2 / §72 / §1) ✓ | NOT in any manifest (post-cut) | DEEP-45 e-Gov パブコメ — sensitive | **READY** |

**Prod-readiness summary**: 7 / 7 ready. Implementation files (1,948 LoC total), test files (30 test functions across 5 files), disclaimer envelopes (6 sensitive cohort hits + 1 documented exemption), and runtime registration (full-cohort flag set proves all 7 hit `mcp.list_tools()`) are all in place.

**Honest gap (not a blocker)**: `sample_arguments` is missing for all 7 because they were cut after the v0.3.4 manifest snapshot. The dxt / mcp-server / server.json manifests carry per-tool `sample_arguments` blocks for the 139 floor — bumping to 146 will require composing 7 new sample-args blocks (operator step in the v0.3.5 publish flow).

## 3. Manifest surfaces that need updating for a 139 → 146 bump

Surfaces touched by `manifest-bump` cadence (per `scripts/check_distribution_manifest_drift.py` and `scripts/check_tool_count_consistency.py`):

| Surface | Current value | Target value (option A) | Owner |
| --- | --- | --- | --- |
| `pyproject.toml` `description` (`139 MCP tools`) | 139 | 146 | release flow |
| `server.json` `tool_count` | 139 | 146 | release flow |
| `mcp-server.json` `tool_count` (×2) | 139 | 146 | release flow |
| `mcp-server.full.json` (count of `"name":` entries) | 141 entries (139 tools + 2 manifest-level names — `autonomath-mcp` + `Bookyou株式会社`) | 148 entries (146 tools + 2 manifest-level) | release flow + per-tool blocks |
| `dxt/manifest.json` description (`139 tools`) + per-tool blocks | 139 | 146 | release flow + per-tool blocks |
| `smithery.yaml` description (`139 tools`) | 139 | 146 | release flow |
| `scripts/distribution_manifest.yml` `tool_count_default_gates: 139` | 139 | 146 | release flow |
| `pyproject.toml` `version` | 0.3.4 | 0.3.5 | release flow |
| `server.json` `version` (×2) | 0.3.4 | 0.3.5 | release flow |
| `mcp-server.json` `version` (×2) | 0.3.4 | 0.3.5 | release flow |
| `src/jpintel_mcp/__init__.py` `__version__` | 0.3.4 | 0.3.5 | release flow |
| `CLAUDE.md` (`139 tools at default gates` mentions) | 139 (×N) | 146 | docs cleanup |
| Public copy: `site/llms.txt`, README, OpenAPI description, marketing pages | 139 / `139-tool` etc. | 146 | docs + site rebuild |

There is also a dedicated drift checker (`scripts/check_tool_count_consistency.py`) that introspects the runtime via subprocess and greps user-visible surfaces — bumping the floor to 146 in static files without restarting the runtime probe with the full cohort flags would still pass because the checker uses `AUTONOMATH_ENABLED=1` only by default; the asymmetry between the bare-shell baseline (107) and the full-cohort runtime (146) is documented in §6 below.

## 4. Bump option A vs option B

### Option A — bump manifests to 146 now (v0.3.4 → v0.3.5)

**Pros**

- Resolves the silent drift between runtime (146) and published manifests (139). Tracks honestly.
- Customers querying registry surfaces (PyPI / smithery / dxt) see the 146 surface that they actually get on connect (when full-cohort flags are set on the server side).
- Keeps `scripts/check_distribution_manifest_drift.py` green for the new floor.
- Allows the 7 new tool docstrings (already loaded into running tool descriptions) to surface in registry-driven indexes.

**Cons**

- Requires a PyPI publish (`twine upload dist/*` per the release checklist) to actually ship the bumped `pyproject.toml` floor — operator step bound to `PYPI_TOKEN`. Not a blocker but a launch-window concern.
- Requires composing 7 new `sample_arguments` / per-tool description blocks for `dxt/manifest.json` + `mcp-server.full.json` — there is no auto-generator that emits these from the runtime tool registry today (verified: `find /Users/shigetoumeda/jpcite -name "manifest_bump*"` returns zero hits; the cadence is manual).
- 4 of the 7 post-manifest tools require explicit experimental cohort flags (`AUTONOMATH_EXPERIMENTAL_MCP_ENABLED` etc., per R8_MCP_FULL_COHORT §2). If a downstream consumer connects without these flags, they get 107 tools — bumping the manifest to 146 then misrepresents the floor for that connection mode. This is the same skew the doc surfaces in §3 (per-cohort isolation).
- A bump locks in the +39 wave24 / intel_wave31 / intel_wave32 cohort as part of the canonical floor, which means rolling back any of those experimental cohorts post-bump becomes a manifest regression.

### Option B — keep manifest at 139, document the +7 as "post-launch additions"

**Pros**

- Zero release-flow churn. v0.3.4 ships as-is, the 7 post-manifest tools are honest about being "internal hypothesis at HEAD" rather than published surface area.
- Avoids locking in the experimental-cohort tax: if any of the +7 needs a fix or rollback before launch, no manifest needs to be re-cut.
- README disclosure ("post-manifest landings — see CHANGELOG `[Unreleased]` section") is sufficient because the runtime surface is self-describing via `mcp.list_tools()`. Customers see what's there even without a manifest entry.
- Matches the discipline R8 doc itself records: "139 manifest = 132 manifest-stable + 7 manifest-pending. At runtime, all 132 stable + all 7 pending are exposed → 139 + 7 = 146." The pending-vs-stable distinction is already explicit in our docs; B preserves it.
- Honors `feedback_completion_gate_minimal` — manifest bump is not on the critical path of the minimal blocker list; pushing it post-launch is consistent with that bar.

**Cons**

- Drift between runtime and manifest persists, even if the doc explains it.
- The drift checker passes at 139 but does not surface "+7 post-manifest" — operator needs to remember the asymmetry.
- Customers who treat the registry manifest as the canonical surface area count (and many do — the `tool_count` field is what shows on smithery / dxt UIs) under-count the 7 cohort.

## 5. Recommendation (operator decision, read-only suggestion)

**Recommend Option B** for the next 7-14 days, then revisit:

1. **Today (read-only)**: keep `139` floor. Add a single line to `CHANGELOG.md` `[Unreleased]` section listing the 7 post-manifest tools and their landing date (2026-05-07). No manifest mutation, no version bump.
2. **Next launch hygiene cycle (post 2026-05-14, after the minimal-blocker gate clears per `R8_HIGH_RISK_PENDING_LIST.md`)**: re-evaluate. By then either (a) the experimental cohort gates collapse (4 flags become default-on and the +39 manifest entries become baseline), in which case bumping to 146 is honest, or (b) one of the 7 needs rollback, in which case we held off correctly.
3. **Manual sample_arguments generation step at the time of bump**: compose 7 new per-tool blocks for `dxt/manifest.json` + `mcp-server.full.json` from the runtime tool descriptions. Estimated 30-60 min operator time; not LLM-assisted (memory `feedback_no_operator_llm_api`).
4. **Drift checker companion**: when the bump lands, also bump `scripts/distribution_manifest.yml` `tool_count_default_gates: 146` so the read-only drift checker is the single source of truth for the new floor.

**Rationale**: 7 / 7 are prod-ready. The bump is feasible. But "feasible" is not the same as "blocking" — and per `feedback_completion_gate_minimal` we should not gate launch on a manifest-bump cosmetic fix. The runtime surface is honest at 146 to anyone who probes it; the manifest surface is honest at 139 to anyone who reads it. The asymmetry is documented in `R8_MCP_FULL_COHORT_2026-05-07.md` and now in this doc.

If the user opts for Option A regardless, the operator step is: (1) compose 7 sample_args blocks, (2) run `manifest-bump` cadence (manual sed-like flow per §3 table — there is no `scripts/manifest_bump.py` today), (3) rebuild `dist/`, (4) publish PyPI + npm + smithery via the release checklist, (5) bump `distribution_manifest.yml` floor.

## 6. Honest gaps recorded by this audit

- No automated `scripts/manifest_bump.py` or equivalent CLI exists. The "manifest-bump CLI" referenced in CLAUDE.md is a pattern, not a tool — the cadence is manual edits to 5 manifest files + `distribution_manifest.yml` + `__init__.py` + `pyproject.toml`. This is feasible (was done for v0.3.0 → v0.3.1 → v0.3.2 → v0.3.3 → v0.3.4) but not push-button.
- No `sample_arguments` auto-generation from the runtime registry. The 7 new blocks are manual writes.
- Per-cohort isolation skew: the +39 wave24/intel_wave31/intel_wave32 manifest entries reach the runtime only when 4 experimental flags are explicitly set. The current published manifest *already counts* these 39 as part of the 139 floor — so the bump 139→146 inherits the same skew, not creates it.
- `mcp-server.full.json` carries 141 `"name":` entries today (139 tools + 2 manifest-level — `autonomath-mcp` package name and `Bookyou株式会社` author name). The bump to 146 makes that 148.

## 7. Files referenced by this audit

- `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_MANIFEST_BUMP_EVAL_2026-05-07.md` — this doc.
- `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_MCP_FULL_COHORT_2026-05-07.md` — companion (full-cohort 146 demonstration).
- `src/jpintel_mcp/mcp/autonomath_tools/time_machine_tools.py` (525 LoC) — `query_at_snapshot_v2` + `query_program_evolution`.
- `src/jpintel_mcp/mcp/autonomath_tools/shihoshoshi_tools.py` (488 LoC) — `shihoshoshi_dd_pack_am`.
- `src/jpintel_mcp/mcp/autonomath_tools/kokkai_tools.py` (402 LoC) — `search_kokkai_utterance` + `search_shingikai_minutes`.
- `src/jpintel_mcp/mcp/autonomath_tools/municipality_tools.py` (277 LoC) — `search_municipality_subsidies`.
- `src/jpintel_mcp/mcp/autonomath_tools/pubcomment_tools.py` (256 LoC) — `get_pubcomment_status`.
- `tests/test_time_machine.py` / `test_shihoshoshi_tools.py` / `test_kokkai_shingikai.py` / `test_municipality_subsidy.py` / `test_pubcomment.py` (30 test functions total).
- `pyproject.toml` / `server.json` / `mcp-server.json` / `mcp-server.full.json` / `dxt/manifest.json` / `smithery.yaml` / `scripts/distribution_manifest.yml` (manifest surfaces).

No file modified by this audit.
