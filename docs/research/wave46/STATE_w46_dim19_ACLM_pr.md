# Wave 46 dim 19 ACLM booster PR — STATE

Date: 2026-05-12
Branch: `feat/jpcite_2026_05_12_wave46_dim19_ACLM_booster`
Worktree: `/tmp/jpcite-w46-dim19-ACLM`
Tick: Wave 46 永遠ループ tick6 #7
Author: parallel subagent (loop)
Lane claim: `/tmp/jpcite-w46-dim19-ACLM.lane`

## Scope — 4 dims, 1 booster PR

Closes 3 distinct dim 19 sub-criterion gaps and explicitly documents the
4th as redundant (already landed). Memory anchors:
`feedback_dual_cli_lane_atomic` /
`feedback_completion_gate_minimal` /
`feedback_session_context_design` /
`feedback_rule_tree_branching`.

| dim | code | action | files | LOC |
| --- | ---- | ------ | ----- | --- |
| A   | semantic_search legacy v1 MCP wrap | NEW MCP tool wrapping `POST /v1/semantic_search` (1024-dim e5-large canonical vec corpus) | `src/jpintel_mcp/mcp/autonomath_tools/semantic_search_legacy.py` + `__init__.py` registration | ~145 |
| C   | amendment_diff ETL test extension  | NEW test module covering canonical_value sort, Japanese unicode equivalence, projection_regression_candidate logic, dry-run no-op, hash-parity gating | `tests/test_dim_c_amendment_diff_etl_v3.py` | ~228 |
| L   | session_context (state token 24h TTL) | NEW REST router with `POST /v1/session/{open,step,close}` + in-process OrderedDict LRU + 24h TTL + 32-step cap + 16 KiB saved_context cap; wired into `main.py` via `_include_experimental_router` | `src/jpintel_mcp/api/session_context.py` + `main.py` wire | ~270 |
| L   | session_context tests | NEW pytest module covering open/step/close happy path, 410 on unknown/expired, 413 on step cap and oversize saved_context, 422 on token shape, store_stats introspection | `tests/test_dimension_l_session_context.py` | ~175 |
| M   | rule_tree_branching | SKIPPED — `src/jpintel_mcp/api/rule_tree_eval.py` (412 LOC) + `tests/test_dimension_k_rule_tree.py` (387 LOC) already landed in PR #139 (Wave 46 dim 19 KN booster). dim M = "multi-step rule tree" is conceptually the same surface (AND/OR/XOR tree eval) — extending here would duplicate `_evaluate_node`. Logged here for traceability per `feedback_completion_gate_minimal`. | (none) | 0 |

## Architecture notes

### Dim A (legacy v1 MCP wrap)
* Wraps the **older** 1024-dim canonical vec corpus surface
  (`api/semantic_search.py`, migration 166). The modern hybrid v2
  surface (384-dim e5-small + cross-encoder reranker) already has an
  MCP wrap at `mcp/autonomath_tools/semantic_search_v2.py`. The legacy
  surface had no MCP wrap → agents with e5-large embeddings had to
  HTTP-hop. Closed here.
* Single ¥3/req billing event (parity with REST handler
  `_billing_unit = 1`).
* `_ENABLED` flag via `JPCITE_SEMANTIC_SEARCH_LEGACY_ENABLED` (default
  ON). `__init__.py` registers via decorator side-effect.
* NO LLM API — client supplies the 1024-dim L2-normalised embedding.

### Dim C (ETL test extension)
* 9 new test cases targeting `scripts/etl/backfill_amendment_diff_from_snapshots.py`.
* Covers:
  - `canonical_value` sort stability on `target_set_json`,
  - empty equivalence collapse (None / "" / "[]"),
  - `should_record_field_change` plain and unicode-Japanese path,
  - `projection_regression_candidate` fires iff raw byte drift + hash
    parity (eligibility/summary/raw_snapshot all match),
  - dry-run (`apply=False`) NEVER touches `am_amendment_diff`,
  - apply→dry-run idempotency metrics (`candidate_diffs_new == 0`).
* In-memory sqlite, no autonomath.db dependency, no network, no LLM.

### Dim L (session_context, NEW)
* 3 endpoints under `/v1/session`:
  * `POST /open` — returns `state_token` (32 hex chars) + 24h
    `expires_at` + initial `saved_context`.
  * `POST /step` — appends a turn under existing token; LRU-bumps to
    end; returns cumulative count + last_step_at.
  * `POST /close` — removes the token + returns final snapshot +
    `step_log`. Second close → 410.
* In-process OrderedDict + `threading.Lock` (no Redis, no sqlite — per
  `feedback_zero_touch_solo` + `feedback_no_quick_check_on_huge_sqlite`).
* Caps: `_MAX_SESSIONS=10_000` (LRU evict), `SESSION_TTL_SEC=86_400`
  (24h), 16 KiB saved_context, 4 KiB step, 32 steps.
* Honest gap: in-process means **session does NOT survive Fly machine
  restart or autoscale to a different machine**. Disclaimer surfaces
  this. 99% of agent multi-turn loops fit in a single machine + 24h.
* §52 / §47条の2 / §72 / §1 disclaimer on every response (verified by
  test).

### Dim M
* Skipped with explicit rationale (see table above). Avoids violating
  `feedback_completion_gate_minimal` ("最低 blocker に絞れ" — don't
  invent surface just to fill a slot).

## Verify

Inside the worktree (`/tmp/jpcite-w46-dim19-ACLM`):

```bash
# ruff (4 new files)
.venv/bin/ruff check \
  src/jpintel_mcp/api/session_context.py \
  src/jpintel_mcp/mcp/autonomath_tools/semantic_search_legacy.py \
  tests/test_dimension_l_session_context.py \
  tests/test_dim_c_amendment_diff_etl_v3.py
# All checks passed!

# pytest (3 pre-existing + 20 new)
.venv/bin/python -m pytest \
  tests/test_a3_amendment_diff_etl.py \
  tests/test_dimension_l_session_context.py \
  tests/test_dim_c_amendment_diff_etl_v3.py \
  -q
# 23 passed, 2 warnings in 1.16s
```

## Constraints honored

* `feedback_dual_cli_lane_atomic` — lane via `mkdir
  /tmp/jpcite-w46-dim19-ACLM.lane`, worktree on `origin/main`.
* `feedback_destruction_free_organization` — no rm/mv, only adds + 1
  wire in `main.py` + 1 import in `autonomath_tools/__init__.py`.
* `feedback_autonomath_no_api_use` / `feedback_no_operator_llm_api` —
  zero LLM SDK imports; banned-import regex in dim L test fails the
  CI if regressed.
* `feedback_overwrite_stale_state` — historical STATE docs left as-is;
  this doc is SOT for the ACLM booster.

## Outcome target

dim 19 audit re-score should lift:
* Dim A `mcp_wrap_count` (legacy v1 wrap now exists) → +1 sub-criterion.
* Dim C `tests_present` (new dedicated v3 test) → +1 sub-criterion.
* Dim L `rest_surface_present` + `tests_present` (new fully) → +2
  sub-criteria.
* Dim M unchanged (already covered by PR #139 rule_tree_eval).
