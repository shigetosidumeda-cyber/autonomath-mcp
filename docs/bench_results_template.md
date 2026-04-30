# Bench results template

> Operators copy this file to `docs/bench_results_YYYY-MM-DD.md`,
> fill in the numbers, and publish under that dated filename.
> The template itself stays empty — DO NOT paste real numbers here.

## Bench results YYYY-MM-DD

- Model: `claude-sonnet-4-6` (or `gpt-4o-2024-11-20`, `gemini-2.0-pro`, etc.)
- Queries: 30 (see `tools/offline/bench_queries_2026_04_30.csv`)
- Run by: `<operator>`
- Date: `2026-MM-DD`
- jpcite `corpus_snapshot_id` (jpcite_packet arm): `<from packet>`
- LLM provider input price (¥ per 1M tokens): `<rate>`
- LLM provider output price (¥ per 1M tokens): `<rate>`
- JPY/USD rate used: `<rate>`

### Per-arm medians

| Metric | direct_web (median, p25–p75) | jpcite_packet (median, p25–p75) | Δ% (median) |
|---|---:|---:|---:|
| input_tokens | ... (... – ...) | ... (... – ...) | ...% |
| output_tokens | ... (... – ...) | ... (... – ...) | ...% |
| reasoning_tokens | ... (... – ...) | ... (... – ...) | ...% |
| web_searches | ... (... – ...) | 0 (0 – 0) | ...% |
| jpcite_requests | 0 (0 – 0) | ... (... – ...) | n/a |
| yen_cost_per_answer | ¥... (¥... – ¥...) | ¥... (¥... – ¥...) | ...% |
| latency_seconds | ... (... – ...) | ... (... – ...) | ...% |

### Per-arm rates

| Metric | direct_web (mean) | jpcite_packet (mean) |
|---|---:|---:|
| citation_rate | ... | ... |
| hallucination_rate | ... | ... |

### Cost-per-answer distribution

Sorted full distribution (¥), N=30 each arm:

```
direct_web:    [..., ..., ..., ...]
jpcite_packet: [..., ..., ..., ...]
```

### Caveats (REQUIRED — do not delete)

- Bench was run on **N=30 queries** stratified across 5 domains
  (10 補助金 / 5 法人 / 5 法令 / 5 税制 / 5 行政処分) on date
  `2026-MM-DD` with model `<model>`.
- Results vary by **model, prompt, query distribution, customer
  environment, provider free tiers, and provider-side caching**.
- Free LLM tiers and provider-side prompt caching are **not modeled**
  in the ¥cost numbers above.
- The Δ% column is the median delta, not a guarantee. Customers will
  observe different numbers on their own query distributions.
- Phrasing rules from `docs/bench_methodology.md` §6 apply: no
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

# 2. Operator runs each instruction line manually against their LLM
#    provider, writes bench_results.csv with the columns listed in
#    docs/bench_methodology.md §3.

# 3. Aggregate
python tools/offline/bench_harness.py \
    --results-csv bench_results.csv \
    --mode aggregate \
    > bench_summary.json
```

See `docs/bench_methodology.md` for the full procedure, including
the two-arm contract, metric definitions, and disclosure block.
