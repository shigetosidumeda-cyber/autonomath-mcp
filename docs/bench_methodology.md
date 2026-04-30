# Bench methodology: `direct_web` vs `jpcite_packet`

Status: planning + tooling. The harness is shipped under
`tools/offline/bench_harness.py` (operator-only). **No LLM call runs from
this repository.** The operator (or a customer / analyst) executes the
LLM calls themselves and feeds results back to the harness.

This document specifies how to run the bench. It does NOT publish
results. Result publication uses `docs/bench_results_template.md` as the
public format.

## 1. Why this bench exists

Per `docs/_internal/llm_resilient_business_plan_2026-04-30.md` Section
9.1 ("Bench方法"), public claims about token / cost reduction must be
backed by a paired A/B benchmark on the same questions, same model,
same date. We must NEVER state a fixed reduction percentage (e.g.
"AIコスト90%削減") — only "当社指定ベンチでは中央値X%低下" with the disclosed
caveats below.

## 2. Two-arm design

Each query is run **twice** against the same model with the same prompt
scaffold. Only the input changes.

| arm | input to LLM | tools enabled | what it measures |
|---|---|---|---|
| `direct_web` | user query alone | provider web search ON | LLM自力深掘り cost / tokens / search count |
| `jpcite_packet` | user query + Evidence Packet (prefetched from `GET /v1/evidence/packets/query?q=...`) | provider web search OFF | jpcite前処理した場合の cost / tokens / 残searches |

The two arms are paired per query — aggregations are paired-sample
medians, not unpaired pools.

### 2.1 Arm: `direct_web`

1. Read query string from the input CSV.
2. Call the operator's chosen LLM (Claude Sonnet, GPT-4o, Gemini 2.0,
   etc.) with:
   - `model = <operator-chosen>`
   - `system = "Answer the user's question about Japanese public
     subsidies / laws / tax / corporations. Cite primary government
     sources when possible."`
   - `messages = [{"role":"user","content": <query>}]`
   - `tools = [web_search]` (provider-specific tool name).
3. Record from the response: `input_tokens`, `output_tokens`,
   `reasoning_tokens` (if exposed by provider), number of `web_search`
   tool calls, `latency_seconds`, the answer text.
4. `jpcite_requests = 0` for this arm.

### 2.2 Arm: `jpcite_packet`

1. Read the same query string.
2. Prefetch evidence: `GET https://api.jpcite.com/v1/evidence/packets/query?q=<urlencoded>`.
   - Record `jpcite_requests = 1` (each customer-billable jpcite call
     counts; if the harness needs to follow up with `/v1/programs/{id}`
     etc. for richer context, increment per call).
   - Record the packet's `corpus_snapshot_id`, `packet_id`,
     `generated_at` for replay.
3. Call the same LLM with:
   - `model = <same as arm A>`
   - `system = "Answer using ONLY the provided evidence packet. Do not
     web-search. Cite the source_url, fetched_at, and corpus_snapshot_id
     from the packet."`
   - `messages = [{"role":"user","content": <query> + "\n\n=== Evidence
     Packet ===\n" + <packet JSON, pretty-printed>}]`
   - `tools = []` (web search disabled).
4. Record the same metrics. `web_searches` is expected to be `0`.

## 3. Per-query metrics logged

Each row of `bench_results.csv` MUST carry these columns. Operators may
add extras but cannot drop these.

| column | type | source | notes |
|---|---|---|---|
| `query_id` | int | input CSV | 1-indexed |
| `query_text` | str | input CSV | original Japanese question |
| `arm` | str | harness | `direct_web` or `jpcite_packet` |
| `model` | str | operator | e.g. `claude-sonnet-4-6`, `gpt-4o-2024-11-20` |
| `input_tokens` | int | LLM provider response | |
| `output_tokens` | int | LLM provider response | |
| `reasoning_tokens` | int | LLM provider response | 0 if provider doesn't expose |
| `web_searches` | int | LLM provider response | count of web_search tool invocations |
| `jpcite_requests` | int | harness | 0 for `direct_web`, ≥1 for `jpcite_packet` |
| `yen_cost_per_answer` | float | operator-computed | LLM token cost (¥) + jpcite ¥3/req × jpcite_requests |
| `latency_seconds` | float | wall-clock | round-trip from query send to final answer |
| `citation_rate` | float | operator-rated | fraction of factual claims with a `source_url` |
| `hallucination_rate` | float | operator-rated | fraction of factual claims unsupported by source |
| `corpus_snapshot_id` | str | jpcite packet (B arm only) | empty for direct_web |
| `packet_id` | str | jpcite packet (B arm only) | empty for direct_web |
| `notes` | str | operator | freeform |

Token-cost computation (¥):

```
yen_cost_per_answer = (input_tokens / 1_000_000) * input_price_jpy_per_M
                    + (output_tokens / 1_000_000) * output_price_jpy_per_M
                    + (jpcite_requests * 3.0)
```

Operator records the `input_price_jpy_per_M` / `output_price_jpy_per_M`
they used (varies by model + JPY/USD rate at run date). This goes in
the `notes` column or the result template caveats.

## 4. Aggregation

Per arm, after all queries are scored, compute:

- `median(input_tokens)`, `p25(input_tokens)`, `p75(input_tokens)`
- `median(output_tokens)`, `p25 / p75`
- `median(reasoning_tokens)`, `p25 / p75`
- `median(web_searches)`, `p25 / p75`
- `median(jpcite_requests)`, `p25 / p75`
- `median(yen_cost_per_answer)`, `p25 / p75`
- `median(latency_seconds)`, `p25 / p75`
- `mean(citation_rate)` and `mean(hallucination_rate)` (rates already
  bounded 0..1, mean is the natural aggregate)

Δ% in the published table is `(direct_web - jpcite_packet) / direct_web * 100`,
computed per metric, on the medians only.

## 5. Sample size and stratification

Minimum N for a public publication: **30 queries**, stratified across
the five domains in `tools/offline/bench_queries_2026_04_30.csv`:

| domain | count | example |
|---|---:|---|
| 補助金 (subsidies) | 10 | 「東京都の設備投資補助金は?」 |
| 法人 lookup | 5 | 「法人番号 4120101047866 の採択履歴」 |
| 法令 | 5 | 「インボイス制度 売上1000万円未満 必要書類」 |
| 税制 | 5 | 「研究開発税制 中小企業 控除率」 |
| 行政処分 | 5 | 「過去3年の建設業 業務停止」 |

We do not claim 30 queries are representative of all customer
distributions — the publication template states this explicitly.

## 6. Required disclosure on every published number

Every public bench result MUST include the following block (already
baked into `docs/bench_results_template.md`):

> 比較対象: raw user query を LLM provider の web search に渡す方式と、
> jpcite Evidence Packet を前処理して LLM に渡す方式。対象: ベンチ実施日
> 時点の補助金・法人・法令・税制・行政処分クエリ N=30 件 (詳細は
> `tools/offline/bench_queries_2026_04_30.csv`)。指標: input_tokens,
> output_tokens, reasoning_tokens, web_searches, jpcite_requests,
> yen_cost_per_answer, latency_seconds, citation_rate,
> hallucination_rate。**結果はモデル、プロンプト、クエリ分布、顧客環境、
> プロバイダ無料枠、provider側キャッシュ効果により大きく変動します。**

Forbidden phrasing (per Section 9.1):

- 「トークン費を必ずX%削減」
- 「AIコストX%削減」(数字確定形)
- 「何円節約できます」(個別保証形)
- 「業界最安」「ChatGPT より安い・正確」

Allowed phrasing:

- 「当社指定ベンチでは中央値X%低下しました」
- 「N=30 のベンチ範囲では中央値Y%低下を観測」(分母 + 算定日付き)

## 7. Replication procedure (operator)

```bash
# 1. Generate bench instructions (no LLM call)
python tools/offline/bench_harness.py \
    --queries-csv tools/offline/bench_queries_2026_04_30.csv \
    --mode emit \
    > bench_instructions.jsonl

# 2. Operator runs each instruction line manually against their LLM
#    provider and writes results to bench_results.csv with the columns
#    listed in §3 above. The harness does NOT call the LLM.

# 3. Aggregate
python tools/offline/bench_harness.py \
    --results-csv bench_results.csv \
    --mode aggregate \
    > bench_summary.json

# 4. Operator pastes medians into docs/bench_results_template.md and
#    publishes under docs/bench_results_YYYY-MM-DD.md.
```

## 8. What the harness explicitly does NOT do

- Call any LLM provider (Anthropic, OpenAI, Google, etc.).
- Import `anthropic`, `openai`, `google.generativeai`, or
  `claude_agent_sdk`. The CI guard
  `tests/test_no_llm_in_production.py` enforces this for `src/`,
  `scripts/`, and `tests/`. `tools/offline/bench_harness.py` is the
  harness — it generates instructions and aggregates results, period.
- Hardcode an expected reduction percentage. There is no
  `EXPECTED_DELTA = 0.9` or similar in the code or docs.
- Run the bench in CI. The harness is operator-driven; `pytest`
  exercises only the instruction-emission and aggregation paths
  using fixture data.

## 9. References

- `docs/_internal/llm_resilient_business_plan_2026-04-30.md` §9.1
  (bench specification).
- `docs/_internal/llm_resilient_business_plan_2026-04-30.md` §6
  (Evidence Packet shape).
- `tools/offline/README.md` (operator-only boundary rules).
- `tests/test_no_llm_in_production.py` (CI invariant).
- `feedback_autonomath_no_api_use` (operator memory: ¥3/req structure
  cannot absorb LLM-API cost on hot path).
