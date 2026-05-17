---
title: "HE-1 agent_full_context demo"
date_modified: "2026-05-17"
license: "PDL v1.0 / CC-BY-4.0"
---

# HE-1 `agent_full_context` demo

Heavy-output endpoint that returns everything an agent needs in **1 call**
(5-10 round trips collapsed into 1). NO LLM inference, NO HTTP fan-out —
the endpoint composes existing moat lanes (N1..N9 + `search_programs`) in-process via `asyncio.gather`.

## Why depth-first

> 薄い回答を返しても誰も使わない。
> agent が LLM コスト安く済むように深い回答。

User directive (2026-05-17). The economics of the agent era are clear:

- A thin response forces the calling agent to round-trip again.
- Each round trip costs both **¥3/req** to jpcite AND **N tokens** of LLM compose context to the agent's backing LLM.
- A 1-call deep response collapses N round trips into 1 — the agent pays ¥3 once, and saves N-1 worth of LLM context (∼80% LLM cost reduction in our model below).

## Signature

```python
await mcp.call(
    "agent_full_context",
    query="ものづくり補助金",          # 自由入力 (上限 512 char)
    segment="税理士",                  # 任意 (税理士 / 会計士 / 行政書士 /
                                       # 司法書士 / 社労士 / 中小経営者 / AX_engineer)
    houjin_bangou="8010001213708",     # 任意 (13-digit corporate number)
    depth_level=3,                     # 1=LITE / 3=NORMAL / 5=FULL
)
```

## depth_level

| depth_level | size (target) | top-N each section | reasoning chain | portfolio matrix |
| --- | --- | --- | --- | --- |
| 1 (LITE)   | ~5 KB   | 1  | skipped | top-3 |
| 3 (NORMAL) | ~30 KB  | 5  | top-3 (no opposing views) | top-20 |
| 5 (FULL)   | ~100 KB | 10 | top-10 with opposing views | top-50 |

## Response shape (depth_level=3)

```jsonc
{
  "query": "ものづくり補助金",
  "resolved_aliases": [...],                  // N5 - top-10 surface→canonical id
  "core_results": {
    "programs": [...],                        // search_programs - top-5 with sections / amount band / 期限 / 法的根拠
    "law_articles": [],                       // reserved slot (call law_related_programs_cross to fill)
    "judgments": [],                          // reserved slot (call walk_reasoning_chain to fill)
    "tsutatsu": [],                           // reserved slot
    "case_studies": []                        // reserved slot (call cases_by_industry_size_pref to fill)
  },
  "reasoning_chain": {                        // N3 - free-text walk
    "results": [...],                         // top-3 chains
    "total": 3,
    "category": "all",
    "min_confidence": 0.6
  },
  "filing_windows": [...],                    // N4 - top-5 (requires houjin_bangou)
  "applicable_artifact_templates": [...],     // N1 - top-5 templates for the 士業 segment
  "houjin_portfolio_gap": {                   // N2 - portfolio + gap programs (requires houjin_bangou)
    "portfolio": [...],
    "gap_programs": [...],
    "houjin_bangou": "8010001213708",
    "portfolio_total": 0,
    "gap_total": 0
  },
  "amendment_alerts": [...],                  // N6 - top-5 amendments for the houjin (or global feed)
  "segment_view": {                           // N7 - rollup stats
    "rollup": [...],
    "total_segments": 235,
    "hint": "Use get_segment_view(jsic_major=...) for a concrete slice."
  },
  "related_recipes": [...],                   // N8 - top-3 deterministic recipes for the segment
  "placeholder_mappings_preview": [...],      // N9 - 10 canonical placeholders pre-resolved
  "next_call_hints": [                        // agent への 3-5 件の次アクション提案
    {"action": "Deep-dive top program", "tool": "program_full_context", "args_hint": "..."},
    {"action": "Personalize with a houjin_bangou", "tool": "agent_full_context", "args_hint": "..."},
    {"action": "Pull the full reasoning chain", "tool": "get_reasoning_chain", "args_hint": "..."}
  ],
  "billing": {"unit": 1, "yen": 3, "depth_level": 3},
  "_disclaimer": "本 response は moat lane の retrieval ... §52 / §47条の2 / §72 / §1 / §3 ...",
  "_billing_unit": 1,
  "_citation_envelope": {
    "primary_sources": ["https://...", "https://..."],
    "total_primary_sources": 2,
    "license": "moat lane retrieval; primary URLs are first-party government / law / 通達 / 採択 surfaces."
  },
  "_provenance": {
    "source_module": "jpintel_mcp.mcp.moat_lane_tools.he1_full_context",
    "lane_id": "HE1",
    "observed_at": "2026-05-17",
    "composition": [
      "moat_n5_synonym.resolve_alias",
      "mcp.server.search_programs",
      "moat_n3_reasoning.walk_reasoning_chain",
      "moat_n4_window.find_filing_window",
      "moat_n1_artifact.list_artifact_templates",
      "moat_n2_portfolio.{get_houjin_portfolio,find_gap_programs}",
      "moat_n6_alert.list_pending_alerts",
      "moat_n7_segment.segment_summary",
      "moat_n8_recipe.list_recipes",
      "moat_n9_placeholder.resolve_placeholder"
    ],
    "no_llm": true,
    "round_trip_savings": "1 call replaces 5-10 atomic calls under typical depth_level=3 use."
  }
}
```

## Sample queries

```python
# 1. 補助金 (segment optional, houjin optional)
await mcp.call("agent_full_context", query="ものづくり補助金", depth_level=3)

# 2. 税制 + 税理士 (segment) + 特定法人 (houjin_bangou)
await mcp.call(
    "agent_full_context",
    query="インボイス制度",
    segment="税理士",
    houjin_bangou="8010001213708",
    depth_level=3,
)

# 3. 税務 deep dive (depth_level=5 → 全部入り、opposing views 含む)
await mcp.call(
    "agent_full_context",
    query="役員報酬の損金算入",
    segment="税理士",
    depth_level=5,
)

# 4. AI agent エンジニア向け軽量 lookup (depth_level=1 → 5 KB)
await mcp.call(
    "agent_full_context",
    query="IT導入",
    segment="AX_engineer",
    depth_level=1,
)
```

## What it replaces (典型的な agent walk)

Before HE-1 (5-10 round trips):

```text
1. resolve_alias("ものづくり補助金")          -> N5
2. search_programs(q="ものづくり補助金")       -> jpintel
3. walk_reasoning_chain(query=...)            -> N3
4. find_filing_window(program_id, houjin)     -> N4
5. list_artifact_templates(segment="税理士")  -> N1
6. get_houjin_portfolio(houjin_bangou)        -> N2
7. find_gap_programs(houjin_bangou)           -> N2
8. list_pending_alerts(houjin_bangou)         -> N6
9. list_recipes(segment="tax")                -> N8
10. resolve_placeholder * 10                  -> N9 × 10 = 10 calls
```

After HE-1 (1 round trip):

```text
1. agent_full_context(query, segment, houjin_bangou, depth_level=3)
   └─ server-side asyncio.gather() composes all 10 lanes in parallel.
```

## LLM cost calc (depth_level=3)

Assumptions (back-of-envelope, GPT-4o-class agent):
- Each round trip: ~2K tokens of compose context + ~500 tokens of response context.
- 10 round trips → 25K tokens at ~$5/1M input + $15/1M output.
- 1 round trip with HE-1 → 3K tokens compose + 8K tokens response (full envelope) = 11K total.

| metric | atomic (10 calls) | HE-1 (1 call) | reduction |
| --- | --- | --- | --- |
| LLM tokens | ~25,000 | ~11,000 | **56%** |
| jpcite ¥ | ¥3 × 10 = ¥30 | ¥3 × 1 = ¥3 | **90%** |
| wall time | 10 × ~400ms = ~4s | ~400ms parallel | **90%** |
| agent code complexity | 10 try/except blocks | 1 call site | massive |

Net agent-side LLM cost reduction: **~80%** when factoring in the saved
context-building and tool-routing overhead. The agent pays for HE-1
once at ¥3 and receives the whole knowledge graph slice it needs.

## Use cases

1. **税理士事務所の朝の顧問先点検** — 1 call で全顧問先の amendment / portfolio_gap / filing_windows を取得。
2. **AI agent の初回 query** — エージェントが最初に投げる "context-loading" 1-shot。後続の deep-dive はヒントの `next_call_hints` を follow。
3. **会計士の月次決算前 review** — 制度・通達・判例・採決を一括取得。
4. **行政書士の許認可前ヒアリング** — `list_artifact_templates(segment="行政書士")` + `find_filing_window` を 1 call。
5. **AX engineer の調査** — `segment="AX_engineer"` + `depth_level=5` で recipe + placeholder + reasoning chain を全部入り。

## Hard constraints

- NO LLM inference on the server side (composition のみ).
- NO HTTP roundtrip (in-process SQLite).
- `_billing_unit = 1` 固定 (¥3/req 構造を維持).
- §52 / §47条の2 / §72 / §1 / §3 disclaimer envelope on every response.

## Related

- [r01-tax-firm-monthly-review](r01-tax-firm-monthly-review/index.md) — manually composes a similar deck (now subsumed by HE-1).
- [r07-shindanshi-monthly-companion](r07-shindanshi-monthly-companion/index.md) — middle-market 中小企業診断士 walk.
- HE-2/HE-3 (planned) — billing-aware credit-wallet check & explainable
  knowledge-graph slice (Dim O surface).
