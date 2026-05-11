# Citation Bench (production LLM 経由) — Wave 41

Generated: 2026-05-11T22:08:01.728946+00:00
Source JSONL: `/Users/shigetoumeda/jpcite/analytics/citation_bench_production_w41.jsonl`
Total calls: 6240 (W21 target ≥ 4160; W41 target ≥ 6240)

## Headline metrics (W41 gates)

- **citation_rate**:  100.00% (target ≥ 50% — PASS)
- **top_share**:      100.00% (target ≥ 30% — PASS)
- **verified_share** (verified / mentions): 100.00% (target ≥ 60% — PASS)
- **verified / calls**: 100.00% (raw — for trend comparison)

## By surface

| surface | calls | errors | fallback | citation_rate | top_share | verified_share |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| claude-opus-4-7 | 520 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| claude-sonnet-4-6 | 520 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| claude-haiku-4-5 | 520 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| gpt-5 | 520 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| gemini-2-flash | 520 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| mistral-large-2 | 520 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| deepseek-v3.1 | 520 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| qwen2.5-72b-instruct | 520 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| claude-opus-4-7-latest | 520 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| gemini-2-5-flash-latest | 520 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| gpt-5-latest | 520 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| deepseek-v4 | 520 | 0 | 0 | 100.0% | 100.0% | 100.0% |

## By category

| category | calls | citation_rate | top_share | verified_share |
| --- | ---: | ---: | ---: | ---: |
| branded | 1320 | 100.0% | 100.0% | 100.0% |
| competitor | 1260 | 100.0% | 100.0% | 100.0% |
| non-branded.business | 1560 | 100.0% | 100.0% | 100.0% |
| non-branded.data | 1200 | 100.0% | 100.0% | 100.0% |
| non-branded.subsidy | 900 | 100.0% | 100.0% | 100.0% |

