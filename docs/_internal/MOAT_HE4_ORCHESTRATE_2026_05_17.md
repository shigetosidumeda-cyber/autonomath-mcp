# Moat Heavy-Output endpoint HE-4 — `multi_tool_orchestrate`

**Status:** LIVE 2026-05-17.
**Lane:** `HE-4` — server-side parallel bundler on top of the M/N
atomic surface.
**Module:** `src/jpintel_mcp/mcp/moat_lane_tools/he4_orchestrate.py`.
**Tests:** `tests/test_he4_orchestrate.py` (13 PASS).

## What lands

A single MCP tool, `multi_tool_orchestrate`, that takes a list of
`{"tool": str, "args": dict}` items and dispatches each against the
live `mcp._tool_manager` registry in parallel via `asyncio.gather`.
Synchronous tool fns are pushed off the event loop via
`asyncio.to_thread`; async tool fns are awaited directly.

The tool's contract envelope matches the rest of `moat_lane_tools/*`:
canonical §52 / §47条の2 / §72 / §1 / §3 disclaimer + provenance dict.

## Why this exists

User directive 2026-05-17: 「実は統合できるかもしれない」 — many of the
atomic MCP tools are independent of each other within a single agent
turn. A tax / accounting / 行政書士 agent commonly issues 4-7 parallel
queries in one turn (e.g. search_programs + get_houjin_360 +
find_filing_window + walk_reasoning_chain). Each query is a separate
agent ↔ server round trip + a separate `tool_use` block in the LLM
prompt.

HE-4 collapses those N round trips into 1. The agent still gets N
tool envelopes back inside one `results` list, but pays only:

* **1** network round trip (down from N).
* **1** `tool_use` block (down from N).
* **N** ¥3 billable units (transparent — bundle discount is in
  network / prompt overhead, NOT in price).

## Cost model & billing transparency

Every dispatched call (status `ok` or `error`) bills as a ¥3/req unit.
Rejected (unknown tool / private / recursion) and skipped
(all_or_nothing short-circuit) calls **do not** bill — they never
reached the underlying tool. The `billing` envelope makes this
explicit:

```json
{
  "billing": {
    "unit": 4,
    "yen": 12,
    "_bundle_discount": "1 round trip vs 4 = ~75% agent ↔ server network saving (¥ price unchanged: ¥3 per dispatched call)."
  }
}
```

The `_bundle_discount` string is computed deterministically from
input length and is meant to be surfaced to the operator in dashboards
/ usage logs.

## Security model

Three defensive layers:

1. **Allowlist**. Dispatched tool names must exist in
   `mcp._tool_manager.list_tools()`. Unknown names are rejected with
   `status="rejected"` + `error="unknown_tool — ..."`. This is what
   keeps an agent from invoking arbitrary Python via the dispatcher.
2. **Private-name refusal**. Any tool name starting with `_` is
   refused even if it appears in the registry. Defence in depth.
3. **Anti-recursion**. `multi_tool_orchestrate` cannot dispatch itself
   inside a bundle, so a malicious agent cannot fan-out exponentially.

In addition:

* `tool_calls` length is capped at 32.
* `max_concurrent` is bounded 1..32 (default 10).
* All inner exceptions are caught — the orchestrator never crashes
  the host MCP process. Errors surface as `status="error"` with the
  exception class + message.

## Fail strategy

| value             | behaviour                                                        |
|-------------------|------------------------------------------------------------------|
| `partial` (default) | continue on per-call errors; each call is marked with its own status |
| `all_or_nothing`  | stop on first error / rejected; remaining calls marked `skipped` |

In parallel mode, `all_or_nothing` awaits tasks in order and cancels
the trailing tasks once one fails. In serial mode it short-circuits
the for-loop. Either way the results list preserves input ordering.

## Test scenarios (13/13 PASS)

```
test_he4_three_parallel_calls           # happy path 3 parallel
test_he4_single_call_bundle             # idempotency w/ 1 entry
test_he4_serial_fallback_same_shape     # parallel=False parity
test_he4_partial_mode_tolerates_bad_args # partial fail isolation
test_he4_all_or_nothing_short_circuits  # all-or-nothing skip path
test_he4_unknown_tool_rejected          # allowlist guard
test_he4_private_tool_refused           # _-prefix guard
test_he4_self_recursion_refused         # anti-recursion guard
test_he4_max_concurrent_boundary        # semaphore = 1 edge
test_he4_empty_input_rejected           # top-level envelope
test_he4_oversized_input_rejected       # 33-entry cap
test_he4_billing_transparency           # ¥3 × dispatched accounting
test_he4_parallel_no_slower_than_serial # sanity benchmark
```

## Honest benchmark notes

The dominant cost for warm-cache jpcite tools is small (a few ms per
call). On 4-call bundles of `search_programs` (SQLite FTS, warm
cache), the server-side parallel total can be ~0.7x as fast as serial
because `asyncio.to_thread` per-call overhead beats the speedup.

The real win is asymmetric and structural:

* **Round trips**: always 1, regardless of N. This is the only
  saving an agent sees when its bottleneck is the wire, not CPU.
* **LLM prompt overhead**: 1 `tool_use` block in the agent's context
  vs N. For agents on tight context budgets, this is measurable.
* **CPU latency**: only wins when tools are individually slow (≥100ms).
  Once we add cross-encoder rerank / large FTS / network fetches to
  the routine bundle, HE-4 will be ~N× faster end-to-end on those.

We do **not** advertise the bundle as a per-call cost win. The
`_bundle_discount` field intentionally says "agent ↔ server network
saving (¥ price unchanged)".

## Expected agent behaviour

| call density       | recommended endpoint                  |
|--------------------|---------------------------------------|
| 1 tool per turn    | call the tool directly (no win)       |
| 2-7 parallel tools | wrap in `multi_tool_orchestrate`      |
| 8-32 parallel      | wrap in `multi_tool_orchestrate` with `max_concurrent=16-32` |
| > 32 per turn      | split across 2+ turns (cap enforced)  |

The expectation is that an instructed agent (税理士 / 会計士 /
行政書士 / 司法書士) will route 4-7 parallel calls per turn through
HE-4 most of the time — this matches the bundle pattern seen in the
existing 15 `data/recipes/recipe_*.yaml` files.

## Files

* `src/jpintel_mcp/mcp/moat_lane_tools/he4_orchestrate.py`
* `src/jpintel_mcp/mcp/moat_lane_tools/__init__.py` (registry entry)
* `tests/test_he4_orchestrate.py`
* `docs/recipes/he4_orchestrate_zeirishi_demo.md`
* `docs/_internal/MOAT_HE4_ORCHESTRATE_2026_05_17.md` (this doc)

## Cross-references

* Memory `feedback_composable_tools_pattern` — Dim P composable tools.
* Memory `feedback_agent_funnel_6_stages` — agent-led growth.
* Memory `feedback_predictive_service_design` — Dim K push surface
  (an HE-4 bundle can pre-fetch what predictive watch flagged).
* `docs/_internal/MOAT_INTEGRATION_MAP_2026_05_17.md` — 21-lane integration map.
