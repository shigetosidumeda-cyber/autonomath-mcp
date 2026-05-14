# Bench results template

> Operators copy this file to `docs/bench_results_YYYY-MM-DD.md`,
> fill in the numbers, and publish under that dated filename.
> The template itself stays empty — DO NOT paste real numbers here.

## Bench results YYYY-MM-DD

This dated report measures **Evidence Pre-fetch** and **Precomputed
Intelligence** against a caller-supplied comparison baseline. It does
not claim that jpcite always saves tokens or always lowers cost.

- Model: `claude-sonnet-4-6` (or `gpt-4o-2024-11-20`, `gemini-2.0-pro`, etc.)
- Queries: 30 (see `tools/offline/bench_queries_2026_04_30.csv`)
- Run by: `<operator>`
- Date: `2026-MM-DD`
- jpcite `corpus_snapshot_id` (jpcite arms): `<from packet / bundle>`
- LLM provider input price (¥ per 1M tokens): `<rate>`
- LLM provider output price (¥ per 1M tokens): `<rate>`
- JPY/USD rate used: `<rate>`

Required measured fields per answer: `input_tokens`, `output_tokens`,
`reasoning_tokens`, `web_searches`, `jpcite_requests`,
`yen_cost_per_answer`, `citation_rate`, and `hallucination_rate`.
For `jpcite_precomputed_intelligence`, also record natural-language
lookup coverage: `records_returned`, `precomputed_record_count`, and
`zero_result_rate`. Before operator LLM calls, run
`tools/offline/bench_prefetch_probe.py` and use its output to fill
`records_returned`, `precomputed_record_count`, and
`packet_tokens_estimate` where the probe can measure them. If the query
CSV includes `baseline_source_tokens` / `source_token_count` or
`baseline_source_pdf_pages` / `source_pdf_pages`, also record
`baseline_source_method`, `source_tokens_estimate`, `input_context_reduction_rate`,
`break_even_source_tokens_estimate`, and `break_even_met`.

### Per-arm medians

| Metric | direct_web (median, p25–p75) | jpcite_packet (median, p25–p75) | Δ% vs direct_web | jpcite_precomputed_intelligence (median, p25–p75) | Δ% vs direct_web |
|---|---:|---:|---:|---:|---:|
| input_tokens | ... (... – ...) | ... (... – ...) | ...% | ... (... – ...) | ...% |
| output_tokens | ... (... – ...) | ... (... – ...) | ...% | ... (... – ...) | ...% |
| reasoning_tokens | ... (... – ...) | ... (... – ...) | ...% | ... (... – ...) | ...% |
| web_searches | ... (... – ...) | 0 (0 – 0) | ...% | 0 (0 – 0) | ...% |
| jpcite_requests | 0 (0 – 0) | ... (... – ...) | n/a | ... (... – ...) | n/a |
| yen_cost_per_answer | ¥... (¥... – ¥...) | ¥... (¥... – ¥...) | ...% | ¥... (¥... – ¥...) | ...% |
| latency_seconds | ... (... – ...) | ... (... – ...) | ...% | ... (... – ...) | ...% |

### Per-arm rates

| Metric | direct_web (mean) | jpcite_packet (mean) | jpcite_precomputed_intelligence (mean) |
|---|---:|---:|---:|
| citation_rate | ... | ... | ... |
| hallucination_rate | ... | ... | ... |

### Natural-language query hit-rate

For `jpcite_precomputed_intelligence` only:

| Field | Value |
|---|---:|
| records_returned | ... |
| precomputed_record_count | ... |
| packet_tokens_estimate | ... |
| queries_with_source_token_baseline | ... |
| queries_with_break_even_inputs | ... |
| rows_missing_source_token_baseline | ... |
| rows_without_price | ... |
| negative_context_rows | ... |
| median_context_reduction_rate | ...% |
| context_reduction_rate_p25-p75 | ...% - ...% |
| break_even_rate | ...% |
| baseline_source_method_breakdown | `<caller_token_count: ..., pdf_pages_estimate: ...>` |
| break_even_rate_by_price | `<¥100/1M: ..., ¥300/1M: ..., ¥1000/1M: ...>` |
| zero_result_rate | ...% |

Use `records_returned` as the per-query returned-record count or as the
reported aggregate specified in `notes`. `zero_result_rate` is the share
of precomputed-arm queries where `records_returned = 0`.
`packet_tokens_estimate` is an estimate of context size, not a measured
LLM billing token count. `median_context_reduction_rate` and
`break_even_rate` are input-context estimates from the probe.
`break_even_rate_by_price` is a
sensitivity table only; keep measured token-count baselines separate
from PDF-page estimates when writing the result narrative.

### Cost-per-answer distribution

Sorted full distribution (¥), N=30 each arm:

```
direct_web:                        [..., ..., ..., ...]
jpcite_packet:                     [..., ..., ..., ...]
jpcite_precomputed_intelligence:   [..., ..., ..., ...]
```

### Caveats (REQUIRED — do not delete)

- 比較対象: raw user query を LLM provider の web search に渡す方式、
  jpcite Evidence Packet を前処理して LLM に渡す方式、事前計算済み
  jpcite intelligence bundle を LLM に渡す方式。対象: ベンチ実施日
  時点の補助金・法人・法令・税制・行政処分クエリ N=30 件 (詳細は
  `tools/offline/bench_queries_2026_04_30.csv`)。指標: input_tokens,
  output_tokens, reasoning_tokens, web_searches, jpcite_requests,
  yen_cost_per_answer, latency_seconds, citation_rate,
  hallucination_rate。**結果はモデル、プロンプト、クエリ分布、顧客環境、
  プロバイダ無料枠、provider側キャッシュ効果により大きく変動します。**
- Bench was run on **N=30 queries** stratified across 5 domains
  (10 補助金 / 5 法人 / 5 法令 / 5 税制 / 5 行政処分) on date
  `2026-MM-DD` with model `<model>`.
- Results vary by **model, prompt, query distribution, customer
  environment, provider free tiers, and provider-side caching**.
- Free LLM tiers and provider-side prompt caching are **not modeled**
  in the ¥cost numbers above.
- The Δ% column is the median delta, not a guarantee. Customers will
  observe different numbers on their own query distributions. For each
  jpcite arm, Δ% is computed against `direct_web`.
- `direct_web` uses provider web search. The jpcite arms disable
  provider web search and instead include Evidence Packet or
  Precomputed Intelligence context plus `jpcite_requests`. Interpret
  savings as a measured operating-mode comparison, not as proof that
  every workload will use fewer tokens.
- A cheaper arm with lower `citation_rate` or higher
  `hallucination_rate` must be reported as a cost/quality tradeoff, not
  as an unqualified saving.
- Natural-language query hit-rate fields for
  `jpcite_precomputed_intelligence` measure lookup coverage only; they
  do not prove answer quality or cost savings by themselves.
- `packet_tokens_estimate` is produced before the LLM call from the
  prefetched packet/bundle. Treat it as an operator-side context-size
  estimate; use provider-reported `input_tokens` for billing claims.
- Phrasing rules from `docs/bench_methodology.md` §7 apply: no
  「必ずX%削減」、「業界最安」、「ChatGPTより正確」 phrasing in any
  derivative collateral citing this file.

### Replication

```bash
# 1. Generate bench instructions (no LLM call from this repo)
python tools/offline/bench_harness.py \
    --queries-csv tools/offline/bench_queries_2026_04_30.csv \
    --mode emit \
    --model <your-model> \
    > bench_instructions.jsonl

# Optional legacy two-arm run:
# python tools/offline/bench_harness.py \
#     --queries-csv tools/offline/bench_queries_2026_04_30.csv \
#     --mode emit \
#     --model <your-model> \
#     --arms direct_web,jpcite_packet \
#     > bench_instructions.jsonl

# 2. Probe jpcite prefetch URLs before any operator LLM calls.
python tools/offline/bench_prefetch_probe.py \
    --queries-csv tools/offline/bench_queries_2026_04_30.csv \
    --rows-csv bench_prefetch_probe.csv \
    --input-token-price-jpy-per-1m 300 \
    --price-scenarios 100,300,1000

# Copy records_returned, precomputed_record_count, packet_tokens_estimate,
# baseline_source_method, source_tokens_estimate, input_context_reduction_rate,
# break_even_source_tokens_estimate, and break_even_met from
# bench_prefetch_probe.csv into the matching jpcite rows when present.
# Copy baseline_source_method_breakdown and break_even_rate_by_price from
# the JSON summary into the aggregate table/disclosure when present.
# Leave fields empty when the probe cannot measure them.

# 3. Operator runs each instruction line manually against their LLM
#    provider, writes bench_results.csv with the columns listed in
#    docs/bench_methodology.md §3.

# 4. Aggregate
python tools/offline/bench_harness.py \
    --results-csv bench_results.csv \
    --mode aggregate \
    > bench_summary.json
```

See `docs/bench_methodology.md` for the full procedure, including
the arm contract, metric definitions, and disclosure block.
