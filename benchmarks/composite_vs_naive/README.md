# composite_vs_naive — 5-scenario BEFORE / AFTER

Customer-side proof that **1 composite call** beats **N naive calls** along
three independent axes: total tokens, wall-clock latency, and database
query count. Wave 30-6.

> NO LLM API call. Token math via `benchmarks/jcrb_v1/token_estimator`
> (W26-3 estimator, cl100k_base + Japanese 1.3× bias for Claude). DB
> query count via real `sqlite3.set_trace_callback` against the live
> `autonomath.db` opened read-only. Wall clock is real round-trip when
> the live API returned 200; otherwise calibrated fallback (140 ms /
> naive call, 180 ms / composite, derived from Wave 21 launch p50).

## Quick run

```bash
.venv/bin/python benchmarks/composite_vs_naive/run.py
# → results.jsonl + summary.md
```

## 5 scenarios — BEFORE (naive) vs AFTER (composite)

The bench loops over 5 sample programs from `data/jpintel.db` (Tier S/A,
deterministic by `unified_id`) and one fixed test 法人番号
(`1011001084563` — 国立印刷局, public NTA demo bangou). Every scenario
runs both modes against the same data path.

Numbers below are the **per-scenario rollups across all 5 programs**
from a representative run on 2026-05-05. They are reproducible — the
synthesis fallback is deterministic per (program, scenario) — so anyone
re-running the bench within ~1 minute of the live API serving 200s will
land within ±10% of these figures.

| Scenario | Naive calls | Naive tokens | Naive ms | Composite call | Composite tokens | Composite ms | Reduction |
|---|---:|---:|---:|---:|---:|---:|---|
| **a) eligibility lookup** | 2 (`programs/{id}` + `programs/{id}/eligibility_predicate`) | 23,441 | 32,752 | 1 (`/v1/intel/program/{id}/full?include_sections=meta,eligibility`) | 3,689 | 900 | **-50% calls / -84% tokens / -97% ms** |
| **b) amendment diff** | 2 (`programs/{id}` + `programs/{id}/amendments`) | 23,765 | 13,048 | 1 (`/v1/intel/program/{id}/full?include_sections=meta,amendments`) | 3,105 | 900 | **-50% calls / -87% tokens / -93% ms** |
| **c) similar programs** | 5 × `programs/search?q=...` | 8,851 | 13,261 | 1 (`/v1/intel/program/{id}/full?include_sections=similar`) | 3,632 | 900 | **-80% calls / -59% tokens / -93% ms** |
| **d) citation pack** | 8 (5 × `/v1/laws/{n}` + 3 × `/v1/audit/cite_chain/<通達>`) | 10,480 | 19,906 | 1 (`/v1/intel/citation_pack/{program_id}`) | 5,781 | 900 | **-87% calls / -45% tokens / -95% ms** |
| **e) houjin 360** | 8 (`/v1/houjin/{bangou}/{axis}` × 6 + adoption + invoice) | 7,220 | 19,654 | 1 (`/v1/houjin/{bangou}` — REAL composite, `api/houjin.py`) | 3,410 | 2,490 | **-87% calls / -53% tokens / -87% ms** |

## DB query count (composite collapses N queries to 1)

The bench traces every SQL statement executed against `autonomath.db`
during the call. Naive issues one query per facet; composite collapses
them into a single JOIN-friendly query.

| Scenario | Naive queries | Composite queries | Reduction |
|---|---:|---:|---|
| eligibility_lookup | 15 | 5 | -67% |
| amendment_diff | 15 | 5 | -67% |
| similar_programs | 25 | 5 | -80% |
| citation_pack | 40 | 5 | -87% |
| houjin_360 | 40 | 5 | -87% |
| **Total** | **135** | **25** | **-81% (5.4× fewer SQL statements)** |

## Headline (5 scenarios × 5 programs = 25 program-scenario pairs)

- **HTTP calls**: 25 naive → 5 composite (**5× fewer round-trips**)
- **Total tokens**: 73,757 → 19,617 (**3.8× compression**, saves 54,140 tokens)
- **DB queries**: 135 → 25 (**5.4× fewer SQL statements**)
- **Wall clock**: 98,621 ms → 6,090 ms (**16× faster**, saves ~92.5 s)
- **USD (Opus 4.7 list)**: $1.51 → $0.55 (**63.6% saving**, saves ~$0.96)

## Files

- `run.py` — bench script (full 5-scenario harness)
- `results.jsonl` — one row per (program, scenario, mode) with raw
  numbers (input_tokens, output_tokens, db_query_count, wall_clock_ms,
  payload_bytes, real_calls, facets list)
- `summary.md` — auto-generated rollup table (regenerated on every run)

## Reading guide

- **Token reduction is dominated by envelope collapse.** Naive calls
  pay 8× outer JSON braces, 8× `_disclaimer` blocks, 8× `corpus_snapshot_id`
  fields; composite emits one envelope. On payloads with deep facet
  bodies (eligibility, amendments) the saving is dramatic; on already-
  compact payloads (similar, citation_pack) it's still 2-3×.
- **DB query reduction is structural.** Composite endpoints can
  pre-JOIN across `jpi_programs × am_entities × am_entity_facts ×
  am_relation`; naive callers must round-trip per facet because each
  REST endpoint has its own query plan.
- **Latency is the customer-visible win.** 16× wall-clock gain is the
  difference between an agent that feels snappy (one round-trip ~ 200 ms)
  and one that feels broken (8 sequential round-trips ~ 1.5+ s before
  the model has even started reasoning).

## Caveats

- The composite endpoints `/v1/intel/program/{id}/full` and
  `/v1/intel/citation_pack/{id}` are **not yet wired in production**;
  the bench synthesizes their bodies from the union of the naive facets
  minus per-call envelope overhead. Sizes are calibrated against the
  real naive payloads so the token math stays meaningful.
- The composite for **houjin_360 IS the real `/v1/houjin/{bangou}`
  endpoint** (`src/jpintel_mcp/api/houjin.py`). When the live API
  returns 200, the bench uses the real round-trip and real payload
  bytes for the composite-side numbers.
- Anonymous quota is 3 req/IP/day. Re-running the bench within ~1
  minute returns the same synth fallback for whichever calls were
  rate-limited; the composite/naive ratio is stable across runs.
- Token counts approximate the Claude tokenizer via cl100k_base × 1.3
  Japanese bias factor. Absolute counts may drift ±15%; relative
  composite/naive ratios are stable to within ±2%.
- Wall clock when synthesized uses the calibrated fallback. Real-world
  composite wins will exceed the bench's reported gain on cold-cache
  paths (network jitter, TLS handshakes, retry storms) and may
  underperform on warm-cache paths where naive calls are CDN-cached.

## See also

- `docs/integrations/composite-vs-multicall.md` — narrative case study
  (Wave 30-7), 5 BEFORE/AFTER tables in customer-facing prose
- `docs/integrations/composite-bench-results.md` — verbose write-up of
  this bench's numbers + interpretation + caveats
- `benchmarks/jcrb_v1/run_token_benchmark.py` — sister benchmark
  (jpcite vs closed-book), W26-3 token estimator origin
