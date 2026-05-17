# HE-4 `multi_tool_orchestrate` — 税理士 agent demo

**Audience:** 税理士 / 会計士 / 行政書士 / 司法書士 agent operators.
**Goal:** Replace N round trips (search + houjin lookup + filing window +
reasoning chain) with **one bundled call**.
**Billing:** transparent — each dispatched call still bills as 1 ¥3/req
unit (税込 ¥3.30). The bundle discount is in **network round trips and
agent prompt overhead**, not in ¥.

> Sensitive surface — every response carries the canonical
> §52 / §47条の2 / §72 / §1 / §3 disclaimer envelope. NO LLM is invoked
> server-side; HE-4 is a deterministic dispatcher only.

## Why one tool for many calls?

A 税理士 agent answering "I have client `1234567890123`. Tell me the
relevant ものづくり-style subsidies, the company's 360° posture, the next
filing window, and walk me through the legal-reasoning chain." normally
issues four sequential MCP calls:

```text
agent → MCP: search_programs(q="ものづくり")
agent ← MCP: { results: [...] }
agent → MCP: get_houjin_360(houjin_bangou="1234567890123")
agent ← MCP: { ... }
agent → MCP: find_filing_window(houjin_bangou="1234567890123")
agent ← MCP: { ... }
agent → MCP: walk_reasoning_chain(query="...")
agent ← MCP: { ... }
```

Each round trip pays the agent ↔ server network cost **and** another
`tool_use` block in the LLM prompt context. For an agent that has
already decided on four independent queries, this is wasted work.

HE-4 collapses all four into:

```text
agent → MCP: multi_tool_orchestrate([
              {tool: search_programs, args: {...}},
              {tool: get_houjin_360, args: {...}},
              {tool: find_filing_window, args: {...}},
              {tool: walk_reasoning_chain, args: {...}},
           ])
agent ← MCP: { results: [{...}×4], summary, billing, _disclaimer }
```

The internal dispatcher uses `asyncio.gather`, so the four calls run
concurrently on the server side. The agent sees one round trip.

## End-to-end example

### Request

```python
from jpintel_mcp.mcp.moat_lane_tools.he4_orchestrate import multi_tool_orchestrate

bundle = multi_tool_orchestrate(
    tool_calls=[
        {"tool": "search_programs",       "args": {"q": "ものづくり", "limit": 3}},
        {"tool": "get_houjin_360",        "args": {"houjin_bangou": "1234567890123"}},
        {"tool": "find_filing_window",    "args": {"houjin_bangou": "1234567890123"}},
        {"tool": "walk_reasoning_chain",  "args": {"query": "中小企業 設備投資"}},
    ],
    parallel=True,
    fail_strategy="partial",
    max_concurrent=10,
)
```

### Response shape (abridged)

```json
{
  "tool_name": "multi_tool_orchestrate",
  "schema_version": "moat.he4.v1",
  "primary_result": {
    "status": "ok",
    "lane_id": "HE-4",
    "upstream_module": "jpintel_mcp.moat.he4_orchestrate",
    "primary_input": {
      "tool_calls_count": 4,
      "parallel": true,
      "fail_strategy": "partial",
      "max_concurrent": 10
    }
  },
  "results": [
    {"tool_call_idx": 0, "tool": "search_programs",      "status": "ok", "result": { ... }, "latency_ms": 42},
    {"tool_call_idx": 1, "tool": "get_houjin_360",       "status": "ok", "result": { ... }, "latency_ms": 38},
    {"tool_call_idx": 2, "tool": "find_filing_window",   "status": "ok", "result": { ... }, "latency_ms": 19},
    {"tool_call_idx": 3, "tool": "walk_reasoning_chain", "status": "ok", "result": { ... }, "latency_ms": 71}
  ],
  "summary": {
    "total_calls": 4,
    "ok": 4,
    "error": 0,
    "rejected": 0,
    "skipped": 0,
    "total_latency_ms": 73
  },
  "billing": {
    "unit": 4,
    "yen": 12,
    "_bundle_discount": "1 round trip vs 4 = ~75% agent ↔ server network saving (¥ price unchanged: ¥3 per dispatched call)."
  },
  "_disclaimer": "本 response は moat lane の retrieval / モデル推論結果で…",
  "_provenance": {
    "source_module": "jpintel_mcp.moat.he4_orchestrate",
    "lane_id": "HE-4",
    "wrap_kind": "moat_lane_he4_orchestrate",
    "observed_at": "2026-05-17",
    "registered_tool_count": 218
  }
}
```

Note: `total_latency_ms` is the wall-clock of the *server-side* gather,
not the sum of per-call latencies. With parallel=True, the bundle
finishes in roughly `max(per_call_latencies)`.

## Failure modes & how to handle them

| status     | meaning                                                  | billed? |
|------------|----------------------------------------------------------|---------|
| `ok`       | tool returned successfully                               | yes (¥3)|
| `error`    | tool raised — bad args, runtime exception                | yes (¥3)|
| `rejected` | tool name unknown / private (`_x`) / recursion refused   | no      |
| `skipped`  | all_or_nothing short-circuit cancelled this call          | no      |

In `fail_strategy="partial"` (default), one bad call does not poison
the bundle. Inspect `results[i].status` per call.

In `fail_strategy="all_or_nothing"`, the orchestrator stops at the
first `error` or `rejected` and marks the remaining calls as `skipped`.
Useful when a downstream client refuses to display a partial bundle.

## Security model

* **Allowlist**: dispatched tool names must already be registered on
  the MCP server (i.e. present in `mcp._tool_manager.list_tools()`).
  Unknown names are rejected with `error="unknown_tool — not registered
  on this MCP server."`.
* **Private tool refusal**: any tool name starting with `_` is refused
  defensively, even if it somehow appears in the registry.
* **Anti-recursion**: calling `multi_tool_orchestrate` from inside the
  bundle is rejected to prevent stack-amplification.
* **Bounded fan-out**: `max_concurrent` caps the asyncio semaphore at
  10 by default; the hard cap is 32.
* **Bounded input**: `tool_calls` length is capped at 32.

## Honest performance notes

The dominant cost for most jpcite tools is SQLite I/O on warm cache (a
few ms per call). On 4 warm-cache `search_programs` calls, the
server-side `parallel=True` total can be **slower** than `parallel=False`
by 5-10ms because `asyncio.to_thread` adds per-call overhead. The win
is asymmetric:

* **Network**: 1 round trip vs N — a real saving regardless.
* **LLM prompt overhead**: 1 `tool_use` block vs N — measurable when
  the agent's context budget is tight.
* **CPU latency**: only matters when individual tools take 100ms+
  (e.g. cross-encoder rerank, large FTS scans, network-bound fetches).
  HE-4 makes those bundles ~N× faster end-to-end.

Use HE-4 when you already know you need ≥2 independent queries.
Don't use it as a "wrap every single call" idiom — for a 1-call bundle
you save no round trips and pay the same ¥3.
