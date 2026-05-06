# JCRB-v1 Token Savings Report

- Questions: **50**
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
| claude-opus-4-7 | 271 | 350 | 1,002 | 120 | **+230** | $0.03034 | $0.02402 | **$+0.00632** | **+20.8%** |
| gemini-2.5-pro | 254 | 350 | 741 | 120 | **+230** | $0.00382 | $0.00212 | **$+0.00170** | **+44.4%** |
| gpt-5 | 256 | 350 | 778 | 120 | **+230** | $0.00382 | $0.00217 | **$+0.00165** | **+43.2%** |

## Aggregate

- Total (model, question) pairs scored: **150**
- Output tokens saved (sum across pairs): **+34,563**
- USD saved (sum across pairs): **$+0.4832**
- Avg USD saved per (model, question) pair: **$+0.003221**

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

## Per-domain mean USD saving (averaged across all 3 models, n=30 per domain)

| domain | n | mean USD saved | min | median | max |
|---|---:|---:|---:|---:|---:|
| subsidy_eligibility | 30 | $+0.003306 | $+0.001627 | $+0.001746 | $+0.007110 |
| tax_application | 30 | $+0.003192 | $+0.001617 | $+0.001682 | $+0.006585 |
| law_citation | 30 | $+0.003183 | $+0.001567 | $+0.001692 | $+0.006810 |
| adoption_statistics | 30 | $+0.003148 | $+0.001608 | $+0.001669 | $+0.006435 |
| enforcement_risk | 30 | $+0.003278 | $+0.001657 | $+0.001711 | $+0.006810 |

## Per-model distribution (n=50 questions per model)

| model | n | mean USD saved | min | median | max |
|---|---:|---:|---:|---:|---:|
| claude-opus-4-7 | 50 | $+0.006317 | $+0.005685 | $+0.006285 | $+0.007110 |
| gemini-2.5-pro | 50 | $+0.001695 | $+0.001611 | $+0.001692 | $+0.001802 |
| gpt-5 | 50 | $+0.001652 | $+0.001567 | $+0.001648 | $+0.001758 |

## Regression rate (jpcite ATTACHMENT increases LLM spend, saving < $0)

- Total (model, question) pairs scored: **150**
- Pairs where saving < $0: **0**
- Regression rate: **0.00%**

Interpretation: at the current per-question shape (5 jpcite results @ ~487
input tokens of context), output-side compression (closed-book ~360 tok →
with-jpcite ~125 tok) outweighs the input-side context cost on every
(model, question) pair. ZERO regressions were observed in this 50q × 3-model
matrix. A regression would require a degenerate question — extremely short
input + the model already willing to answer in a single sentence — at
which point input-side context tokens dominate.

