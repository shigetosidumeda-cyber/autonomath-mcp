# Opus 4.7 7-turn ground-truth fixtures — generation guide

This directory is populated **out-of-band by the operator** using Claude
Code Max Pro per query. `jpcite` production must **never** import an LLM
SDK (CLAUDE.md §3 hard constraint enforced by
`tests/test_no_llm_in_production.py`).

## Schema (per `<query_id>.json`)

```json
{
  "query_id": "<id from queries_2026_05_17.yaml>",
  "cohort": "<cohort id>",
  "query": "<verbatim Japanese query text>",
  "engine": "opus-4-7",
  "tool_calls": [
    { "step": 1, "verb": "think_through", "endpoint": null, "args": {} },
    { "step": 2, "verb": "outline", "endpoint": null, "args": {} },
    { "step": 3, "verb": "fetch_rule", "endpoint": "tax_rule_full_chain", "args": {} },
    { "step": 4, "verb": "synthesize", "endpoint": null, "args": {} },
    { "step": 5, "verb": "cite", "endpoint": "evidence_packets_query", "args": {} },
    { "step": 6, "verb": "review", "endpoint": null, "args": {} },
    { "step": 7, "verb": "render", "endpoint": null, "args": {} }
  ],
  "output_text": "<7-turn final answer>",
  "checklist_must_have": ["必須キーワード1", "必須キーワード2"],
  "referenced_endpoints": ["tax_rule_full_chain", "am_by_law"],
  "citations": [
    {
      "source_url": "https://elaws.e-gov.go.jp/...",
      "source_fetched_at": "2026-05-17T00:00:00+09:00",
      "label": "e-Gov 法令検索"
    }
  ],
  "self_reported_score": 80.0,
  "cost_jpy_estimate": 75,
  "tier": "C"
}
```

## Generation workflow

See `docs/_internal/P5_BENCHMARK_GROUND_TRUTH_GENERATION_2026_05_17.md`
for the full step-by-step operator playbook (Claude Code Max Pro session
template, cost capture, schema validation).

The scorer (`scripts/bench/score_p5_outputs_2026_05_17.py`) gracefully
skips queries that do not yet have an Opus fixture and reports them
under `missing_opus_count` in `data/p5_benchmark/scores/_summary.json`.
