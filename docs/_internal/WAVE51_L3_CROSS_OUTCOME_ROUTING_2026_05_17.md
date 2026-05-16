# Wave 51 L3 — cross_outcome_routing module landed (2026-05-17)

Status: **LANDED — module green**
Lane: `[lane:solo]`
Wave: 51 L3 (post Wave 51 tick 0 dim K-S consolidation)
Parent design: `docs/_internal/WAVE51_L3_L4_L5_DESIGN.md` (cross_outcome_routing row)

## Scope

Land the first L3 / AX Layer 6 lane from `WAVE51_L3_L4_L5_DESIGN.md`:
**`cross_outcome_routing`** — a deterministic pairwise scorer + per-segment
greedy chain walker over the 14 production outcome deliverables in
`agent_runtime.outcome_catalog`.

This is the "router-agnostic substrate" landing only. The companion AX
Layer 6 cron (`scripts/cron/ax_layer_6_cross_outcome_routing.py`) and
its `.github/workflows/ax-layer-6-cross-outcome-routing.yml` are
separate landings — this module is the input both will consume.

## Files landed

| Path | Role |
|------|------|
| `src/jpintel_mcp/cross_outcome_routing/__init__.py` | Public surface — re-exports 12 names |
| `src/jpintel_mcp/cross_outcome_routing/models.py` | Pydantic envelopes: `OutcomePairScore` / `OutcomeRoutingChain` / `RoutingMatrix` |
| `src/jpintel_mcp/cross_outcome_routing/routing.py` | Scorer (`jaccard` / `score_pair` / `build_pairs`) + chain walker (`build_chains`) + facade (`build_routing_matrix`) |
| `tests/test_cross_outcome_routing.py` | 24 tests (>=10 mandated) covering algebra + Pydantic guards + real-catalog smoke |

## Scoring formula (canonical reference)

For every pair `(a, b)` of catalog entries:

```
use_case_overlap = jaccard(a.use_case_tags,         b.use_case_tags)
source_overlap   = jaccard(a.source_family_ids,     b.source_family_ids)
segment_overlap  = jaccard(a.user_segments,         b.user_segments)
score = 0.45 * use_case_overlap
      + 0.30 * source_overlap
      + 0.25 * segment_overlap
```

Weights `WEIGHT_USE_CASE=0.45 / WEIGHT_SOURCE=0.30 / WEIGHT_SEGMENT=0.25`
sum to 1.0 (pinned by a test), keeping `score` in `[0.0, 1.0]` without
post-hoc rescaling. The weight choice is deliberate: use-case overlap is
the strongest "next-step affinity" signal, source-family reuse is the
ETL economy multiplier, and segment overlap is the lightest signal
(it only narrows audience, not topical relevance).

## Per-segment greedy chain walker

For each `UserSegment` × each catalog entry that includes that segment,
walk a chain by repeatedly picking the highest-scoring unused
neighbour that (a) shares the segment and (b) has pair score
`>= threshold`. Ties break on ASCII slug order so the walk is fully
reproducible. The walk stops on no qualifying neighbour or at
`max_steps`. Chains with zero handoff steps are dropped.

Defaults: `DEFAULT_THRESHOLD=0.10`, `DEFAULT_MAX_CHAIN_STEPS=5`.

## Smoke against the live catalog

```text
catalog size: 14
pair_count:   91   (= 14 * 13 / 2)
nonzero pairs: 91  (every pair carries at least 1 shared segment)
top 3 pairs:
  subsidy-grant-candidate-pack   ↔ cashbook-csv-subsidy-fit-screen   score=0.608
  invoice-registrant-public-check ↔ accounting-csv-public-counterparty-check score=0.530
  local-government-permit-obligation-map ↔ healthcare-regulatory-public-check score=0.512
chains produced: 42  (across all UserSegment × anchor combinations)
example chain (accounting_firm):
  invoice-registrant-public-check
  → accounting-csv-public-counterparty-check
  → client-monthly-public-watchlist
  → cashbook-csv-subsidy-fit-screen
  → subsidy-grant-candidate-pack
```

The example chain is exactly the kind of "1 customer → 5 deliverable
handoff" surface that the cron will materialise daily and that the L5
revenue funnel will use to compound `¥3/req` calls per session.

## Verification

| Check | Command | Result |
|-------|---------|--------|
| Module tests | `pytest tests/test_cross_outcome_routing.py -q` | **24 passed in 0.79s** |
| mypy --strict | `mypy --strict src/jpintel_mcp/cross_outcome_routing/` | **Success: no issues found in 3 source files** |
| ruff | `ruff check src/jpintel_mcp/cross_outcome_routing/ tests/test_cross_outcome_routing.py` | **All checks passed!** |
| No-LLM invariant | `pytest tests/test_no_llm_in_production.py -q` | **10 passed in 26.26s** |

## Invariants enforced

1. **No LLM API import** — `anthropic` / `openai` / `google.generativeai`
   / `claude_agent_sdk` absent from the module tree. CI guard
   `tests/test_no_llm_in_production.py` continues to PASS (10/10).
2. **Pure deterministic** — no clock (`datetime.now`), no random
   (`random.choice`), no I/O (HTTP / DB / file). Identical catalog
   inputs always produce identical `RoutingMatrix` outputs.
3. **Pydantic strict-by-default** — `extra='forbid'` + `frozen=True`
   on every envelope. `pair_count == len(pairs)` and `slug_a !=
   slug_b` enforced by `model_validator`.
4. **Weight invariance** — `WEIGHT_USE_CASE + WEIGHT_SOURCE +
   WEIGHT_SEGMENT == 1.0` is asserted by a test so a future tuning
   change is intentional rather than silent.
5. **¥3/req economics preserved** — pure CPU-bound Python set math, no
   external paid API call, no LLM inference, no per-call cost beyond
   in-process Jaccard. Fits the Wave 51 dim K-S "deterministic
   composition" pattern from `feedback_composable_tools_pattern.md`.

## Cross-reference

- Parent L3 design: `docs/_internal/WAVE51_L3_L4_L5_DESIGN.md`
- Wave 51 plan (§4.3 = L3 AX Layer 6 cron): `docs/_internal/WAVE51_plan.md`
- Wave 51 tick 0 closeout (foundational 11-module substrate this builds on):
  `docs/_internal/WAVE51_DIM_K_S_CLOSEOUT_2026_05_16.md`
- Wave 51 implementation roadmap (Day 8-14 = L3 range):
  `docs/_internal/WAVE51_IMPLEMENTATION_ROADMAP.md`
- Source catalog under composition: `src/jpintel_mcp/agent_runtime/outcome_catalog.py`
- Outcome routing helper (Wave 50 / pre-L3): `src/jpintel_mcp/agent_runtime/outcome_routing.py`
  (still authoritative for catalog-driven *routing decisions* per request;
  this L3 module is for *offline cross-outcome chain materialisation*)

## Next (not in this landing)

- `scripts/cron/ax_layer_6_cross_outcome_routing.py` — daily 03:00 JST
  cron that calls `build_routing_matrix()` and writes the artifact
  to S3 + CW custom metric for funnel observability.
- `.github/workflows/ax-layer-6-cross-outcome-routing.yml` — GHA
  scheduler binding (DISABLED default per Stream W concern separation
  convention).
- MCP wrapper tool `recommend_outcome_chain(slug, segment)` that
  looks up the persisted artifact and surfaces the chain in the
  canonical `Evidence` envelope.
- The remaining 4 L3 cron lanes from `WAVE51_L3_L4_L5_DESIGN.md`:
  `predictive_merge_daily` / `notification_fanout` / `as_of_snapshot_5y`
  / `federated_partner_sync`.

## Lane marker

`[lane:solo]` — single-session land, no dual-CLI lane claim
(`feedback_dual_cli_lane_atomic.md` does not apply since this is a
single-author module + single-author test + single-author doc landing).

last_updated: 2026-05-17
