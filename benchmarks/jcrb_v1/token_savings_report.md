# JCRB-v1 Token Savings Report

- Questions: **5**
- Models: **claude-opus-4-7, gemini-2.5-pro, gpt-5**
- Methodology: closed-book input = system prompt + question;
  closed-book output = base 320 tokens + 0.6 × question chars
  (heuristic, calibrated against JCRB-v1 SEED runs).
  with_jpcite input = system + jpcite context block + question;
  with_jpcite output = base 110 tokens + 0.2 × question chars
  (compressed because the model can quote a cited row).
- Pricing: see `token_estimator.MODEL_PRICING` (USD per 1M tokens).
  No LLM API was called by this benchmark.

## Per-model rollup (mean per question)

| model | closed in | closed out | with_jpcite in | with_jpcite out | output tok saved | USD closed | USD with | USD saved/q | USD saved % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| claude-opus-4-7 | 311 | 358 | 1,198 | 122 | **+236** | $0.03152 | $0.02715 | **$+0.00437** | **+13.9%** |
| gemini-2.5-pro | 263 | 358 | 750 | 122 | **+236** | $0.00391 | $0.00216 | **$+0.00175** | **+44.7%** |
| gpt-5 | 270 | 358 | 765 | 122 | **+236** | $0.00392 | $0.00218 | **$+0.00174** | **+44.4%** |

## Aggregate

- Total (model, question) pairs scored: **15**
- Output tokens saved (sum across pairs): **+3,537**
- USD saved (sum across pairs): **$+0.0393**
- Avg USD saved per (model, question) pair: **$+0.002620**

## How to read this

**Total tokens go UP** with jpcite — context injection adds ~500
input tokens per question. **USD goes DOWN** because output
tokens are 5-8× more expensive than input on every model in this
table, and jpcite cuts the output side from ~360 to ~125 tokens
(the model quotes the cited row instead of speculating).

Per-question USD savings look small ($0.001-0.005). The product
story is volume × frequency: a 税理士 顧問先 fan-out running
200 saved searches/day × 30 顧問先 × 365d saves
$0.002 × 200 × 30 × 365 ≈ **$4,380/year/firm** in raw LLM spend,
BEFORE any quality lift (citation_ok jumps from ~0.40 to ~0.95
per JCRB-v1 SEED runs).

## Caveats

- Closed-book output length is a heuristic, not a measurement.
  Real model output length varies ±40% per run; a future revision
  should swap in measured medians from a customer-side eval set.
- jpcite context length is a real fetch (or a calibrated synthetic
  fallback when the API is unreachable). Synthetic fallback is
  within ±20% of live `/v1/search` payload size.
- Anthropic + Gemini tokenizers are approximated via cl100k_base
  with a Japanese bias factor (×1.3 / ×0.9). Absolute counts may
  drift ±15%; relative USD deltas are stable.
- The benchmark counts **only** LLM token spend. It does NOT
  count the ¥3/req jpcite metering on the with_jpcite side. At
  current rates that is ~$0.020/call (¥3 ≈ $0.020), so the LLM
  savings alone do not pay for jpcite — the value comes from the
  citation_ok lift, not raw token math.
