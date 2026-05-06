# 税理士 1-Month Workflow Simulation

Customer-side ROI projection: 1 税理士 × 30 顧問先 × 1 month.
NO LLM API was called by this simulation — token math is the JCRB-v1
deterministic estimator (`benchmarks/jcrb_v1/token_estimator.py`).

## Workflow assumptions

- 顧問先: **30**
- Queries / 顧問先 / month: **200**
- Total queries / month: **6,000**
- Query mix:
  - subsidy_match — 30% (n=1,800) → jcrb-v1 domain: subsidy_eligibility
  - law_reasoning — 25% (n=1,500) → jcrb-v1 domain: law_citation
  - adoption_review — 20% (n=1,200) → jcrb-v1 domain: adoption_statistics
  - antisocial_check — 10% (n=600) → jcrb-v1 domain: enforcement_risk
  - kessan_briefing — 15% (n=900) → jcrb-v1 domain: tax_application
- jpcite price: **¥3.30/req** (税込) ≈ $0.0220/req at ¥150=$1
- jpcite total cost / month: **¥19,800** ($132.00)

## Per-model rollup (1 month, all 6,000 queries)

| model | closed-book USD (jpcite なし) | with-jpcite USD (LLM only) | jpcite metering USD | with-jpcite TOTAL USD | net saving USD | saving % |
|---|---:|---:|---:|---:|---:|---:|
| claude-opus-4-7 | $182.10 | $144.16 | $132.00 | $276.16 | **$-94.07** | **-51.7%** |
| gemini-2.5-pro | $22.93 | $12.75 | $132.00 | $144.75 | **$-121.82** | **-531.3%** |
| gpt-5 | $22.94 | $13.03 | $132.00 | $145.03 | **$-122.09** | **-532.1%** |

## 顧問先 1 件あたりの月次節約

| model | net saving / 顧問先 / month |
|---|---:|
| claude-opus-4-7 | $-3.14 |
| gemini-2.5-pro | $-4.06 |
| gpt-5 | $-4.07 |

## 時間節約 (citation_ok 0.40 → 0.95)

- Per-query verify time saved: **30 秒**
- Total verify time saved / month: **50.0 時間** (180,000 秒)
- Implied 税理士 hourly value @ ¥8,000/h: **¥400,000/月** ($2,666.67)

## Bottom line

### LLM-token line only (CFO view)

- **claude-opus-4-7**: closed-book $182.10 → with jpcite (LLM $144.16 + jpcite $132.00) $276.16 → **net $-94.07** (-51.7%).
- **gemini-2.5-pro** (cheapest tier here): net **$-121.82** (-531.3%).
- 解釈: token spend だけで見ると jpcite ¥19,800/月 を回収できない  (citation_ok lift / 時間節約 が真の ROI 源)。

### 時間節約を含む total ROI (税理士 view)

- 50.0 h/月 × ¥8,000/h = **¥400,000/月** ($2,666.67) の verify 時間節約。
- **claude-opus-4-7 + 税理士 verify time**: jpcite 月額 ¥19,800 を払っても累計 **$2,572.60/月** (¥385,889/月) 節約。
- 顧問先 1 件あたり: **$85.75/月** (¥12,863/月)。
- ROI 倍率: 月額 ¥19,800 投下 → ¥385,889 リターン = **19.5×**.

## Caveats

- Token estimator is the JCRB-v1 deterministic heuristic; absolute
  USD will drift ±15% vs measured runs (Anthropic + Gemini
  tokenizers approximated via cl100k_base + JP bias).
- jpcite context is a synthetic 5-row mock (calibrated to within
  ±20% of live `/v1/search` payload size).
- Time-savings figure assumes 100% of queries used to require
  verify; real 税理士 mix is closer to 60-70%. The headline number
  is therefore an upper bound for verify-time value.
- Mix shares (30/25/20/10/15) are the workflow assumption; rerun
  with `--mix` (future) to test sensitivity.
- Pricing as of 2026-05-05 (token_estimator.MODEL_PRICING).
