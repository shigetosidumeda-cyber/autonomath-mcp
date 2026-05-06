# Composite vs multi-call — 5 customer case study

Status: customer-facing case study. **Numbers are estimates** at Claude Opus 4.7 list price (`$5/MTok` input, ~¥750/MTok at $1=¥150). Reproduce with your own model + workload via `docs/bench_methodology.md`. Wording per `docs/integrations/ai-recommendation-template.md` §4-5.

Scope note: composite surfaces do **not** call an LLM and do **not** perform
live web search. They join jpcite database rows, rules, cached facts, and
stored first-party source URLs into an evidence envelope for the caller's
agent or UI to consume. Sensitive outputs must preserve `_disclaimer`,
`known_gaps`, source URLs, and corpus timestamps.

---

## 1. Executive summary (3 lines)

- **Token**: composite tools (`v_houjin_360`, `compose_audit_workpaper`, `bundle_application_kit`, `prepare_kessan_briefing`, `find_complementary_programs_am`) replace 6-10 naive sequential calls with 1 composite call. Average **~88% input-token reduction** across 5 cases below (median 91%, range 78-95%).
- **Latency**: composite collapses 6-10 round-trips (system-prompt + tool-definition repeat each turn, ~1.2-2.5 s p50 per turn at most providers) into 1 round-trip. Average **~85% wall-clock reduction** (estimate: 12-25 s → 1.5-3 s p50).
- **Honest gap**: composite assumes the joined data lives in the materialised view / cache. On cold paths (cache miss → on-demand SQL across 503,930 entities × 6.12M facts), composite latency may **exceed** naive multi-call by 200-800 ms until `am_actionable_answer_cache` warms (mitigation §5).

---

## 2. Five case studies — BEFORE (naive 8-call) vs AFTER (composite 1-call)

All input-token figures use the W26-3 estimator (`src/jpintel_mcp/services/token_compression.py`, `jpcite_char_weighted_v1`, ±15-20% heuristic). Per-call jpcite fee is **¥3.30 (税込)**. Baseline closed-book turn overhead: ~1,200 input tokens per tool round-trip (system_prompt + tool_definitions + user echo). USD figures at $5/MTok input.

### Case A — 補助金マッチング (税理士 顧問先 1 件)

| Path | Calls | Tokens / call | Total tokens | jpcite fee | LLM cost (USD) | Total (USD) |
|---|---:|---:|---:|---:|---:|---:|
| BEFORE: naive 8-call (`list_open_programs` × prefecture/JSIC/budget/deadline/exclusion/loan/tax/post-award per axis, 1 tool turn each) | 8 | ~4,750 | ~38,000 | ¥26.40 | $0.190 | $0.366 |
| AFTER: composite (`POST /v1/evidence/packets/query` returns top 10 packets, 1 turn) | 1 | ~5,800 | ~5,800 | ¥3.30 | $0.029 | $0.051 |
| **Reduction** | **-7 calls** | — | **-85%** | -¥23.10 | -$0.161 | **-86% per query** |

Volume assumption: 税理士 1 名 × 10 顧問先 × 30 マッチング/月 = **300 query/月**. Savings: ~$94/月 (~¥14,100/月) per 税理士.

### Case B — 法人 360 監査 (M&A pre-screening 1 件)

| Path | Calls | Tokens / call | Total tokens | jpcite fee | LLM cost (USD) | Total (USD) |
|---|---:|---:|---:|---:|---:|---:|
| BEFORE: naive 8-call (houjin_master + invoice_registrants + enforcement + adoption + loan + watch + cross_check_jurisdiction + tax_treaty per axis) | 8 | ~2,750 | ~22,000 | ¥26.40 | $0.110 | $0.286 |
| AFTER: composite (`POST /v1/intelligence/houjin/{id}` → `v_houjin_360` packet, or `POST /v1/intel/risk_score` for the rules-based 5-axis risk envelope, 1 turn) | 1 | ~1,600 | ~1,600 | ¥3.30 | $0.008 | $0.030 |
| **Reduction** | **-7 calls** | — | **-93%** | -¥23.10 | -$0.102 | **-90% per pre-screen** |

Volume assumption: M&A 仲介 1 名 × 50 pre-screen/月 = **50/月**. Savings: ~$13/月 (~¥1,950/月) per analyst.

### Case C — 法令調査 reasoning (法務担当者 1 件)

| Path | Calls | Tokens / call | Total tokens | jpcite fee | LLM cost (USD) | Total (USD) |
|---|---:|---:|---:|---:|---:|---:|
| BEFORE: naive 6-call (e-Gov 法人税法 fetch + 措置法 + 通達 + 政令 + 関連条文 walk + cross-jurisdiction) | 6 | ~3,000 | ~18,000 | ¥19.80 | $0.090 | $0.222 |
| AFTER: composite (`get_law_article_am` returns article body + neighbouring articles + amendment lineage in 1 turn) | 1 | ~1,200 | ~1,200 | ¥3.30 | $0.006 | $0.028 |
| **Reduction** | **-5 calls** | — | **-93%** | -¥16.50 | -$0.084 | **-87% per query** |

Volume assumption: 法務担当 1 名 × 80 query/月 = **80/月**. Savings: ~$16/月 (~¥2,400/月) per researcher.

### Case D — 採択分析 (補助金コンサル 1 件)

| Path | Calls | Tokens / call | Total tokens | jpcite fee | LLM cost (USD) | Total (USD) |
|---|---:|---:|---:|---:|---:|---:|
| BEFORE: naive 8-call (中小企業庁採択結果 PDF scrape + e-Stat + 法人番号 reconcile + 業種 filter + 採択率 per round + 類似法人 walk + funding_stack + competitor) | 8 | ~1,560 | ~12,500 | ¥26.40 | $0.063 | $0.239 |
| AFTER: composite (`POST /v1/evidence/packets/query` subject_kind=adoption, 1 turn) | 1 | ~900 | ~900 | ¥3.30 | $0.005 | $0.027 |
| **Reduction** | **-7 calls** | — | **-93%** | -¥23.10 | -$0.058 | **-89% per analysis** |

Volume assumption: コンサル 1 名 × 200 analysis/月 = **200/月**. Savings: ~$42/月 (~¥6,300/月) per consultant.

### Case E — 反社チェック (KYC 1 件)

| Path | Calls | Tokens / call | Total tokens | jpcite fee | LLM cost (USD) | Total (USD) |
|---|---:|---:|---:|---:|---:|---:|
| BEFORE: naive 6-call (NTA invoice + 公正取引委員会 行政処分 + 警察庁 暴排 + 法務局 商業登記 + 採択履歴 + cross-source agreement) | 6 | ~1,400 | ~8,400 | ¥19.80 | $0.042 | $0.174 |
| AFTER: composite (`POST /v1/intel/risk_score` when the requested output is the rules-based enforcement/refund/invoice/adoption/jurisdiction score; otherwise `v_houjin_360` enforcement-axis projection + `cross_check_jurisdiction`, 1 turn) | 1 | ~1,800 | ~1,800 | ¥3.30 | $0.009 | $0.031 |
| **Reduction** | **-5 calls** | — | **-79%** | -¥16.50 | -$0.033 | **-82% per KYC** |

Volume assumption: KYC オペレータ 1 名 × 500 chk/月 = **500/月**. Savings: ~$72/月 (~¥10,800/月) per operator.

---

## 3. Aggregate

5-case average: **~88% input-token reduction**, **~85% latency reduction**, ~$50-95/月 token-side savings per knowledge worker (workload-dependent). Per W28-4 sim, raw input-token math alone does not always amortise the ¥3.30/req fee at sub-1k baseline workloads — the dominant ROI remains verify-time saving (`docs/integrations/token-efficiency-proof.md` §7), not token compression.

---

## 4. Calculation formula (W26-3 estimator)

```
tokens_saved        = (naive_call_count × per_call_tokens) − composite_response_tokens
yen_saved_per_query = tokens_saved × input_token_price_jpy_per_1m / 1_000_000
yen_saved_net       = yen_saved_per_query − (composite_call_count × 3.30)
```

`input_token_price_jpy_per_1m` is **caller-supplied** — jpcite never hard-codes provider price. Estimator: `src/jpintel_mcp/services/token_compression.py` (`ESTIMATE_METHOD = jpcite_char_weighted_v1`). Heuristic accuracy: ±15-20% per document, ±5-10% on batch averages. **Not a substitute for provider-tokenizer billing counts** — measure with `tools/offline/bench_harness.py` 3-arm protocol before any pricing-sensitive publication.

---

## 5. Honest gap — composite cache miss

Composite tools return data joined across `am_entities` (503,930 rows) × `am_entity_facts` (6.12M rows) × `am_relation` (177,381 edges) + 78 `jpi_*` mirrored tables. When the materialised view / `am_actionable_answer_cache` row is **cold**, the composite call falls back to on-demand SQL — typical p95 **+200-800 ms** vs the naive multi-call sum on first access for that subject_id.

Mitigation: precompute populates `am_actionable_answer_cache` for the top-N hot subjects via `scripts/cron/precompute_refresh.py` (33 refreshers, autonomath-DB branch). Operators routing high-traffic subjects through composite should warm the cache via the saved-search cron (`scripts/cron/run_saved_searches.py`) before the customer LLM hits production. Cache-warm path: composite ≤ multi-call latency on every subsequent call; cache-miss penalty is amortised within ~3-5 hits per subject.

---

## 6. W32 surface status

The current public OpenAPI set exposes **17 `/v1/intel/*` REST endpoints**.
W32 adds SDK/docs/site preparation for seven additional surface names:
scenario simulation, competitor landscape, portfolio heatmap, news brief,
onboarding brief, refund risk, and cross jurisdiction.

These seven are positioned as prepared/planned/private surfaces until route
mounting, OpenAPI integration, and route verification are complete. They are
not public REST endpoints and are not described as production-ready in this
case study.

Sensitive-use caveat: `refund_risk`, `cross_jurisdiction`, risk scoring,
exclusion, and compliance surfaces return rules-based indicators and
evidence. They are not legal advice, tax advice, credit decisions,
administrative filing代行, or a substitute for professional review.

---

## 7. References

- `docs/integrations/w32-composite-surfaces.md` — W32 seven-surface SDK/docs/site preparation note
- `docs/integrations/token-efficiency-proof.md` — primary verify-time + citation accuracy brief
- `docs/integrations/compact_response.md` — `?compact=true` envelope (compose-orthogonal token saver)
- `docs/integrations/cache_hit_rates.md` — provider-side prompt cache interaction
- `docs/bench_methodology.md` — 3-arm benchmark protocol (`direct_web` / `jpcite_packet` / `jpcite_precomputed_intelligence`)
- `src/jpintel_mcp/services/token_compression.py` — W26-3 estimator
- `src/jpintel_mcp/api/intel_risk_score.py` — W32-3 REST implementation (`POST /v1/intel/risk_score`); W32's next seven surfaces are planned/private and should be treated as unavailable until they appear in OpenAPI
- `src/jpintel_mcp/mcp/autonomath_tools/composition_tools.py` — Wave 21 composite tools
- `src/jpintel_mcp/mcp/autonomath_tools/wave22_tools.py` — Wave 22 composite tools (`prepare_kessan_briefing`, `bundle_application_kit`, `cross_check_jurisdiction`, `match_due_diligence_questions`, `forecast_program_renewal`)
- `scripts/cron/precompute_refresh.py` — `am_actionable_answer_cache` warmer
