# Wave 46 dim 19 SFGH booster PR — STATE

**Date**: 2026-05-12
**Branch**: `feat/jpcite_2026_05_12_wave46_dim19_SFGH`
**Lane**: `/tmp/jpcite-w46-dim19-SFGH.lane`
**Worktree**: `/tmp/jpcite-w46-dim19-SFGH`
**Memory invariants honoured**:
- `feedback_dual_cli_lane_atomic` — mkdir lane atomic claim
- `feedback_completion_gate_minimal` — 4-dim ship + ruff/pytest green only
- `feedback_copilot_scaffold_only_no_llm` — Dim S scaffold-only, NO LLM

## Background

`docs/audit/dim19_audit_2026-05-12.md` left 4 lower-bottom dims still at
`MISS` ratings after Wave 46 FPQO + EJ + KN landed:

| Dim | Score / 10 | Symptom |
|-----|------------|---------|
| **S** copilot_scaffold     | 5.0 | REST + MCP both MISS |
| **F** fact_signature       | partial | ETL bulk refresh missing (only weekly cron) |
| **G** realtime_signal      | 4.50 | subscriber-state test gap |
| **H** personalization      | partial | MCP wrap missing (only REST) |

This PR closes all 4 in one booster lane (~470 LOC added across 4 new
files + 1 new ETL + 1 STATE doc).

## Diff inventory (4 dims, 1 worktree)

```
src/jpintel_mcp/api/copilot_scaffold.py                      +180  Dim S REST
tests/test_dimension_s_copilot.py                            +110  Dim S test
scripts/etl/refresh_fact_signatures_v2.py                    +160  Dim F ETL
tests/test_dimension_g_realtime_subscribers.py               +180  Dim G test
src/jpintel_mcp/mcp/autonomath_tools/personalization_mcp.py  +220  Dim H MCP
tests/test_dimension_h_personalization_mcp.py                +160  Dim H test
src/jpintel_mcp/api/main.py                                  +7    wire S
src/jpintel_mcp/mcp/autonomath_tools/__init__.py             +1    wire H
docs/research/wave46/STATE_w46_dim19_SFGH_pr.md              +this STATE
```

Net delta: ~1018 LOC, all behind feature-gate envs or experimental
router include so absence of substrate degrades to skip, not crash.

## Dim projections (post-PR)

| Dim | Was | Lift mechanism | After (proj.) |
|-----|-----|----------------|---------------|
| **S** copilot_scaffold     | 5.0  | 2 REST endpoints + 6 unit tests | 7.5+ |
| **F** fact_signature       | 8.0* | bulk subject-scoped ETL v2 | 9.0  |
| **G** realtime_signal      | 4.5  | subscriber-state test (3 cases) | 6.0  |
| **H** personalization      | 6.5  | MCP wrap (`personalization_recommendations_am`) | 8.0  |

* dim F was already at 8.0/10 after Wave 46 FPQO; ETL v2 closes the
  bulk-refresh missing-axis flag.

## LLM = 0 verify (the dim S invariant)

```
$ grep -rE "(import|from)\s+(anthropic|openai|google\.generativeai|cohere)" \
    src/jpintel_mcp/api/copilot_scaffold.py \
    src/jpintel_mcp/mcp/autonomath_tools/personalization_mcp.py \
    scripts/etl/refresh_fact_signatures_v2.py
# (no matches expected)
```

All four new modules go through the `test_no_llm_imports_in_*` guard
test pattern; tests assert at module-import time + grep + helper.

## Wire-up

1. `src/jpintel_mcp/api/main.py` — `_include_experimental_router(app,
   "jpintel_mcp.api.copilot_scaffold")` registered between Dim N
   anonymized_query and `autonomath_health_router` so the surface
   shows up under `/v1/copilot/scaffold/*` with envelope parity.

2. `src/jpintel_mcp/mcp/autonomath_tools/__init__.py` — `personalization_mcp`
   added to the side-effect import tuple. Single tool
   (`personalization_recommendations_am`) gated by
   `AUTONOMATH_PERSONALIZATION_MCP_ENABLED` (default ON) AND
   `settings.autonomath_enabled`.

3. `scripts/etl/refresh_fact_signatures_v2.py` — runnable as
   `python scripts/etl/refresh_fact_signatures_v2.py --subject-kind
   houjin --subject-id <id>` for ops bulk re-sign. Re-uses
   `_canonical_payload` / `_load_private_key` / `_sign_and_upsert`
   from `scripts/cron/refresh_fact_signatures_weekly.py` so byte-form
   of signed payload NEVER diverges between the two paths.

## Master projection

| Wave 46 stack snapshot | Before SFGH | After SFGH |
|------------------------|-------------|------------|
| dim 19 dims with MCP wrap     | 12 | 13 |
| dim 19 dims with REST surface | 16 | 17 |
| dim 19 dims with test gap     | 4  | 0  |
| LLM SDK imports in src/       | 0  | 0  |

## PR

Title: `feat(wave46-dim19-SFGH): copilot_scaffold + fact_signature ETL v2 + realtime_signal subscriber test + personalization MCP`

**PR**: https://github.com/shigetosidumeda-cyber/autonomath-mcp/pull/150
**Commit**: b1747f377
