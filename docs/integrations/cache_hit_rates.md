# Cache Hit Rate Measurement

Measured 2026-05-05 against `autonomath.db` (12 GB, 503,930 entities). 1000-query Monte Carlo simulation, seed=42.

## Coverage

| Cache | Rows | Universe | Coverage |
|---|---:|---:|---:|
| `am_program_narrative_full` | 1 | 8,203 programs (`am_entities` kind=program) | 0.012% |
| `am_program_eligibility_predicate_json` | 12,753 | 12,753 UNI-* programs (own universe) | 100.00% |
| `am_entity_density_score` | 503,930 | 503,930 entities | 100.00% (275,611 with score>0 = 54.7%) |
| `am_entity_pagerank` | 503,930 | 503,930 entities | 100.00% (all score>0) |
| `am_entities_vec_l2v2_map` | 215,233 | 503,930 entities | 42.71% |

Vec internal buckets (rowid counts): A=201,845 / C=2,286 / J=2,065 / K=137 / L=7,360 / S=11,601 / T=1,984 = 227,278 (note: counts > distinct canonicals because adoption rows can map to multiple JSIC bucket prefixes).

## 1000-Query Random Hit Rate

| Cache | Hit% (random entity) | Hit% (within own scope) | Target 80%+ | Gap |
|---|---:|---:|---|---:|
| narrative_full | 0.00% | 0.00% (1/8,203) | NO | -80 pp |
| eligibility_predicate_json | 100.00% | 100.00% | YES | +20 pp |
| density_score | 100.00% | 100.00% | YES | +20 pp |
| pagerank | 100.00% | 100.00% | YES | +20 pp |
| vec_* (l2v2) | 44.40% | adoption=100%, others=0% | NO | -36 pp |

1-sample probe: predicate_json HIT, density HIT, pagerank HIT, narrative_full MISS, vec MISS (random non-adoption entity).

## Cache-Miss Token Cost

Estimated extra tokens per miss (re-derive on demand vs. table read):

- `narrative_full` miss: ~3,000-8,000 tokens (LLM narrative regeneration). Currently 8,202 of 8,203 program calls miss. **Worst offender.**
- `predicate_json` miss: N/A (rule-based extraction, ~50 tokens). Risk negligible.
- `density_score` miss: ~200 tokens (graph aggregation SQL re-run). All hit -> 0 cost.
- `pagerank` miss: ~500 tokens (PageRank batch is offline, hot path is read-only). All hit -> 0 cost.
- `vec` miss: ~1,500 tokens per entity for re-embedding fall-through. 56% of random queries miss (statistic/program/corporate_entity = 0% covered).

## Recommendation / Gap Closure

1. **W26-5 narrative ACTUAL run** (not smoke) is the single biggest token-saving win: 8,202 missing program narratives x ~5k tokens/miss = ~41M tokens saved per full agent sweep. Move narrative_full from 1 row to >=6,500 rows (>=80%).
2. **Vec backfill beyond `adoption`**: extend l2v2 embedding to `program`, `enforcement`, `statistic`, `corporate_entity` to push canonical-level coverage from 42.71% to >=80%. Current 0% for non-adoption kinds is the second-largest token leak.
3. predicate_json / density / pagerank are at the 80%+ target; no action.
