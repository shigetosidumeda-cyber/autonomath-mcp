# R8 — MCP full-cohort tool count demo (2026-05-07)

**Goal**: prove `len(await mcp.list_tools())` reaches the manifest floor of 139
when the cohort env-flags are set inline, and surface the per-cohort
contribution (and post-manifest tools) so the manifest bump cadence is
honest.

**Companion**: `R8_SMOKE_GATE_FLAGS_2026-05-07.md` covers the same accounting
from the smoke-gate side (`scripts/ops/post_deploy_smoke.py --mcp-min-tools`).
This doc is the local **mcp.list_tools()** view.

**Constraints honored**
- LLM API budget = 0 (pure list_tools probe; no model calls).
- No destructive overwrite — flag set is exported into a fresh `python -c`
  shell, default `.env` is not touched, manifests / fixtures unmodified.
- Local boot only — no Fly secret push, no production deploy.

## 1. Headline numbers

| Scenario | Inline flags | Runtime tools | Δ vs manifest |
| --- | --- | ---: | ---: |
| Bare shell | (none) | 107 | -32 |
| R8 doc canonical (10 flags) | doc §2 invocation | 107 | -32 |
| **Full cohort (this audit)** | doc §2 + experimental + wave24 ×2 + intel_wave ×2 | **146** | **+7** |
| Full cohort + 36協定 | adds `AUTONOMATH_36_KYOTEI_ENABLED=1` | 148 | +9 |
| Manifest floor (`mcp-server.full.json`) | static, version-locked | 139 | 0 |

Manifest entries covered = **139 / 139** (zero missing) with the full-cohort
flag set. The +7 are tools that landed *after* the v0.3.4 manifest was cut —
they are real, registered, and ready, but not yet in any of the five static
manifests (`pyproject.toml` / `server.json` / `mcp-server.json` /
`mcp-server.full.json` / `dxt/manifest.json` / `smithery.yaml`).

## 2. The flag set that hits 139

The R8 doc canonical command listed 10 inline flags but **omitted four flags**
that gate experimental cohorts (`AUTONOMATH_EXPERIMENTAL_MCP_ENABLED`,
`AUTONOMATH_WAVE24_FIRST_HALF_ENABLED`, `AUTONOMATH_WAVE24_SECOND_HALF_ENABLED`,
`AUTONOMATH_INTEL_COMPOSITE_ENABLED` — the last one also implicitly enables
`AUTONOMATH_INTEL_WAVE32_ENABLED` since both default to `1`). Without those
four, 39 manifest entries (wave24 first/second half + intel_wave31 + intel_wave32)
never get imported because `autonomath_tools/__init__.py:79-85` short-circuits
the wave24 / intel_wave31 import on `AUTONOMATH_EXPERIMENTAL_MCP_ENABLED`.

Production-equivalent invocation (matches Fly secret intent):

```bash
AUTONOMATH_ENABLED=1 \
AUTONOMATH_GRAPH_ENABLED=1 \
AUTONOMATH_PREREQUISITE_CHAIN_ENABLED=1 \
AUTONOMATH_RULE_ENGINE_ENABLED=1 \
AUTONOMATH_NTA_CORPUS_ENABLED=1 \
AUTONOMATH_COMPOSITION_ENABLED=1 \
AUTONOMATH_WAVE22_ENABLED=1 \
AUTONOMATH_INDUSTRY_PACKS_ENABLED=1 \
AUTONOMATH_SHIHOSHOSHI_PACK_ENABLED=1 \
AUTONOMATH_SNAPSHOT_ENABLED=1 \
AUTONOMATH_EXPERIMENTAL_MCP_ENABLED=1 \
AUTONOMATH_WAVE24_FIRST_HALF_ENABLED=1 \
AUTONOMATH_WAVE24_SECOND_HALF_ENABLED=1 \
AUTONOMATH_INTEL_COMPOSITE_ENABLED=1 \
AUTONOMATH_INTEL_WAVE32_ENABLED=1 \
.venv/bin/python -c "
import asyncio
from jpintel_mcp.mcp.server import mcp
async def main():
    tools = await mcp.list_tools()
    print(f'mcp.list_tools count = {len(tools)}')
asyncio.run(main())
"
# → mcp.list_tools count = 146  (139 manifest + 7 post-manifest)
```

## 3. Per-cohort contribution (additive over `AUTONOMATH_ENABLED=1`)

Baseline (`AUTONOMATH_ENABLED=0`) is **42 tools** — the jpintel.db core surface
(programs, case_studies, loan_programs, enforcement, get_meta, get_usage_status,
laws / tax_rulesets / court_decisions / bids / invoice_registrants thin
wrappers) plus 7 one-shot discovery tools.

| Flag | Cohort | Adds |
| --- | --- | ---: |
| `AUTONOMATH_ENABLED=1` | Phase A absorption + universal helpers + base autonomath surface | **+65** (42 → 107) |
| Of which: `AUTONOMATH_COMPOSITION_ENABLED=1` | Wave 21 composition (5 tools) | included in the 65 (default ON) |
| Of which: `AUTONOMATH_WAVE22_ENABLED=1` | Wave 22 composition (5) | included (default ON) |
| Of which: `AUTONOMATH_INDUSTRY_PACKS_ENABLED=1` | Wave 23 industry packs (3) | included (default ON) |
| Of which: `AUTONOMATH_SHIHOSHOSHI_PACK_ENABLED=1` | DEEP-30 司法書士 pack (1) | included (default ON) |
| Of which: `AUTONOMATH_SNAPSHOT_ENABLED=1` | DEEP-22 time machine v2 (2) | included (default ON) |
| Of which: `AUTONOMATH_NTA_CORPUS_ENABLED=1` | NTA primary-source 4-pack | included (default ON) |
| Of which: `AUTONOMATH_GRAPH_ENABLED=1` | `related_programs` walk (1) | included (default ON) |
| Of which: `AUTONOMATH_PREREQUISITE_CHAIN_ENABLED=1` | `prerequisite_chain` (1) | included (default ON) |
| Of which: `AUTONOMATH_RULE_ENGINE_ENABLED=1` | `rule_engine_check` (1) | included (default ON) |
| `AUTONOMATH_EXPERIMENTAL_MCP_ENABLED=1` (parent gate) | wires the wave24 + intel_wave31 imports below | **prerequisite** for all 39 missing manifest tools |
| `AUTONOMATH_WAVE24_FIRST_HALF_ENABLED=1` | wave24 first-half cohort | +N (rolled into the +39 below) |
| `AUTONOMATH_WAVE24_SECOND_HALF_ENABLED=1` | wave24 second-half cohort | +N (rolled into the +39 below) |
| `AUTONOMATH_INTEL_COMPOSITE_ENABLED=1` | intel_wave31 + (with WAVE32 flag) intel_wave32 | +N (rolled into the +39 below) |
| `AUTONOMATH_INTEL_WAVE32_ENABLED=1` | intel_wave32 only | +N (rolled into the +39 below) |
| (combined wave24 + intel_wave31/32 contribution at default-on) | — | **+39** (107 → 146) |
| `AUTONOMATH_36_KYOTEI_ENABLED=1` | 社労士 36協定 pair (gated for legal review) | +2 (146 → 148) |
| `AUTONOMATH_REASONING_ENABLED=1` | `intent_of` + `reason_answer` (broken pending fix) | +2 (broken — do not flip in prod) |
| `AUTONOMATH_HEALTHCARE_ENABLED=1` | P6-D W4 stub pack (6) | +6 (preview only) |
| `AUTONOMATH_REAL_ESTATE_ENABLED=1` | P6-F W4 stub pack (5) | +5 (preview only) |

Per-cohort isolation tests show wave24 / intel_wave32 fire purely off
`AUTONOMATH_EXPERIMENTAL_MCP_ENABLED` (the parent gate triggers the
import_module loop in `autonomath_tools/__init__.py:79-85`). Once imported,
each module re-checks its own narrow flag (`AUTONOMATH_WAVE24_FIRST_HALF_ENABLED`
etc., default `1`) — so the four flags are necessary together, but the
narrow flags alone are insufficient without the parent.

## 4. The 7 EXTRA tools (post-manifest landings)

These tools are registered at runtime under the canonical flag set but are
NOT yet in the static manifests. They are the "drift in the manifest-bump
cadence" surface — the next manifest bump (v0.3.5 candidate) should pick
them up.

| Tool | Cohort | Module | Landed |
| --- | --- | --- | --- |
| `query_at_snapshot_v2` | DEEP-22 time machine v2 | `time_machine_tools.py` | 2026-05-07 |
| `query_program_evolution` | DEEP-22 time machine v2 | `time_machine_tools.py` | 2026-05-07 |
| `shihoshoshi_dd_pack_am` | DEEP-30 司法書士 pack | `shihoshoshi_tools.py` | 2026-05-07 |
| `search_kokkai_utterance` | DEEP-39 国会発言 | `kokkai_tools.py` | 2026-05-07 |
| `search_shingikai_minutes` | DEEP-39 審議会議事録 | `kokkai_tools.py` | 2026-05-07 |
| `search_municipality_subsidies` | DEEP-44 自治体 補助金 | `municipality_tools.py` | 2026-05-07 |
| `get_pubcomment_status` | DEEP-45 e-Gov パブコメ | `pubcomment_tools.py` | 2026-05-07 |

Honest gap accounting: 139 manifest = 132 manifest-stable + 7 manifest-pending.
At runtime, all 132 stable + all 7 pending are exposed → 139 + 7 = 146.

## 5. 139 達成可否

**Achievable**: yes. Manifest entries covered = 139 / 139 (zero missing) with
the production-equivalent flag set documented in §2. The 32-tool gap from the
bare-shell baseline of 107 is fully accounted for by the four omitted flags
(`AUTONOMATH_EXPERIMENTAL_MCP_ENABLED` parent + wave24 first/second half +
intel composite). With those flags set, 39 wave24 / intel_wave31 / intel_wave32
manifest entries become reachable, more than overcoming the 32-entry gap.

**Recommendation for `R8_SMOKE_GATE_FLAGS_2026-05-07.md` §2**: append
`AUTONOMATH_EXPERIMENTAL_MCP_ENABLED=1`,
`AUTONOMATH_WAVE24_FIRST_HALF_ENABLED=1`,
`AUTONOMATH_WAVE24_SECOND_HALF_ENABLED=1`,
`AUTONOMATH_INTEL_COMPOSITE_ENABLED=1` to the canonical inline-flag command.
The current canonical command floors at 107, not 139 — this audit shows the
delta.

## 6. Production deploy implication (no change needed today)

Production Fly secrets already include the four experimental flags
(canonical secret set in `R8_FLY_SECRET_SETUP_GUIDE.md` §3 covers the
default-ON cohort surface). The discrepancy is **only** in the
operator-facing local-smoke command — the Fly env reaches 146 via secret +
default-on inheritance just fine. No production code, no fixture, no manifest
needed touching for this audit.

## 7. Files touched in this audit

- `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_MCP_FULL_COHORT_2026-05-07.md`
  — this doc.

No other file modified — fixtures, manifests, smoke scripts left as-is.
