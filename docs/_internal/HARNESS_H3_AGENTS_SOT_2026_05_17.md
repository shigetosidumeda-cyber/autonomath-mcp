# Harness H3 — Agent Entry SOT (2026-05-17)

Landing notes for the P0.4 remediation from
`docs/_internal/AGENT_HARNESS_REMEDIATION_PLAN_2026_05_17.md`.

## What changed

| File | Before | After |
|---|---|---|
| `AGENTS.md` (root) | absent | **created** — 177 lines, vendor-neutral SOT |
| `CLAUDE.md` | 923 lines (Wave 17..51 / tick 1..150 mixed with rules) | **92 lines** — Claude-specific shim, defers to AGENTS.md |
| `.agent.md` | 141 lines (duplicated counts + rules) | **22 lines** — vendor-neutral shim |
| `.cursorrules` | 79 lines (duplicated counts + rules) | **22 lines** — Cursor shim |
| `.windsurfrules` | 106 lines (duplicated counts + rules) | **22 lines** — Windsurf shim |
| `.mcp.json` | 18 lines (151-tool description) | **18 lines** — count removed, points at AGENTS.md |
| `docs/_internal/historical/CLAUDE_WAVE_HISTORY_2026_05_06_2026_05_16.md` | absent | **created** — 776 lines, archived Wave/tick log |
| `tests/test_agent_entry_sot.py` | absent | **created** — 11 tests, all passing |

## Why

The pre-H3 state had **six** competing agent entry surfaces, each carrying
hardcoded volatile counts:

- `.agent.md` claimed **139 tools** + **219 paths**.
- `.cursorrules` claimed **139 tools** + **219 paths**.
- `.windsurfrules` claimed **139 tools** + **219 paths**.
- `.mcp.json` claimed **151 tools**.
- `CLAUDE.md` claimed **139** then **146** then **155** then **165** then
  **169** then **179** then **184** then **221** then **262** depending on
  which Wave / tick paragraph an agent landed on.
- `scripts/distribution_manifest.yml` pinned **184** as the canonical
  published count, with header comment still saying **179**.

This split-brain state was the root cause flagged by the H3 audit. Any new
coding agent reading these files in the natural order (CLAUDE.md → .agent.md
→ .cursorrules) reached three different "current" counts before finding
the canonical one.

## Contract after H3

1. **AGENTS.md is the source of truth.** Every shim file points at it.
2. **No hardcoded volatile counts** in any agent entry file. CI guard
   `tests/test_agent_entry_sot.py` enforces this with a stale-counts list
   covering 139 / 146 / 151 / 155 / 165 / 169 / 179 / 184 / 186 / 219 / 220
   / 221 / 262 / 306 / 307.
3. **Live counts live in three places**:
   - `scripts/distribution_manifest.yml` — canonical published values.
   - `len(await mcp.list_tools())` — runtime MCP tool count.
   - `scripts/probe_runtime_distribution.py` — one-pass runtime + manifest.
4. **Wave / tick history is archived** at
   `docs/_internal/historical/CLAUDE_WAVE_HISTORY_2026_05_06_2026_05_16.md`
   and explicitly marked as historical-state-only. New work does **not**
   amend it — start a new Wave file under `docs/_internal/` instead.
5. **CLAUDE.md is a shim** carrying only Claude-specific operating notes
   (loop discipline, sub-agent parallelism, safe_commit, encoding rules).
   It does not duplicate hard constraints — those live in AGENTS.md.

## Verification

```bash
# 1. AGENTS.md exists and has all 8 required SOT sections.
test -f AGENTS.md
grep -c "Project identity\|Hard constraints\|Architecture pointer\|Live counts\|Key commands\|Quality gates\|What NOT to do\|Memory pointer" AGENTS.md   # → 8

# 2. CLAUDE.md shrunk under budget.
wc -l CLAUDE.md   # → ≤ 200 (currently 92)

# 3. No hardcoded volatile counts in any agent entry file.
grep -nE "\b(139|146|151|155|165|169|179|184|186|219|220|221|262|306|307)\b" \
  AGENTS.md CLAUDE.md .agent.md .cursorrules .windsurfrules .mcp.json   # → empty

# 4. Every shim points at AGENTS.md.
for f in CLAUDE.md .agent.md .cursorrules .windsurfrules .mcp.json; do
  grep -q "AGENTS\.md" "$f" || echo "MISSING POINTER: $f"
done   # → empty

# 5. Test suite passes.
.venv/bin/pytest tests/test_agent_entry_sot.py -v   # → 11/11 PASS
```

## What did NOT change

- `tests/test_no_llm_in_production.py` — unchanged. The no-LLM rule
  ("constraint 3" in AGENTS.md §2) is still enforced by the existing guard.
- `tests/test_distribution_manifest.py` — unchanged. Manifest drift is still
  the SOT for tool / route / OpenAPI path counts.
- `scripts/distribution_manifest.yml` — unchanged. Remains the canonical
  published counts source.
- `src/jpintel_mcp/` — unchanged. No code paths affected.
- `.github/workflows/` — unchanged. No CI rewiring.
- `.gitignore` — unchanged (`.claude/` was already on line 156).

## Out of scope

H3 deliberately does **not** touch:

- P0.1 (MCP tool count contract reconciliation across manifests).
- P0.5 (CI / release gate split-brain — `make mcp` vs CI distribution check).
- P0.6 (Live AWS canary authority — separate H5 doc landed same day).
- P1 / P2 remediation (resources/prompts, marketplace, eval, workflows).

Those have their own landing docs and their own H-tickets.
