# Codex Tool Count Resolve Audit - 2026-05-17

Agent: Codex / Evening Agent D  
Scope: `/Users/shigetoumeda/jpcite-codex-evening` only  
Write scope used: this report only

## Recommendation

Choose **option B: 184 as the canonical published/default-gate SOT**.

Do **not** choose option A (`219` exact) for the current code. The latest root
`AGENTS.md` explicitly says volatile counts must not be hardcoded in agent entry
files and defines the canonical published MCP count as
`scripts/distribution_manifest.yml: tool_count_default_gates`. That manifest is
currently `184`. Current runtime is not `219` either: direct `mcp.list_tools()`
returns `231`, while the runtime distribution probe returns `272` under its
production-equivalent flag set. So `219 exact` matches neither current SOT files
nor current runtime behavior.

The technically coherent model in the current repo is:

- **Published/default-gate public count:** `184`
- **Runtime live count:** separately measured, currently `231` direct and `272`
  with the probe's experimental/default-on flag posture
- **Manifest floor behavior:** runtime must be `>= 184`, not exactly equal to
  `184`

## Evidence

### Canonical entry + distribution manifest

- `AGENTS.md` lines 64-76: live counts are not to be hardcoded; published MCP
  count points to `scripts/distribution_manifest.yml: tool_count_default_gates`;
  runtime count points to `len(await mcp.list_tools())`.
- `scripts/distribution_manifest.yml`:
  - `tool_count_default_gates: 184`
  - `tagline_ja` says `184-tool MCP`
  - stale comment still says "Public default-gate MCP surfaces advertise 179
    tools" and should be corrected.

### Public manifests

Observed via `jq`:

| Surface | tools array | meta tool_count |
|---|---:|---:|
| `server.json` | n/a | 184 |
| `site/server.json` | n/a | 184 |
| `mcp-server.json` | 184 | 184 |
| `mcp-server.full.json` | 184 | 184 |
| `site/mcp-server.json` | 184 | 184 |
| `site/mcp-server.full.json` | 184 | 184 |
| `dxt/manifest.json` | 184 | 184 |
| `mcp-server.core.json` | 39 | 39 |
| `mcp-server.composition.json` | 58 | 58 |

Well-known site descriptors also currently say `184`:

- `site/.well-known/agents.json`: `tools_count.public_default = 184`,
  `tools_count.runtime_verified = 184`
- `site/.well-known/trust.json`: `ai_use.tool_count_default_gates = 184`
- `site/.well-known/jpcite-federation.json`: `tool_count_runtime = 184`,
  `tool_count_manifest = 184`

### Runtime counts

Commands run:

```bash
.venv/bin/python -c "import os, asyncio; os.environ['AUTONOMATH_ENABLED']='1'; os.environ['AUTONOMATH_EXPERIMENTAL_MCP_ENABLED']='0'; from jpintel_mcp.mcp.server import mcp; print(len(mcp._tool_manager.list_tools())); print(len(asyncio.run(mcp.list_tools())))"
```

Result: `231`, `231`.

```bash
.venv/bin/python -c "import os, asyncio; os.environ['AUTONOMATH_ENABLED']='1'; os.environ['AUTONOMATH_EXPERIMENTAL_MCP_ENABLED']='1'; from jpintel_mcp.mcp.server import mcp; print(len(mcp._tool_manager.list_tools())); print(len(asyncio.run(mcp.list_tools())))"
```

Result: `272`, `272`.

```bash
.venv/bin/python scripts/probe_runtime_distribution.py
```

Result:

```text
[probe_runtime_distribution] OK - runtime route_count=364, tool_count=272 satisfies manifest floor=184.
```

This confirms `scripts/probe_runtime_distribution.py` already models
`tool_count_default_gates` as a floor, not an exact runtime count.

### Drift/probe script output

```bash
.venv/bin/python scripts/check_distribution_manifest_drift.py --fix
```

Result: OK. This is incomplete, because it misses JSON numeric key drift in
`site/_data/public_counts.json`.

```bash
.venv/bin/python scripts/check_mcp_drift.py
```

Result: fails because it still expects public full manifests/server manifests to
match runtime exactly. It reports runtime `231`, while public manifests are
`184`. That script conflicts with the AGENTS/distribution-manifest floor model.

```bash
.venv/bin/python scripts/ops/check_mcp_drift.py --json
```

Result: ground truth `184`, but drift in:

- `site/llms-full.txt`: `[155]`
- `site/llms-full.en.txt`: `[169]`
- `CLAUDE.md`: no count found

The `CLAUDE.md` finding conflicts with the new agent-entry policy: agent shims
should point to live sources and should not contain hardcoded volatile counts.

```bash
.venv/bin/python scripts/check_tool_count_consistency.py --fix-list
```

Result: many user-visible stale `155`/`165` occurrences remain across generated
site/docs/registry/email surfaces. This script correctly treats runtime as
`>= public_count`, but its output is broader than the distribution-manifest
guard.

## Surfaces To Change

### Keep at 184

Do not change these to `219`:

- `scripts/distribution_manifest.yml: tool_count_default_gates`
- `server.json`, `site/server.json`
- `mcp-server.json`, `mcp-server.full.json`
- `site/mcp-server.json`, `site/mcp-server.full.json`
- `dxt/manifest.json`
- `docs/mcp-tools.md`
- `README.md` top-level public MCP count copy
- `site/.well-known/agents.json`
- `site/.well-known/trust.json`
- `site/.well-known/jpcite-federation.json`

### Correct stale 179/155 public-count surfaces

- `scripts/distribution_manifest.yml`: update the header comment from `179`
  to `184`.
- `scripts/generate_public_counts.py:134`: replace hardcoded `155` with the
  manifest value, preferably by reading `tool_count_default_gates`.
- `site/_data/public_counts.json:18`: `mcp_tools_total` is `179`; regenerate or
  set to `184`.
- `site/index.html:889`: static fallback is `155`; should become `184` or be
  regenerated from `public_counts`.
- `site/facts.html:420`: visible `MCP 機能数: 179`; should become `184`.
- `site/llms-full.txt`: visible stale `155` at lines including `10`, `137`,
  `253`, `982`.
- `site/llms-full.en.txt`: stale `169` detected by ops drift, plus broad
  scanner found stale `155` at line `47`.

Broad stale list from `scripts/check_tool_count_consistency.py --fix-list`
includes additional generated/public docs such as:

- `site/audiences/dev.html`
- `site/press/fact-sheet.md`
- `site/en/{index,about,products,pricing,getting-started}.html`
- `site/connect/{chatgpt,claude-code,codex,cursor}.html`
- `site/qa/**`
- `site/compare/**`
- `docs/press_kit.md`
- `docs/organic_outreach_templates.md`
- `docs/launch/**`
- `docs/marketplace/**`
- `docs/distribution/discovery_map_2026_05_11.md`
- `scripts/mcp_registries_submission.json`
- `scripts/registry_submissions/**`
- `src/jpintel_mcp/email/templates/onboarding_day1.{html,txt}`

### Fix scripts/checkers so 184 is durable

- `scripts/check_mcp_drift.py`
  - Load the canonical public count from `scripts/distribution_manifest.yml`
    instead of comparing public manifests to runtime exact.
  - Validate full public manifests/server manifests against `184`.
  - Validate runtime as `>= 184` and report the actual runtime separately.
  - Remove or widen the stale runtime upper range `[130,200]`, because current
    runtime can be `231` or `272`.

- `scripts/probe_runtime_distribution.py`
  - Keep the current floor semantics.
  - Update any stale comments that imply static manifests should equal runtime.

- `scripts/ops/check_mcp_drift.py`
  - Treat `scripts/distribution_manifest.yml` as ground truth instead of
    `server.json`.
  - Remove `CLAUDE.md` from text sites or invert the assertion to require a
    pointer/no hardcoded count.
  - Include `site/_data/public_counts.json` and well-known descriptors in the
    JSON sites if this remains an ops guard.

- `scripts/check_distribution_manifest_drift.py`
  - Add structured JSON checks for numeric keys such as `mcp_tools_total`,
    top-level/nested `tool_count`, and `tools_count.*`.
  - Current regex-only scanning misses `site/_data/public_counts.json`.

- `scripts/sync_mcp_public_manifests.py`
  - It currently regenerates public manifests from runtime `mcp.list_tools()`;
    running it now would push the public full manifests toward `231`/`272`.
  - For option B, split "published default manifest sync" from "runtime
    inventory sync", or make it read the canonical published cohort/list rather
    than all runtime tools.

- `scripts/check_tool_count_consistency.py`
  - Keep the floor model; after the stale surfaces are fixed, make this part of
    the verification path because it finds pages the distribution checker misses.

### Fix stale tests

- `tests/test_mcp_public_manifest_sync.py`
  - Still asserts `155` and exact runtime-manifest equality.
  - Replace constants with `scripts/distribution_manifest.yml` values and use
    floor semantics for runtime.

- `tests/test_static_public_reachability.py`
  - Still pins several `155` strings for generated pages/facts.
  - Update to `184` or read `site/_data/public_counts.json`/manifest.

- Keep `tests/test_agent_entry_sot.py` policy: agent entry files must avoid
  hardcoded counts and point to live sources.

### Mark stale internal decision docs as superseded

These are not public SOT, but they are confusing:

- `docs/_internal/HARNESS_H1_H2_2026_05_17.md` says `219 exact`; add a
  supersession note pointing to this audit and AGENTS/distribution manifest.
- `docs/_internal/HARNESS_H7_H8_2026_05_17.md:54` says
  `mcp-server.full.json: tool_count=219`, while the current file is `184`.

## Verification Commands

After fixes:

```bash
jq '{file:input_filename,tools:(.tools|length),meta:._meta.tool_count,publisher:._meta["io.modelcontextprotocol.registry/publisher-provided"].tool_count}' \
  mcp-server.json mcp-server.full.json site/mcp-server.json site/mcp-server.full.json dxt/manifest.json

rg -n "tool_count_default_gates|tagline_ja" scripts/distribution_manifest.yml

.venv/bin/python scripts/check_distribution_manifest_drift.py --fix
.venv/bin/python scripts/check_tool_count_consistency.py --fix-list
.venv/bin/python scripts/probe_runtime_distribution.py
.venv/bin/python scripts/check_mcp_drift.py
.venv/bin/python scripts/ops/check_mcp_drift.py --json

.venv/bin/python -c "import os, asyncio; os.environ['AUTONOMATH_ENABLED']='1'; os.environ['AUTONOMATH_EXPERIMENTAL_MCP_ENABLED']='0'; from jpintel_mcp.mcp.server import mcp; print(len(asyncio.run(mcp.list_tools())))"
.venv/bin/python -c "import os, asyncio; os.environ['AUTONOMATH_ENABLED']='1'; os.environ['AUTONOMATH_EXPERIMENTAL_MCP_ENABLED']='1'; from jpintel_mcp.mcp.server import mcp; print(len(asyncio.run(mcp.list_tools())))"

.venv/bin/pytest tests/test_distribution_manifest.py -v
.venv/bin/pytest tests/test_agent_entry_sot.py tests/test_mcp_public_manifest_sync.py -v
```

Expected final state:

- Public/default SOT remains `184`.
- Runtime remains separately reported and may be greater than `184`.
- No public/generated surface says `155`, `169`, `179`, or `219` as the current
  MCP tool count.
- Agent entry files contain pointers only, no hardcoded volatile counts.

## Parent Follow-Up Implementation

After this audit, CodeX implemented the option B contract:

- `scripts/check_mcp_drift.py` now treats public/default manifests as the
  `tool_count_default_gates` SOT and treats runtime as `>= public_count`.
- `tests/test_mcp_public_manifest_sync.py` now validates public manifests as a
  runtime subset instead of requiring exact runtime equality.
- `scripts/distribution_manifest.yml` header comment now says 184, matching the
  actual `tool_count_default_gates`.
- `scripts/ops/check_mcp_drift.py` no longer requires `CLAUDE.md` to contain a
  hardcoded count, because agent shims intentionally point to `AGENTS.md`.
- Stale public/user-facing 155/165/169/179 top-line MCP count references were
  updated to 184 across `site/`, `docs/`, registry submission copy, and
  onboarding email templates.
- `scripts/regen_llms_full.py` and `scripts/regen_llms_full_en.py` were updated
  so regenerated `llms-full*` files do not reintroduce stale 155/169 counts.

Verification after implementation:

```text
.venv/bin/python scripts/check_distribution_manifest_drift.py        PASS
.venv/bin/python scripts/check_mcp_drift.py                          PASS
.venv/bin/python scripts/ops/check_mcp_drift.py --json               PASS
.venv/bin/python scripts/check_tool_count_consistency.py             PASS
.venv/bin/pytest tests/test_mcp_public_manifest_sync.py -q           9 passed
```
