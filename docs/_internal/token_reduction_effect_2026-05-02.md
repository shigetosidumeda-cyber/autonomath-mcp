# Token Reduction Effect — 2026-05-02

## 結論

jpcite は「常に LLM 料金が下がる」とは言えないが、**長い PDF / Web ページ / 検索結果を LLM に読ませる前に、必要な根拠だけを 500〜1,300 tokens 程度の Evidence Packet に圧縮する効果**はある。

公開表現は次が安全:

> jpcite は回答生成前の Evidence Pre-fetch Layer です。長い公的資料や検索結果をそのまま LLM に渡す代わりに、出典 URL、取得時刻、content hash、provenance、既知の欠落を構造化した小さな evidence packet を返します。トークン量・外部 LLM API 料金への影響は workload-dependent です。

## 2026-05-02 offline probe

Command:

```bash
uv run python tools/offline/bench_prefetch_probe.py \
  --queries-csv tools/offline/bench_queries_2026_04_30.csv \
  --limit 5 \
  --rows-csv analysis_wave18/bench_prefetch_probe_2026-05-02.csv
```

Result:

| Metric | Value |
|---|---:|
| benchmark queries | 30 |
| zero-result queries | 0 |
| queries with at least one precomputed record | 12 |
| precomputed query rate | 40.0% |
| records returned total | 142 |
| precomputed records total | 37 |
| packet token estimate median | 566 |
| packet token estimate p25 | 532 |
| packet token estimate p75 | 1,163 |
| packet token estimate min / max | 338 / 1,352 |
| precomputed packet median | 1,213 |
| metadata-only packet median | 544 |

This probe uses local SQLite + EvidencePacketComposer only. It does not call any LLM API and does not prove answer quality by itself.

## What it can reduce

1. **Input context size vs raw source reading**

   If a user would otherwise paste or fetch a 5k〜50k token PDF/Web page/search result bundle, a 338〜1,352 token evidence packet is a material context reduction. In that scenario, the context-size reduction can be roughly 70〜99% depending on the raw source size.

2. **Tool/search calls**

   If the LLM would otherwise perform web search, open several URLs, extract text, and summarize, jpcite can replace that with 1 billable API/MCP call plus a compact packet. This is often the stronger value than pure token reduction.

3. **Output/reasoning waste**

   Supplying structured fields (`source_url`, `source_fetched_at`, `source_checksum`, `quality.known_gaps[]`) can reduce retries and citation repair prompts. This needs paired LLM measurement before public numeric claims.

## What it cannot honestly claim yet

1. **Guaranteed lower LLM bill**

   If the user asks a cheap model a simple question and accepts an answer from model memory, adding a jpcite packet increases input tokens and adds the jpcite request fee.

2. **Guaranteed lower total cost**

   Some providers include cheap or free search, prompt caching, batch discounts, or low-cost models. In those cases, the jpcite request can cost more unless provenance, freshness, auditability, or reduced retries matter.

3. **Universal token savings**

   Evidence packets are compact compared with raw sources, but not always compact compared with a bare user prompt.

## Product positioning

The strongest claim is not "token cost shield". It is:

> AI can write the answer. jpcite gives it the verified, compact evidence first.

Use token/cost language only as conditional:

> For evidence-heavy tasks, jpcite can reduce the amount of raw source text and search output that needs to be sent into the LLM. In the 2026-05-02 offline probe, benchmark evidence packets were 338〜1,352 estimated tokens, median 566. Actual LLM token/cost impact depends on model, prompt, cache, search settings, and whether the alternative workflow reads raw sources.

## Next measurement

Run the paired benchmark from `docs/bench_methodology.md` before any public percentage claim:

- `direct_web`: query only, provider web search on.
- `jpcite_packet`: query + Evidence Packet, provider web search off.
- `jpcite_precomputed_intelligence`: query + precomputed bundle, provider web search off.

Public numeric claim is allowed only after measuring:

- input tokens
- output tokens
- reasoning tokens
- web_search count
- jpcite_requests
- yen_cost_per_answer
- citation_rate
- hallucination_rate
