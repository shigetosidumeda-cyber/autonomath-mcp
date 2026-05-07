# composite_vs_naive — bench summary

- Programs sampled: **5**
- Scenarios: **5** (eligibility / amendment_diff / similar / citation_pack / houjin_360)
- Pricing: **claude-opus-4-7** list price (W26-3 estimator, NO LLM call).

## Per-scenario rollup (sum over sampled programs)

| Scenario | Mode | Calls | Tokens | DB queries | Wall ms | USD |
|---|---|---:|---:|---:|---:|---:|
| eligibility_lookup | naive | 2 | 6,797 | 15 | 24,489 | $0.15416 |
| eligibility_lookup | composite | 1 | 3,689 | 5 | 900 | $0.09914 |
| amendment_diff | naive | 2 | 23,765 | 15 | 11,098 | $0.40868 |
| amendment_diff | composite | 1 | 3,105 | 5 | 900 | $0.09037 |
| similar_programs | naive | 5 | 8,942 | 25 | 12,741 | $0.21513 |
| similar_programs | composite | 1 | 3,632 | 5 | 900 | $0.10548 |
| citation_pack | naive | 8 | 10,480 | 40 | 20,072 | $0.26700 |
| citation_pack | composite | 1 | 5,781 | 5 | 900 | $0.14492 |
| houjin_360 | naive | 8 | 7,220 | 40 | 19,718 | $0.21810 |
| houjin_360 | composite | 1 | 3,410 | 5 | 2,496 | $0.10935 |

## Reduction (composite vs naive)

| Scenario | Calls reduction | Token reduction | DB query reduction | Latency reduction |
|---|---|---|---|---|
| eligibility_lookup | 2→1 (50.0%) | 6,797→3,689 (54.3%) | 15→5 (33.3%) | 24,489→900ms (3.7%) |
| amendment_diff | 2→1 (50.0%) | 23,765→3,105 (13.1%) | 15→5 (33.3%) | 11,098→900ms (8.1%) |
| similar_programs | 5→1 (20.0%) | 8,942→3,632 (40.6%) | 25→5 (20.0%) | 12,741→900ms (7.1%) |
| citation_pack | 8→1 (12.5%) | 10,480→5,781 (55.2%) | 40→5 (12.5%) | 20,072→900ms (4.5%) |
| houjin_360 | 8→1 (12.5%) | 7,220→3,410 (47.2%) | 40→5 (12.5%) | 19,718→2,496ms (12.7%) |

## Headline (5 scenarios × programs)

- HTTP calls: **25 naive → 5 composite** (0.20× of naive)
- Total tokens: **57,204 naive → 19,617 composite** (34.3% of naive, saves 37,587 tokens)
- DB queries: **135 naive → 25 composite** (18.5% of naive, saves 110 statements)
- Wall clock: **88,118 ms naive → 6,096 ms composite** (6.9% of naive, saves 82,022 ms)
- USD: **$1.26306 naive → $0.54926 composite** (43.5% of naive, saves $0.71381)

## Methodology + caveats

- Token math via W26-3 estimator (`benchmarks/jcrb_v1/token_estimator.py`). **NO LLM API call** — count is deterministic per the cl100k_base + Japanese 1.3× bias factor for Claude.
- DB query count: real `sqlite3.set_trace_callback` against `autonomath.db` (read-only `mode=ro&immutable=1` URI). The naive path issues one query per facet; composite collapses to a single JOIN-friendly query.
- Wall clock: real round-trip when the live API returned 200; otherwise calibrated fallback (140 ms/naive call, 180 ms/composite). Composite endpoints `/v1/intel/program/{id}/full` + `/v1/intel/citation_pack/{id}` are not yet wired in production; their bodies are size-calibrated synthesis. `/v1/houjin/{bangou}` IS the real composite (`api/houjin.py`).
- Output token model: naive must re-quote per facet (110 + 32/facet); composite emits one consolidated quote (130 + 8/facet).
- Pricing: Opus 4.7 list ($15/M input, $75/M output) per `token_estimator.MODEL_PRICING`.
