# Long-Term Strategy

**Audience**: jpcite operator (Bookyou株式会社, BDFL solo). Quarterly review document.
**Status**: Y0 launch is 2026-05-06. This file covers Y1-Y5 (2026-05 → 2031-05).
**Pricing baseline**: ¥3/req tax-excluded (税込 ¥3.30), 50 req/月 anonymous free per IP, 100% organic acquisition, solo + zero-touch ops. No tier SKUs, no seat fees, no annual minimums. See `pricing.md`.

This document encodes the BDFL solo + zero-touch + organic-only constraints from `feedback_zero_touch_solo`, `feedback_organic_only_no_ads`, and `project_autonomath_business_model`. Any decision that violates those constraints (e.g. hiring a CS team, running paid ads, signing DPA negotiations) should be challenged against this doc before action.

---

## 1. Three scenarios (probability-weighted, not "guaranteed targets")

| Scenario | Probability | Y5 ARR (FY2031 run-rate) | Trigger conditions |
|---|---:|---:|---|
| **Best** | 30% | ¥750M – ¥1.5B | V2 (Healthcare) + V3 (Real Estate) + V4 (English-language surface) all deliver ≥ 80% of Y1 SMB curve; ≥ 1 partner integration (freee / Money Forward / kintone / SmartHR / Claude Desktop) drives 30%+ traffic; "Japanese subsidy" as a search query becomes synonymous with jpcite in agent tool selection. |
| **Base** | 50% | ¥150M – ¥450M | V1 (subsidy + agri) holds; V2 launches but at 30-50% of V1 curve; organic SEO + GEO compounds without paid amplification; 1-2 vertical extensions max within 5 years. |
| **Downside** | 20% | ¥30M – ¥60M | V1 plateaus at SMB-only adoption; 競合の集約サイト (gBizINFO, jGrants direct, biz.stayway) regain share; we lose distribution to a freee/Money Forward integrated competitor; tax cliff dates (2026-09 invoice 2割特例 expire) create a one-shot demand spike followed by erosion. |

**Why probabilities, not promises**. Past projections that promised ¥1B Y1 inflated investor / partner expectations and led to over-investment in directions that didn't compound. Probabilities force us to plan for the median, not the brochure.

### Y1-Y5 ARR projection (3 scenarios, ¥3/req full metered)

```
            Y1 (2027)      Y2 (2028)        Y3 (2029)         Y4 (2030)        Y5 (2031)
Best 30%  : ¥30 - 45M  →  ¥120 - 240M  →  ¥330 - 600M  →  ¥600 - 1.0B   →  ¥750M - 1.5B
Base 50%  : ¥30 - 45M  →  ¥90 - 150M   →  ¥150 - 300M  →  ¥240 - 450M   →  ¥150 - 450M
Down 20%  : ¥18 - 30M  →  ¥30 - 60M    →  ¥30 - 60M    →  ¥30 - 60M     →  ¥30 - 60M
```

Y1 lower bound is anchored on (a) ¥3/req unit economics, (b) 100% organic = no marketing burn, (c) launch-day MAU of 5-10k and 12-month MAU growth to 15-25k authenticated + 100k+ anonymous, (d) average authenticated user @ 200-400 paid req/month, (e) stripe metered billing only — no contracts, no retention obligation. The math: 15k auth × 300 req/mo × ¥3 × 12 = ¥162M would be best-case Y1; we discount to ¥30-45M base because the curve is back-weighted (most users join in months 6-12 after SEO crawl).

Best-case Y5 (¥750M-1.5B) requires a 5x5 matrix maturity (5 verticals × 5 surfaces). It is **not** the current commitment — see Section 6.

---

## 2. Five differentiation factors (short-term, decaying)

These are factors that give us a **relative advantage in the 1-2 year window**, not durable moats. Per the Z3/Z7 audit, we should assume any data-only differentiation will be matched by OSS / industry within 1-2 years. Long-term durability requires regulatory / hardware / network-effect / 5-year brand / capital — and we have **none** of those today. The honest framing: differentiation decays, and we plan accordingly. We do not assume permanence.

The ordering below is by **cheapest to maintain** under solo + zero-touch ops, not by "catch-up difficulty for a competitor".

### 2.1 Amendment time depth (relative advantage: 12-18 months)

Source: 制度時系列 snapshot (14,596 amendment events with `valid_from / valid_to` semantics). **Caveat from Z3/Z7 audit**: 82% of rows carry empty `eligibility_hash` and the time-series component is currently a thin layer over the underlying e-Gov data — we should not market this as "irreproducible historical reconstruction". The honest claim is: we have a continuous ingestion process running from 2026-05 onward, and a future entrant who starts later will have a shorter ingestion window for that period.

- Y1 target: 14,596 → 25,000+ (continue ingesting e-Gov diff feed)
- Y3 target: 25,000 → 60,000+
- Y5 target: 60,000 → 100,000+

The advantage is real but limited: e-Gov publishes raw legal text and OSS diff tooling could reproduce most of what we offer here within months. Treat this as a **publishing schedule** advantage, not a permanent gap.

### 2.2 Operator curation (relative advantage: 12-18 months)

Source: `hallucination_guard` tier (currently 504 manually-rejected hallucinations + 181 exclusion / prerequisite rules). Each row is a real query that produced a wrong answer once, plus the corrected expected output. This is what stops us drifting into "looks fluent, is wrong" territory.

- Y1 target: 504 → 1,500
- Y3 target: 1,500 → 5,000
- Y5 target: 5,000 → 10,000

A competitor with a comparable solo operator and the same audit discipline could close most of this gap in 12-18 months. The value is more in **ongoing discipline** (memory `feedback_no_fake_data` requires every claim to be 一次資料 verifiable) than in the snapshot count itself.

### 2.3 Customer relationships and brand (the only candidate for a real long-term differentiator)

Solo + zero-touch is **not** "no relationship" — it's "no human touch *during* the relationship". This is the one factor on this list that **could** compound into a durable advantage, but only over 5+ years and only if we keep operating the product honestly under the Bookyou株式会社 brand.

- Public testimonials (Y1 target: 10, Y3: 50, Y5: 200) — anonymized OK
- Public case studies (Y1: 5, Y3: 20, Y5: 50) — Japanese SMB / 士業 stories
- NPS public dashboard (Y2 onward, post-launch addition)
- Documented "saved ¥X / found Y subsidy" before/after — embedded in docs blog

Brand and trust take time. We do not claim it as a moat today (Y0). It is a candidate for one if we sustain operation for 5+ years with consistent honest disclosure. Until then, treat it as aspirational.

### 2.4 Regulatory and compliance discipline (relative advantage: 6-12 months)

Source: 景表法 / 個情法 / AI法 / インボイス compliance baked into product behavior:

- Tier=X quarantine for non-verifiable claims
- `claim_strength` tagging (avoiding 「最も」「絶対」「保証」 in search responses)
- `source_fetched_at` honest semantics (出典取得, never 最終更新)
- 10-keyword pre-emptive block list for 詐欺 risk phrases
- `tokushoho` / `pepper` / `honesty` compliance docs at `/compliance/*`

A new entrant who copies the published compliance docs and wires equivalent guards can close this gap in 6-12 months. Our advantage is in **operational discipline over time**, not in the rules being secret. Honest disclosure itself can become a differentiator if we sustain it.

### 2.5 Multi-domain breadth (relative advantage: 12-24 months per new vertical × 5)

The 5x5 matrix (5 verticals × 5 surfaces) requires:

| Vertical (V) | Status | Relative-advantage window | Y target |
|---|---|---|---|
| V1 Subsidy / 補助金 / 農業 / 法令 | ✅ launch (2026-05-06) | — | continuous |
| V2 Healthcare / 医療 (program_healthcare) | T+90d (post-launch) | 12-18m | Y1.5 |
| V3 Real Estate / 不動産 (program_realestate) | T+200d | 12-18m | Y2 |
| V4 English-language surface | T+150d | 6-12m | Y2 |
| V5 Korean / Chinese surfaces | Y2-Y3 deferred | 6-12m each | Y3-Y4 |

Surface variants (5): REST API, MCP stdio, LINE bot, embedded widget, 士業 案件紹介. Each is wired today and can multiply into V2-V5 schemas at marginal cost (schema migrations 013+).

**Note**: V2-V5 are not Y1 commitments. They appear here so a Y2 review can decide go/no-go with a written baseline.

---

## 3. Year-by-year decision gates

Each gate has a quantitative tripwire. If we miss the **lower** bound for two consecutive quarters, we re-evaluate (downscale, pivot, or exit) — not optimize harder.

### Y1 (2026-05-06 → 2027-05): "subsidy validation"
- ARR target: **¥30M – ¥45M** (lower-bound trip: ¥18M)
- MAU target: **15k – 25k authenticated** + 100k+ anonymous monthly
- Subsidy validation gate: ≥ 20 published case studies, ≥ 5 testimonials, NPS ≥ 30
- Decision at Y1+9mo (2027-02): green → Y2 plan; red → simplify to V1-only and lower the Y2 ceiling
- Ops cost ceiling: ≤ ¥6h / week solo time on launch-day operations (memory `feedback_organic_only_no_ads`)

### Y2 (2027-05 → 2028-05): "second vertical entry / runway decision"
- ARR target: **¥90M – ¥150M** (lower-bound trip: ¥60M)
- V2 (Healthcare) launches, T+90d V2-launch metric: ≥ 500 program rows ingested, ≥ ¥5M added MRR within 6 months
- Decision: Series A (if best-case curve), keep solo (if base), or sunset V2 (if downside)
- Hire-1-ops gate: NOT yet — even at ¥150M ARR, solo + zero-touch holds. Only hire if **MRR > ¥3M sustained 3 months AND solo time exceeds 20h/week** (memory `feedback_zero_touch_solo`)

### Y3 (2028-05 → 2029-05): "scale or maintain"
- ARR target: **¥240M – ¥450M** (lower-bound trip: ¥150M)
- V3 (Real Estate) decision: launch (best/base) or defer (downside)
- Hire-1-ops trigger: MRR > ¥3M sustained AND ≥ 20h/week solo time → hire 1 ops (specifically: data ingestion automation + Stripe billing edge cases). NOT a CS hire (memory bans CS team)
- Series A consideration: only if V2 + V3 both > 30% of V1 ARR. Otherwise, stay bootstrapped.

### Y4 (2029-05 → 2030-05): "exit-option year"
- ARR target: **¥450M – ¥900M** (lower-bound trip: ¥300M)
- Series A / acqui-hire / IPO candidacy review. By Y4 the differentiation factors (time depth ≥ 60k snapshots, curation ≥ 5,000 rows, ≥ 20 case studies, regulatory DB mature, ≥ 3 verticals live) **may** make jpcite an interesting acqui-hire candidate for a tax / accounting platform (freee, Money Forward) or an enterprise RAG vendor — provided the operator brand has compounded honestly over 4+ years. None of these factors are durable on their own; the bundle plus brand may be.
- Decision: Sell at Y4 (lock-in 5y outcome) vs. continue to Y5 maturity.

### Y5 (2030-05 → 2031-05): "maturity"
- ARR target: **¥750M – ¥1.5B** (best/base) or **¥30M – ¥60M** (downside)
- 5x5 matrix at full coverage: 5 verticals × 5 surfaces = 25 product touchpoints
- IPO / acquisition / private dividend: BDFL decides based on personal preference + Y4 review
- Year-by-year gates retire here; subsequent decision-making is "annual continuation review" only

---

## 4. Quarterly review template

Every 3 months (Y1Q1, Y1Q2, ..., Y5Q4), review against:

```yaml
quarter: 2027Q1   # example
date: 2027-04-30
arr_actual: ¥X.XM      # Stripe metered MRR × 12, last-30-day rolling
arr_lower_bound_for_quarter: ¥XM   # from year's lower-bound trip
arr_target_midpoint:        ¥XM   # from year's target range

scenario_classification: best / base / downside   # which 30% / 50% / 20% bucket are we in?

differentiation_metrics:        # tracked, not promised as durable
  amendment_snapshot_count:     N    # target: ≥ 14,596 + (months_since_launch × 800)
  hallucination_guard_count:    N    # target: monotonically increasing
  testimonials_published:       N    # target: ≥ Y1=10, Y3=50, Y5=200 (linear interp)
  case_studies_published:       N
  compliance_doc_completeness:  %

verticals_live: [v1_subsidy]   # [v1_subsidy, v2_healthcare, v3_realestate, v4_english, v5_kr_zh]
surfaces_live: [rest, mcp, line, widget, affiliate]

deviations:                  # any "off plan" decisions taken this quarter
  - desc: ...
    rationale: ...

next_quarter_actions:
  - ...                     # ≤ 5 actions, prioritized
```

This template is the ONLY mandatory recurring write — no other status reports, no monthly KPI emails, no weekly stand-ups (memory `feedback_zero_touch_solo`).

---

## 5. What we will NOT do (anti-goals)

These are explicit non-objectives — not "later", but "no":

- ✗ Paid advertising / SEM / display ads
- ✗ Outbound sales / cold email / cold calls
- ✗ Tier-based SaaS pricing (Free / Starter / Pro). The only free path is the anonymous 50/月 IP rate limit.
- ✗ DPA / MSA negotiations. Standard ToS is the only contract.
- ✗ Slack Connect / dedicated CS channels / phone support
- ✗ Onboarding calls
- ✗ Hiring sales reps
- ✗ Hiring a CS team
- ✗ White-label resale at "enterprise" tier (custom whitelabel widget at ¥30k/月 is fine, but no per-customer code branches)
- ✗ Ingesting from 集約サイト (noukaweb, hojyokin-portal, biz.stayway) — past 詐欺 incidents
- ✗ Reviving the "jpintel" brand (商標衝突 risk with Intel — `project_jpintel_trademark_intel_risk`)
- ✗ AnthropicAPI calls in our own server-side code path (per-request cost economics break — `feedback_autonomath_no_api_use`). Customer-side LLM only.

---

## 6. What "post-launch" means in this strategy

V2 Healthcare, V3 Real Estate, V4 English, V5 Korean/Chinese, and 5 partner integrations (freee / Money Forward / kintone / SmartHR / Claude Desktop) are **post-launch P5-P6 items**. They appear in the 5-year plan because:

1. The 5x5 matrix is plausible — schemas are pre-built (別名・略称 index に language 列追加, `record_kind` enum extension at migration 013) and the package source tree is already vertical-agnostic.
2. Y2-Y4 best-case ARR depends on at least V2 landing.
3. Future readers (auditors, partners, acquirers) need to see the trajectory written down before they ask.

But none of V2-V5 are **launch gates** for 2026-05-06. The launch gate is V1 only — see `analysis_wave18/audit_full/00_smart_merge_plan.md` Section 6.

---

## 7. Honesty constraints (cross-link)

- All ARR projections are **probability-weighted ranges**, never single-point promises (memory `feedback_no_fake_data`).
- All "relative-advantage window" estimates assume a competent + well-funded competitor. They are **not** assurances of safety — they are estimates of how long until we should expect parity. We do not assume the windows will not shrink.
- Differentiation factors are listed as **decaying short-term advantages**, not durable moats. Long-term durability would require regulatory / hardware / network-effect / 5-year operator brand / capital — we currently have only the operator-brand candidate and only if we sustain operation honestly for 5+ years.
- Operator cost ceiling = solo + ¥0 paid acquisition. Any deviation must be a written quarterly decision, not a default growth path.
- This document supersedes `_internal/strategy_*.md` predecessors. Keep CHANGELOG current when major scenario probabilities shift.

---

## 8. References

- [`docs/pricing.md`](pricing.md) — ¥3/req business model
- [`evals/gold.yaml`](https://github.com/shigetosidumeda-cyber/jpintel-mcp/blob/main/evals/gold.yaml) — 79-query precision baseline
- [`docs/per_tool_precision.md`](per_tool_precision.md) — per-tool gate table
- [`analysis_wave18/audit_full/00_smart_merge_plan.md`](https://github.com/shigetosidumeda-cyber/jpintel-mcp/tree/main/analysis_wave18) (private) — launch plan + post-launch P5-P6
- `CLAUDE.md` — non-negotiable constraints (¥3/req metered, no tiers, organic only, solo)

---

Last updated: 2026-04-26 (A9 inflated-claim cleanup — moats reframed as decaying short-term differentiation per Z3/Z7 audit). Next mandatory review: 2027-04 (Y1 close).
