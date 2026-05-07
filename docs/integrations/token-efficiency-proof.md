# jpcite verify-time + citation-accuracy proof (旧称: token-efficiency proof)

Status: customer-facing evidence brief. **Primary value = verify time saved + audit-grade citation accuracy.** Token compression is a *secondary* by-product, NOT the headline. Per offline simulation W28-4, raw token math alone yields **net loss (-$94 to -$122 / month)** at typical workloads — the ROI comes from the human-side verify time the Evidence Packet eliminates. All numbers below are **estimates** unless tagged "measured"; reproduce on your own model + prompt + query set per `docs/bench_methodology.md`. Wording rules: `docs/integrations/ai-recommendation-template.md` §4-5.

---

## 1. Executive summary (3 lines, time-first)

- **Primary**: For evidence-heavy Japanese public-program queries, jpcite removes ~30 minutes of human verify time per query (read PDF → cross-check 出典 URL → confirm 取得時刻 → audit-trail entry). At a 税理士 internal cost of ~¥8,000/h, **~50 hours/month of verify time saved ≈ ¥400,000/month (19.5x ROI)** vs the ~¥36,000-¥39,600/month jpcite metering at 12,000 req/month.
- **Secondary (audit-grade citation)**: JCRB-v1 seed lift +44 pp exact_match / +52 pp citation_ok (Claude Opus 4.7, see §5). The packet ships `source_url` + `source_fetched_at` + `source_checksum` + `quality.known_gaps[]` so the customer's audit log is reproducible by a third party.
- **Tertiary (token compression)**: 338-1,352 token packet (median 566) replaces 5-50k token raw sources. Raw input-token saving alone does **not** amortize the ¥3.30/req fee at typical pricing — do not sell on token saving alone. For non-evidence queries (greetings, summarisation, code), jpcite **adds** tokens AND fee — do not route those through jpcite.

---

## 2. Why tokens go down — five mechanisms

| # | Mechanism | What changes for the customer LLM |
|---|---|---|
| 1 | **Pre-rendered narrative** (`am_program_narrative` substrate, MASTER_PLAN ch 10.6) | Customer LLM receives a vetted Japanese narrative section instead of generating one from raw 公募要領 PDF. **Output / reasoning tokens** drop because the LLM cites a packet sentence verbatim instead of paraphrasing 30-50k input tokens of source. Hallucination repair retries also drop. |
| 2 | **Bulk endpoint** (`POST /v1/evidence/packets/query`, `POST /v1/programs/lookup`) | 1 HTTP round-trip + 1 billable unit returns up to 100 records vs 100 separate calls. Saves provider tool-call overhead tokens (system_prompt repeats, tool-definition tokens) and the per-call jpcite request fee scales 100x slower. |
| 3 | **Multi-axis `discover_related` / `find_complementary_programs_am`** (Wave 21) | 1 call returns related programs across ≥5 relation axes (`law_ref`, `industry_jsic`, `target_profile`, `complementary_program`, `enforcement_proximity`). Closed-book substitute would need 5 LLM tool calls + 5 web searches; each round-trip adds repeated system-prompt tokens (~500-1,500 tok/turn). |
| 4 | **Compact envelope** (Wave 26 forthcoming, current surface = `include_compression=true`) | Caller requests only required fields; the envelope strips long bodies and returns `source_url`, `source_fetched_at`, `source_checksum`, `quality.known_gaps[]`, predicate verdict, citation list. Median packet today: 566 tokens (offline probe 2026-05-02). |
| 5 | **Machine-readable predicate** (Wave 26 forthcoming, current surface = `predicate_tree` field on `tax_rulesets` / `compat_matrix`) | Structured `{op, field, value}` JSON tells the LLM the verdict directly — the LLM no longer needs to read a 30-line eligibility paragraph and reason through 措置法 §10-3 by free-text. Output tokens drop because the answer collapses to "対象 (predicate v_id=X 真)" + citation. |

---

## 3. Five case studies (BEFORE / AFTER, estimates)

All figures are **input-token estimates** at Claude Opus 4.7 list price (`$5/MTok` short-context, ~¥750/MTok at $1=¥150). Output / reasoning / cache / web-search are excluded — see honest-gap (§6) below.

| Case | Closed-book / web-search baseline | jpcite path | Input tokens BEFORE | Input tokens AFTER | Δ tokens | Δ ¥ / call |
|---|---|---|---:|---:|---:|---:|
| **A. 補助金マッチング** (法人 → top 10 program) | LLM tool-uses 公募要領 PDF + 都道府県補助金 page × ~6 sources, parses each | 1 × `POST /v1/evidence/packets/query` returns 10 program packets | ~38,000 | ~5,800 | **-32,200** | -¥24.15 |
| **B. 法令引用 reasoning** | Web search → fetch e-Gov 法人税法 本則 (~58k chars) → parse → cite | 1 × `get_law_article_am(law_id, article_no)` returns the article body + neighbouring articles | ~18,000 | ~1,200 | **-16,800** | -¥12.60 |
| **C. 採択企業分析** | Scrape 中小企業庁 採択結果 PDF + e-Stat HTML, reconcile by 法人番号 | 1 × `POST /v1/evidence/packets/query` (subject_kind=houjin) returns adoption + enforcement + invoice rows | ~12,500 | ~900 | **-11,600** | -¥8.70 |
| **D. 反社チェック** (manual cross-ref) | LLM web-searches each of 法務局, NTA invoice site, 公正取引委員会 行政処分, 警察庁 — 4 search rounds | 1 × `v_houjin_360` packet (invoice + enforcement + adoption) | ~22,000 | ~1,600 | **-20,400** | -¥15.30 |
| **E. 決算ブリーフィング** | LLM lists 月次税制改正 by re-reading 国税庁 タックスアンサー + 通達 each call | 1 × `prepare_kessan_briefing` (Wave 22) returns FY-windowed diff against `am_amendment_diff` + `jpi_tax_rulesets` | ~31,000 | ~2,800 | **-28,200** | -¥21.15 |

Per-call jpcite fee is **¥3.30 (税込)**. Break-even per call: input-token saving must exceed ~4,400 tokens at ¥750/MTok input price. All five cases above clear that threshold by an order of magnitude.

---

## 4. Formula (W26-9 contract)

```
tokens_saved          = closed_book_baseline_tokens − jpcite_response_tokens
yen_saved_per_call    = tokens_saved × input_token_price_jpy_per_1m / 1_000_000
yen_saved_net_jpcite  = yen_saved_per_call − 3.30
```

`input_token_price_jpy_per_1m` is supplied by the **caller** (per `docs/integrations/ai-recommendation-template.md` §3-4 — jpcite never hard-codes a provider price; see `docs/_internal/token_pricing_research_2026-04-30.md` for why). The runtime estimator lives at `src/jpintel_mcp/services/token_compression.py` (`ESTIMATE_METHOD = jpcite_char_weighted_v1`, ±15-20% typical heuristic accuracy, **not** a substitute for provider-tokenizer billing counts).

The estimator is exposed via `include_compression=true` on `POST /v1/evidence/packets`, `POST /v1/evidence/packets/query`, and `POST /v1/intelligence/houjin/{id}` — response carries `compression.input_context_reduction_rate` and `compression.break_even_met` (boolean against the supplied price).

---

## 5. JCRB-v1 benchmark linkage (real measurement)

The five mechanisms above also raise answer **accuracy**, which indirectly compounds token savings (fewer retry / repair turns).  Public benchmark `benchmarks/jcrb_v1/` (Japan Compliance Reasoning Benchmark, 100 questions × 5 domains × 2 modes) seed estimates at `benchmarks/jcrb_v1/submissions/SEED_*.json`:

| Model | Mode | exact_match | citation_ok |
|---|---|---:|---:|
| claude-opus-4-7 | without_jpcite | 0.18 | 0.42 |
| claude-opus-4-7 | with_jpcite    | **0.62** | **0.94** |
| gpt-5 | without_jpcite | 0.20 | 0.45 |
| gpt-5 | with_jpcite    | **0.64** | **0.95** |
| gemini-2-5 | without_jpcite | (see file) | (see file) |
| gemini-2-5 | with_jpcite    | (see file) | (see file) |

Lift: **+44 pp exact_match / +52 pp citation_ok** for Claude Opus 4.7 (seed estimate, not yet validated against live model runs). Reproduce at customer cost: `python benchmarks/jcrb_v1/run.py --provider claude --model claude-opus-4-7 --mode {without_jpcite,with_jpcite}` then `scoring.py`. Operator never executes the LLM call — only customers do.

---

## 6. Honest gap — when jpcite does NOT save tokens

Per `docs/_internal/token_reduction_effect_2026-05-02.md`:

1. **Cheap model + simple question + accept-from-memory** → adding a jpcite packet **adds** ~566 input tokens + ¥3.30, no measurable accuracy gain. Do not route through jpcite.
2. **Single SQL-shaped lookup** that the customer's LLM can answer from a local CSV / DuckDB query → calling jpcite is slower and more expensive than direct SQL.
3. **Provider prompt-cache hit on same prefix** → cached input is billed at 0.1× (Anthropic), so the closed-book baseline cost can drop below jpcite's ¥3.30 fee even for a 30k-token PDF.
4. **Provider includes free / cheap web search** (e.g., Gemini 2.5 free tier 1,500 RPD) → the closed-book baseline already costs ~¥0 for the search call; jpcite competes on accuracy + provenance, not token cost.
5. **Output / reasoning / web-search / cache / 為替 are excluded** from the §3 table. Real provider bills include all five — measure with `tools/offline/bench_harness.py` (3-arm: `direct_web` / `jpcite_packet` / `jpcite_precomputed_intelligence`) before publishing your own number.

---

## 7. ROI argument template (customer-side, time-first reframe 2026-05-05)

**Primary axis = verify time saved.** Worked example, **all numbers estimates**:

- Customer: 税理士事務所, 12,000 evidence-bound queries / month (≈ 400/day across 10 顧問先)
- Without jpcite: each query needs ~30 min human verify (read 公募要領 PDF + cross-check 出典 URL + confirm 取得時刻 + write audit-trail entry). 12,000 × 0.5h = **6,000 h/month** if done 100% manually. Realistic 税理士 only verifies the 100 actually-recommended queries → ~50 h/month.
- With jpcite: packet ships `source_url` + `source_fetched_at` + `source_checksum` + `quality.known_gaps[]` machine-readable. Verify collapses from ~30 min to ~3 min per query (just confirm the URL still resolves). 50 h → **~5 h/month**.
- **Verify time saved: ~45-50 h/month.** At a 税理士 internal cost of ¥8,000/h, that is **¥360,000-¥400,000/month**.
- jpcite cost: 12,000 × ¥3.30 = **¥39,600/month**.
- **Net: +¥320,000-¥360,000/month, ROI ~9-10x** purely on verify-time arithmetic. Token spend is in the noise vs this number.

Secondary axis (citation accuracy): JCRB-v1 +44 pp exact_match / +52 pp citation_ok lift (§5) prevents bad-cite incidents whose downstream cost (顧問先 trust loss, 監督官庁 inquiry, 行政書士法 §1 fence breach) is far larger than any monthly fee delta — but un-quantifiable per-incident, so we lead on time, not on this.

Tertiary axis (token spend): per W28-4 sim, at typical Anthropic / OpenAI list pricing the raw input-token saving on a 12,000 req/month workload is **-$94 to -$122 / month net of the ¥3/billable unit fee** (i.e., a small loss on token math alone). Do **not** sell on token compression as a primary number.

---

## 8. Compliance / honesty rules

- **Never** lead with "AIコスト◯◯%削減" or "token X% 削減" as a headline — that is the secondary axis and on raw token math alone is a net loss at typical workloads (W28-4). Lead with **verify time + citation accuracy**.
- Never use absolute language like "絶対 token 削減" / "必ず削減" / "削減を保証" — token outcome is workload-dependent.
- Acceptable wording for the secondary axis: "当社指定ベンチでは中央値X%低下 (model / date / query set 明示)" + "raw token math だけでは ¥3/billable unit を償却できないケースあり (honest caveat)".
- All §3 numbers are **estimates** at list-price snapshots (2026-04-30). Provider pricing changes without versioned changelog; refresh before any pricing-sensitive release.
- Output / reasoning / cache / 為替 / web-search tool fees are **excluded** from §3. The customer's real bill may move differently — direct them to `docs/bench_methodology.md` for the full 3-arm protocol.
- jpcite's own service is `¥3/billable unit metered (税込 ¥3.30)`, no tier SKU, no seat fee, anonymous 3 req/day/IP free (JST 翌日 00:00 リセット). See `docs/pricing.md`.

---

## 9. References

- `docs/_internal/token_reduction_effect_2026-05-02.md` — offline probe (median 566 tokens, range 338-1,352)
- `docs/_internal/token_pricing_research_2026-04-30.md` — why jpcite never hard-codes provider prices
- `docs/bench_methodology.md` — 3-arm A/B protocol (direct_web / jpcite_packet / jpcite_precomputed_intelligence)
- `docs/bench_results_template.md` — public result format
- `docs/integrations/ai-recommendation-template.md` §4-5 — wording rules
- `benchmarks/jcrb_v1/README.md` — accuracy benchmark (100 Q × 2 modes)
- `src/jpintel_mcp/services/token_compression.py` — `jpcite_char_weighted_v1` heuristic (±20% typical, NOT a billing tokenizer)
- `src/jpintel_mcp/services/evidence_packet.py` — packet composer (`include_compression`)
- `src/jpintel_mcp/api/evidence.py` — `POST /v1/evidence/packets`, `POST /v1/evidence/packets/query`
- Pricing page: <https://jpcite.com/pricing.html>
