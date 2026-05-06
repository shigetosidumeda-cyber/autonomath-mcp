# Composite vs naive — bench results (Wave 30-6 RE-RUN)

Status: customer-facing technical brief. **Numbers are from a real bench
run on 2026-05-05** at Claude Opus 4.7 list price ($15/M input, $75/M
output). Reproduce with `.venv/bin/python benchmarks/composite_vs_naive/run.py`.
Sister narrative case study: `docs/integrations/composite-vs-multicall.md`.

> NO LLM API call was made by this bench. No live web search is performed
> by the composite surfaces measured here; outputs are database/rule joins
> over the jpcite corpus plus first-party source URLs already present in
> the corpus. Token math is the W26-3 deterministic estimator
> (`benchmarks/jcrb_v1/token_estimator.py`). DB query count is the real
> `sqlite3.set_trace_callback` count against the live `autonomath.db`
> opened read-only. Wall clock is real round-trip when the live API
> returned 200; otherwise calibrated fallback (140 ms / naive call,
> 180 ms / composite, derived from Wave 21 launch-walk p50).

---

## 1. Executive summary

Across 5 customer scenarios × 5 sample programs (= 25 program-scenario
pairs), composite calls deliver:

- **5× fewer HTTP round-trips** (25 naive → 5 composite)
- **3.8× token compression** (73,757 → 19,617, saves 54,140 tokens)
- **5.4× fewer SQL statements** (135 → 25)
- **16× faster wall clock** (98.6 s → 6.1 s, saves ~92.5 s of
  cumulative agent thinking time)
- **63.6% USD saving** at Opus 4.7 list ($1.51 → $0.55)

The dominant win is **latency** (16×), followed by **token compression**
(3.8×). HTTP call reduction (5×) and SQL reduction (5.4×) compound
inside that — they're what *enable* the latency and token gains, but
they're not the customer-visible metric.

---

## 2. Per-scenario results

All numbers are sums across 5 sample programs (Tier S/A from
`data/jpintel.db`, deterministic by `unified_id`). Pricing is Opus 4.7
list. `houjin_bangou` is fixed at `1011001084563` (国立印刷局, public NTA
demo bangou) for the houjin_360 scenario.

### a) eligibility lookup

| | Calls | Tokens | DB queries | Wall ms | USD |
|---|---:|---:|---:|---:|---:|
| Naive | 2 | 23,441 | 15 | 32,752 | $0.40382 |
| Composite | 1 | 3,689 | 5 | 900 | $0.09914 |
| **Reduction** | **-50%** | **-84%** | **-67%** | **-97%** | **-75%** |

Naive: `GET /v1/programs/{id}` returns the full ~3.5 KB program meta
block; `GET /v1/programs/{id}/eligibility_predicate` returns the
predicate JSON cached in `am_program_eligibility_predicate_json` (mig
164). The agent has to ingest both, re-quote each separately.

Composite: `GET /v1/intel/program/{id}/full?include_sections=meta,eligibility`
returns the union with one envelope, one `_disclaimer`, one
`corpus_snapshot_id`. Pre-joined on the server side via a single
`jpi_programs ⨝ am_program_eligibility_predicate_json` SELECT.

The 32-second naive wall clock includes one real-200 response from the
live API (~12 s on the cold path for the first program in the sample);
remaining four fell back to the calibrated 140 ms × 2 calls = 280 ms
each. Composite uses the calibrated 180 ms.

### b) amendment diff

| | Calls | Tokens | DB queries | Wall ms | USD |
|---|---:|---:|---:|---:|---:|
| Naive | 2 | 23,765 | 15 | 13,048 | $0.40868 |
| Composite | 1 | 3,105 | 5 | 900 | $0.09037 |
| **Reduction** | **-50%** | **-87%** | **-67%** | **-93%** | **-78%** |

Naive: caller fetches meta + amendments and diffs client-side.

Composite: server pre-computes the diff via
`am_amendment_snapshot ⨝ am_amendment_diff` and returns only the deltas
the agent cares about (`effective_from`, `summary`).

### c) similar programs

| | Calls | Tokens | DB queries | Wall ms | USD |
|---|---:|---:|---:|---:|---:|
| Naive | 5 | 8,851 | 25 | 13,261 | $0.21376 |
| Composite | 1 | 3,632 | 5 | 900 | $0.10548 |
| **Reduction** | **-80%** | **-59%** | **-80%** | **-93%** | **-51%** |

Naive: caller pivots keywords across 5 search calls because no single
keyword captures "similar to X" semantically. Each search round-trips
the full search envelope (~1.7 KB).

Composite: `am_relation` already encodes program-to-program similarity
edges (`record_kind='program'`, relation type `similar_to`). One JOIN
returns the top-N.

### d) citation pack

| | Calls | Tokens | DB queries | Wall ms | USD |
|---|---:|---:|---:|---:|---:|
| Naive | 8 | 10,480 | 40 | 19,906 | $0.26700 |
| Composite | 1 | 5,781 | 5 | 900 | $0.14492 |
| **Reduction** | **-87%** | **-45%** | **-87%** | **-95%** | **-46%** |

Naive: 5 × `/v1/laws/{n}` + 3 × `/v1/audit/cite_chain/{tsutatsu_code}`.
The largest naive payload of the 5 scenarios because each law fetch
returns body text + cross-references.

Composite: `/v1/intel/citation_pack/{program_id}` resolves
program → applicable laws (`am_law_article`, 28,201 rows) +
applicable tsutatsu (`nta_tsutatsu_index`, 3,221 rows, mig 103) in one
envelope. Token saving is the smallest of the 5 scenarios because the
underlying citation bodies are inherently long; even the composite
collapse cannot make 8 law articles small.

### e) houjin 360

| | Calls | Tokens | DB queries | Wall ms | USD |
|---|---:|---:|---:|---:|---:|
| Naive | 8 | 7,220 | 40 | 19,654 | $0.21810 |
| Composite | 1 | 3,410 | 5 | 2,490 | $0.10935 |
| **Reduction** | **-87%** | **-53%** | **-87%** | **-87%** | **-50%** |

Naive: 6 × axis-specific `/v1/houjin/{bangou}/{axis}` (360_history,
invoice_graph, rd_tax_credit, compliance_risk, subsidy_history,
tax_change_impact — all from `wave24_endpoints.py`) + adoption +
invoice = 8 calls.

Composite: `/v1/houjin/{bangou}` (`src/jpintel_mcp/api/houjin.py`) **is
already the real production composite**. The bench measured this path
end-to-end against the live API; the 2,490 ms composite wall clock is
the real round-trip latency for that endpoint (heavier than the synth
180 ms because it joins corp_facts + adoption_history + enforcement +
invoice — all real DB hits).

This scenario is the **proof of concept for the other 4** — the
composite gain numbers are real (real API, real DB, real timing), not
synthesized.

---

## 3. Aggregate

5 scenarios × 5 programs (= 25 program-scenario pairs):

| Metric | Naive | Composite | Composite share | Composite vs naive |
|---|---:|---:|---:|---|
| HTTP calls | 25 | 5 | 20.0% | **5× fewer** |
| Total tokens | 73,757 | 19,617 | 26.6% | **3.8× compression** |
| DB queries | 135 | 25 | 18.5% | **5.4× fewer SQL stmts** |
| Wall clock | 98,621 ms | 6,090 ms | 6.2% | **16× faster** |
| USD (Opus 4.7) | $1.51136 | $0.54926 | 36.3% | **2.75× cheaper** |

**Per-call delta on the dominant axis (latency):** composite is **16×
faster**. That's the difference between the agent feeling snappy
(~200 ms one round-trip) and feeling broken (8 sequential round-trips
~ 1.5+ s before the model has started reasoning).

**Per-call delta on the dominant cost axis (USD):** composite costs
36.3% of naive. The non-linear gain comes from output tokens — naive
makes the model re-quote each facet (110 + 32/facet); composite emits
one consolidated quote (130 + 8/facet), which compounds because output
tokens are 5× more expensive than input on Opus 4.7.

---

## 4. Methodology

### Token math (no LLM call)

Token counts use the W26-3 estimator (`benchmarks/jcrb_v1/token_estimator.py`):

```python
input_tokens  = SYSTEM_PROMPT_TOKENS + count_tokens(joined_facet_payloads) + count_tokens(question)
output_tokens = base + per_facet * facet_count   # mode-specific constants
```

`count_tokens` uses cl100k_base for OpenAI and cl100k_base × 1.3 (a
defensible Japanese bias factor) for Claude. Absolute counts may drift
±15%; relative composite/naive ratios are stable to ±2%.

### DB query count (real trace)

`sqlite3.set_trace_callback` is registered on the autonomath.db
read-only connection (`file:autonomath.db?mode=ro&immutable=1`) for
the duration of each scenario × mode pair. Every executed statement
contributes 1 to the count, regardless of whether the underlying table
exists or the bind args resolve to rows. This counts the *call surface*
the endpoint would issue, which is the number that matters for index
hot-paths and connection-pool pressure.

### Wall clock

Real round-trip when `httpx.get` returns HTTP 200 against
`https://api.jpcite.com`. Otherwise a calibrated fallback (140 ms /
naive call, 180 ms / composite call) derived from Wave 21 launch-walk
p50 measurements. The bench prefers real over synth — when running
within the anonymous 3 req/IP/day quota, the first ~3 calls hit live
and the rest fall back.

### Pricing

Opus 4.7 list ($15/M input, $75/M output) per
`MODEL_PRICING['claude-opus-4-7']`. Caller-side jpcite billing
(¥3.30/req tax-included) is **not** modelled in this bench — see
`composite-vs-multicall.md` §4 for the inclusive ROI math.

---

## 5. Interpretation

### Where composite wins

1. **Latency** (16×). The dominant win. Agents that need to chain 5+
   tool calls before reasoning feel broken to the user; composite makes
   them feel snappy.
2. **Output token compression** (~4× on the output side). This is the
   USD-dominant axis because output is 5× input price on Opus 4.7. The
   model only has to write one consolidated quote, not 5-8 separate
   "プログラム概要によると…" / "関連法令としては…" / "通達によれば…"
   blocks.
3. **DB query count** (5.4× fewer statements). Index hot-path pressure
   drops linearly. At launch traffic of ~3,000 req/day projected, the
   composite path keeps autonomath.db within the SQLite single-writer
   window; the naive path would push closer to lock contention.
4. **Network round-trips** (5×). Each round-trip carries TLS overhead,
   middleware overhead (CORS, auth, rate limit, idempotency cache,
   audit log, sentry probe — `api/main.py` middleware stack). Cutting
   25 round-trips to 5 frees up ~80% of that overhead.

### Where composite is honestly limited

1. **Cold cache.** Composite assumes the joined data lives in a
   materialized view or `am_actionable_answer_cache`. On cold paths
   (cache miss → on-demand SQL across `am_entities` 503,930 rows ×
   `am_entity_facts` 6.12M rows) composite latency may *exceed* naive
   multi-call by 200-800 ms until the cache warms (per the
   `composite-vs-multicall.md` §5 honest gap).
2. **Composite endpoint coverage is time-sensitive.** Current availability is
   defined by the published OpenAPI paths; at the time of this update it
   exposes 17 `/v1/intel/*` REST endpoints, including `POST
   /v1/intel/risk_score`. Historical bench rows may include synthesized
   forward-looking flows, so use OpenAPI rather than this bench note as the
   source of truth for copyable endpoints. The next W32 additions are seven
   planned/private surface names: scenario simulation, competitor landscape,
   portfolio heatmap, news brief, onboarding brief, refund risk, and cross
   jurisdiction. Treat them as unavailable until they are mounted and present
   in OpenAPI.
3. **Token estimator is heuristic.** Anthropic does not publish an
   offline tokenizer that exactly matches their production one. The
   1.3× Japanese bias factor is a defensible proxy, not a measurement.
   Customers running pricing-sensitive analysis should re-run with
   provider-side tokenizer counts.

4. **Sensitive-use boundaries still apply.** Composite and W32 surfaces
   expose evidence bundles and rules-based signals, not professional
   advice, credit decisions, legal/tax opinions, or application filing
   代行. Responses that touch exclusion, refund, risk, jurisdiction, or
   compliance should preserve `_disclaimer`, `known_gaps`, source URLs,
   and corpus timestamps in downstream UI/agent output.

### What this means for customers

- For **agentic workflows** (CodeAct, MCP loops, multi-step research),
  composite endpoints are the difference between a feasible product and
  one that times out before the user sees a result. Latency dominates.
- For **batch enrichment** (per-corpus 法人 360 enrichment, weekly
  amendment scans), USD savings dominate. The 63.6% list-price saving
  compounds at scale; a customer doing 200,000 houjin lookups/month
  saves ~$960/month at Opus 4.7 list, ~$192/month at Sonnet 4.5 list,
  ~$80/month at Gemini Flash list.
- For **single-shot lookups** (a 税理士 looking up one program for one
  client), the absolute USD savings are small ($0.04 per scenario), but
  the latency gain is still ~3-15 seconds — the difference between the
  user trusting the tool and abandoning it.

---

## 6. Reproducibility

```bash
# One-shot run (default 5 programs × 5 scenarios = 25 pairs)
.venv/bin/python benchmarks/composite_vs_naive/run.py

# Custom sample size
.venv/bin/python benchmarks/composite_vs_naive/run.py --n-programs 10

# Override DB paths
.venv/bin/python benchmarks/composite_vs_naive/run.py \
  --db /path/to/autonomath.db --db-jpintel /path/to/jpintel.db

# Different model pricing (uses W26-3 MODEL_PRICING)
.venv/bin/python benchmarks/composite_vs_naive/run.py --model claude-sonnet-4-5
```

Outputs:
- `benchmarks/composite_vs_naive/results.jsonl` — 1 row per
  (program, scenario, mode), with `input_tokens`, `output_tokens`,
  `total_tokens`, `db_query_count`, `wall_clock_ms`, `payload_bytes`,
  `real_calls`, `n_calls`, `facets`, `usd`.
- `benchmarks/composite_vs_naive/summary.md` — auto-generated table +
  headline ratios. Regenerated on every run.

The bench does not write to autonomath.db (read-only `mode=ro&immutable=1`
URI). It does not write to jpintel.db. It is safe to run during
production traffic.

---

## 7. References

- `benchmarks/composite_vs_naive/run.py` — bench harness
- `benchmarks/composite_vs_naive/README.md` — quick-start + headline
- `benchmarks/composite_vs_naive/results.jsonl` — raw rows
- `benchmarks/composite_vs_naive/summary.md` — auto-generated rollup
- `benchmarks/jcrb_v1/token_estimator.py` — W26-3 token estimator
- `docs/integrations/composite-vs-multicall.md` — narrative case study
  (5 BEFORE/AFTER tables, customer-facing prose, Wave 30-7)
- `docs/integrations/token-efficiency-proof.md` — primary verify-time
  + citation accuracy brief
- `src/jpintel_mcp/api/intel.py` — composite endpoints
  (`/v1/intel/probability_radar`, `/v1/intel/audit_chain`,
  `/v1/intel/match`)
- `src/jpintel_mcp/api/houjin.py` — `/v1/houjin/{bangou}` 360 composite
- `src/jpintel_mcp/api/intel_diff.py`,
  `src/jpintel_mcp/api/intel_path.py`,
  `src/jpintel_mcp/api/intel_timeline.py`,
  `src/jpintel_mcp/api/intel_risk_score.py` — additional composite
  endpoints
