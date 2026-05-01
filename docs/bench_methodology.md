# Bench methodology: three-arm token-cost benchmark

Status: measurement protocol. The harness is shipped under
`tools/offline/bench_harness.py`. **No LLM call runs from
the production service.** The operator (or a customer / analyst) executes the
LLM calls themselves and feeds results back to the harness.

This document specifies how to run the bench. It does NOT publish
results. Result publication uses `docs/bench_results_template.md` as the
public format.

## 1. Why this bench exists

This is an operator-facing measurement protocol for **Evidence
Pre-fetch** and **Precomputed Intelligence**. It is a workload-dependent
measurement, not a headline claim that supplying jpcite evidence
universally saves tokens or universally reduces cost. The observed
direction and magnitude of any token / cost / citation / hallucination
delta depend on the model, prompt scaffold, query distribution,
provider prompt-cache state, provider tool pricing, run date, and
customer environment. The benchmark measures whether, for a fixed
model, prompt scaffold, query set, and run date, supplying jpcite
evidence before the LLM call changes token use, web-search use, answer
cost, citation behavior, and unsupported-claim rate relative to a
direct web-search baseline.

Public claims about token / cost reduction must be
backed by a paired A/B benchmark on the same questions, same model,
same date. We must NEVER state a fixed reduction percentage as a
generalized headline (e.g. a flat "AIコスト◯◯%削減" claim) — actual
deltas vary materially by workload, prompt scaffold, model selection,
provider prompt-cache hit rate, and provider web-search / tool pricing.
Only "当社指定ベンチでは中央値X%低下" — scoped to the benchmark date,
model, and query set — with the disclosed caveats below is acceptable.

The minimum measurement set is: `input_tokens`, `output_tokens`,
`reasoning_tokens`, `web_searches`, `jpcite_requests`,
`yen_cost_per_answer`, `citation_rate`, and `hallucination_rate`.
Latency is also logged so operators can see operational tradeoffs, but
latency is not part of the token-cost claim.

## 2. Three-arm design

Each query is run against the same model with the same prompt
scaffold. Only the input changes.

| arm | input to LLM | tools enabled | what it measures |
|---|---|---|---|
| `direct_web` | user query alone | provider web search ON | baseline LLM self-research behavior: tokens, cost, web-search count, citations, unsupported claims |
| `jpcite_packet` | user query + Evidence Packet (prefetched from `POST /v1/evidence/packets/query`) | provider web search OFF | Evidence Pre-fetch: whether supplied source packets reduce search/tool dependence and change token/cost/quality metrics |
| `jpcite_precomputed_intelligence` | user query + precomputed jpcite intelligence bundle | provider web search OFF | Precomputed Intelligence: whether a prepared bundle changes token/cost/quality metrics without provider web search |

The arms are paired per query. Default public runs should include all
three arms. The aggregator also accepts legacy two-arm CSVs containing
only `direct_web` and `jpcite_packet`; in that case the paired count and
deltas are computed over the active arms present in the CSV.

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
2. Prefetch evidence: `POST https://api.jpcite.com/v1/evidence/packets/query` with the query in the JSON body.
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

### 2.3 Arm: `jpcite_precomputed_intelligence`

1. Read the same query string.
2. Prefetch the operator-owned precomputed intelligence bundle for the
   query. The harness emits the expected serving URL:
   `GET https://api.jpcite.com/v1/intelligence/precomputed/query?q=<urlencoded>`.
   If the run uses an internal export or customer-specific precompute
   instead of that URL, record the actual source in `notes`.
   - Record `jpcite_requests = 1` unless the precompute/export path uses
     multiple customer-billable jpcite calls; then increment per call.
   - Record `corpus_snapshot_id`, the bundle/generated timestamp, and
     the bundle id in `packet_id` if available.
   - Record natural-language query hit-rate fields:
     `records_returned` for the number of records returned for this
     query, and `precomputed_record_count` for the number of records
     available in the precomputed index/snapshot searched for this
     query.
3. Call the same LLM with:
   - `model = <same as arm A>`
   - `system = "Answer using ONLY the provided precomputed jpcite
     intelligence bundle. Do not web-search. Cite source_url,
     fetched_at, corpus_snapshot_id, and any bundle/provenance id
     present in the bundle."`
   - `messages = [{"role":"user","content": <query> + "\n\n===
     Precomputed jpcite intelligence ===\n" + <bundle JSON,
     pretty-printed>}]`
   - `tools = []` (web search disabled).
4. Record the same metrics. `web_searches` is expected to be `0`.

## 2.4 Offline prefetch probe before LLM calls

Before running any operator LLM calls, run the offline prefetch probe
against the generated jpcite prefetch instructions. The probe is
operator-only instrumentation: it fetches the jpcite packet/bundle
URLs, records lookup coverage and approximate packet size, and gives
the operator concrete values to copy into `bench_results.csv`. It does
not call an LLM and does not establish answer quality or token/cost
savings by itself.

Typical sequence:

```bash
# First emit the bench instruction set.
python tools/offline/bench_harness.py \
    --queries-csv tools/offline/bench_queries_2026_04_30.csv \
    --mode emit \
    --model <your-model> \
    > bench_instructions.jsonl

# Then probe jpcite prefetch URLs before any LLM provider calls.
python tools/offline/bench_prefetch_probe.py \
    --instructions-jsonl bench_instructions.jsonl \
    --output-csv bench_prefetch_probe.csv
```

Use the probe output to fill, for each applicable jpcite row:

- `records_returned`: number of records returned for that query.
- `precomputed_record_count`: number of records available in the
  precomputed index/snapshot searched for that query, when exposed by
  the prefetch response.
- `packet_tokens_estimate`: estimated token count of the packet/bundle
  that will be supplied to the LLM.

Leave a field empty when the prefetch response or probe cannot measure
it. Do not substitute an assumed value. If the operator changes the
packet/bundle between probing and the LLM call, rerun the probe or note
the mismatch in `notes`.

## 3. Per-query metrics logged

Each row of `bench_results.csv` MUST carry these columns. Operators may
add extras but cannot drop these.

| column | type | source | notes |
|---|---|---|---|
| `query_id` | int | input CSV | 1-indexed |
| `query_text` | str | input CSV | original Japanese question |
| `arm` | str | harness | `direct_web`, `jpcite_packet`, or `jpcite_precomputed_intelligence` |
| `model` | str | operator | e.g. `claude-sonnet-4-6`, `gpt-4o-2024-11-20` |
| `input_tokens` | int | LLM provider response | |
| `output_tokens` | int | LLM provider response | |
| `reasoning_tokens` | int | LLM provider response | 0 if provider doesn't expose |
| `web_searches` | int | LLM provider response | count of web_search tool invocations |
| `jpcite_requests` | int | harness | 0 for `direct_web`, ≥1 for jpcite arms |
| `yen_cost_per_answer` | float | operator-computed | LLM token cost (¥) + jpcite ¥3/req × jpcite_requests |
| `latency_seconds` | float | wall-clock | round-trip from query send to final answer |
| `citation_rate` | float | operator-rated | fraction of factual claims with a `source_url` |
| `hallucination_rate` | float | operator-rated | fraction of factual claims unsupported by source |
| `corpus_snapshot_id` | str | jpcite arms only | empty for direct_web |
| `packet_id` | str | jpcite arms only | Evidence Packet id or precomputed bundle id; empty for direct_web |
| `records_returned` | int | precomputed arm only | number of records returned by natural-language lookup; empty for other arms |
| `precomputed_record_count` | int | precomputed arm only | total records in the searched precomputed index/snapshot; empty for other arms |
| `packet_tokens_estimate` | int | jpcite arms only | approximate token count of the prefetched packet/bundle supplied to the LLM; empty when not measured |
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

Δ% in the published table is computed against the `direct_web`
baseline per candidate arm:

```
(direct_web_median - candidate_arm_median) / direct_web_median * 100
```

The harness keeps the legacy top-level `median_delta_pct` key for
`direct_web` vs `jpcite_packet` and also emits
`median_delta_pct_vs_direct_web` keyed by every non-baseline active arm.

For the `jpcite_precomputed_intelligence` arm, also report the
natural-language query hit-rate:

- `records_returned`: per-query count of records returned by the
  natural-language lookup.
- `precomputed_record_count`: per-query or run-level count of records in
  the precomputed index/snapshot searched.
- `packet_tokens_estimate`: per-query estimate of the precomputed
  bundle tokens supplied to the LLM.
- `zero_result_rate`: share of precomputed-arm queries where
  `records_returned = 0`.

These fields measure lookup coverage for the precomputed arm. They do
not by themselves establish answer quality, token savings, or cost
savings; interpret them alongside `citation_rate`,
`hallucination_rate`, and `yen_cost_per_answer`.

## 5. Interpreting savings across web-search and no-web-search arms

The `direct_web` arm uses provider web search, while the two jpcite arms
disable provider web search and pay for `jpcite_requests` instead. Treat
observed savings as a comparison between operating modes, not as proof
that jpcite universally compresses prompts.

Interpret the deltas as follows:

- A lower `yen_cost_per_answer` means the measured LLM token cost plus
  jpcite request cost was lower for that arm under the recorded prices.
  It does not include provider free tiers, provider prompt-cache
  discounts, operator labor, or customer-specific procurement terms
  unless the operator explicitly modeled them in `notes`.
- A lower `web_searches` count for jpcite arms is expected because web
  search is disabled by design. Do not describe this as a search-quality
  win by itself; pair it with `citation_rate` and
  `hallucination_rate`.
- Higher `input_tokens` in a jpcite arm can still produce lower
  `yen_cost_per_answer` if it reduces output/reasoning tokens or avoids
  provider web-search/tool costs captured by the operator. Conversely,
  a jpcite arm can cost more if the packet or bundle is too large.
- `citation_rate` and `hallucination_rate` are quality gates. A cheaper
  arm with worse support quality should be reported as a tradeoff, not
  as a saving.
- The honest public framing is "Evidence Pre-fetch / Precomputed
  Intelligence was measured against direct provider web search on this
  query set"; avoid wording that implies all customers or all workloads
  will save tokens.

## 6. Sample size and stratification

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

## 7. Required disclosure on every published number

Every public bench result MUST include the following block (already
baked into `docs/bench_results_template.md`):

> 比較対象: raw user query を LLM provider の web search に渡す方式、
> jpcite Evidence Packet を前処理して LLM に渡す方式、事前計算済み
> jpcite intelligence bundle を LLM に渡す方式。対象: ベンチ実施日
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
- "In this benchmark, Evidence Pre-fetch / Precomputed Intelligence was
  measured against direct provider web search and showed the following
  deltas..."

## 8. Replication procedure (operator)

```bash
# 1. Generate bench instructions (no LLM call)
python tools/offline/bench_harness.py \
    --queries-csv tools/offline/bench_queries_2026_04_30.csv \
    --mode emit \
    > bench_instructions.jsonl

# Optional legacy two-arm run:
# python tools/offline/bench_harness.py \
#     --queries-csv tools/offline/bench_queries_2026_04_30.csv \
#     --mode emit \
#     --arms direct_web,jpcite_packet \
#     > bench_instructions.jsonl

# 2. Probe jpcite prefetch URLs before any operator LLM calls.
#    Copy measured records_returned, precomputed_record_count, and
#    packet_tokens_estimate into the matching bench_results.csv rows.
python tools/offline/bench_prefetch_probe.py \
    --instructions-jsonl bench_instructions.jsonl \
    --output-csv bench_prefetch_probe.csv

# 3. Operator runs each instruction line manually against their LLM
#    provider and writes results to bench_results.csv with the columns
#    listed in §3 above. The harness does NOT call the LLM.

# 4. Aggregate
python tools/offline/bench_harness.py \
    --results-csv bench_results.csv \
    --mode aggregate \
    > bench_summary.json

# 5. Operator pastes medians into docs/bench_results_template.md and
#    publishes under docs/bench_results_YYYY-MM-DD.md.
```

## 9. What the harness explicitly does NOT do

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

## 10. References

- `tools/offline/README.md` (offline harness boundary rules).
- `tests/test_no_llm_in_production.py` (CI invariant).
