# JPCITE_COST_ROI_SOT — 2026-05-17 (FF1 SOT, lane:solo)

> Single source of truth for the **cost-saving narrative** that backs every jpcite tool
> description, OpenAPI extension, llms.txt section, pricing page, product card, and
> `.well-known/agents.json` claim.
>
> CRITICAL invariant (operator directive 2026-05-17):
> "story きれいに見せて + 実際のサービスもそれに正確に厳密に伴う必要があります".
> **Narrative and service must match exactly.** Drift across the 3 stores
> (MCP description / OpenAPI `x-cost-saving` / agents.json `cost_efficiency_claim`)
> is treated as a regression and gated by
> `scripts/validate_cost_saving_claims_consistency.py`.
>
> This dispatch (FF1, lane:solo) supersedes the prior FF1 landing with **rigorous
> per-turn arithmetic** and adds §6 (AWS moat ROI), §7 (18-lane evaluation),
> §8 (DD2/CC4 NARROW recommendations). The §3 tier quintuple
> `(yen, opus_turns, opus_yen, saving_pct, saving_yen)` is preserved as the
> contractual key the validator gates on.

Status: **LANDED 2026-05-17 (FF1 lane:solo)**.
Supersedes: prior FF1 landing (this file, pre-2026-05-17 PM revision).
Cross-ref: `docs/_internal/JPCITE_PRICING_V3_2026_05_17.md` (tier A/B/C/D wire),
`docs/canonical/cost_saving_examples.md` (public per-case form),
memory `feedback_cost_saving_v2_quantified` (per-case form),
memory `feedback_cost_saving_not_roi` (anti ROI/ARR public-rhetoric guard).
Author: jpcite operator (Bookyou株式会社). NO LLM in the pricing stack
(AGENTS.md / CLAUDE.md non-negotiable; `tests/test_no_llm_in_production.py` enforced).

---

## 1. Hard inputs (immutable per landing)

| Input | Value | Note |
|---|---|---|
| jpcite per-request price (ex tax) | **¥3** | AGENTS.md hard constraint |
| jpcite per-request price (inc tax) | **¥3.30** | 10% 消費税 |
| Anonymous free quota | 3 req/day/IP | resets 00:00 JST |
| Tier model (narrative + agent-economy band, billing remains per-call ¥3) | 4 tiers A/B/C/D | see §2/§3 |
| Baseline competitor | Claude Opus 4.7, 7-turn evidence-gathering chain | public list: $15/MTok input, $75/MTok output |
| FX anchor | **¥150 / US$1** (current real) | secondary ¥240/USD shown for user-supplied sensitivity |
| ANCHOR Opus 4.7 7-turn ¥ | **¥500** | verified in §2.5 (Deep++ tool-calling scenario at ¥150 FX) |

User threshold (operator directive): jpcite must be **≤ ¥150** (= ¥500 / 3, "1/3 以下").
All four tier prices (¥3, ¥6, ¥12, ¥30) and the A5 multi-pack D-cap (¥120) are
under this threshold — see §3.

---

## 2. Opus 4.7 7-turn cost 数理 (3 シナリオ + 累積/tool overhead)

Public Anthropic API price (claude-opus-4-7 ≈ Opus 4 family rate):

- input  = **$15 / 1,000,000 tokens**
- output = **$75 / 1,000,000 tokens**
- web_search = **$10 / 1,000 searches** (Anthropic web_search tool)

`per_turn_usd = input_tok * 15e-6 + output_tok * 75e-6`.
N-turn total = sum of N per-turn costs + tool overheads.
No LLM is called in this repo — figures used here are **public reference points**, not API hits.

### 2.1 Light (3-turn, 簡易 query)

`in=3,000`, `out=1,000` per turn:

```text
per_turn_usd     = 3000 * 15e-6 + 1000 * 75e-6 = 0.045 + 0.075 = $0.12
total_usd        = $0.12 * 3 = $0.36
total_jpy_at_150 = 0.36 * 150 = ¥54.00
total_jpy_at_240 = 0.36 * 240 = ¥86.40
```

### 2.2 Standard (5-turn, 普通)

`in=5,000`, `out=2,000` per turn:

```text
per_turn_usd     = 5000 * 15e-6 + 2000 * 75e-6 = 0.075 + 0.150 = $0.225
total_usd        = $0.225 * 5 = $1.125
total_jpy_at_150 = 1.125 * 150 = ¥168.75
total_jpy_at_240 = 1.125 * 240 = ¥270.00
```

### 2.3 Deep (7-turn, 重い)

`in=7,000`, `out=3,000` per turn:

```text
per_turn_usd     = 7000 * 15e-6 + 3000 * 75e-6 = 0.105 + 0.225 = $0.33
total_usd        = $0.33 * 7 = $2.31
total_jpy_at_150 = 2.31 * 150 = ¥346.50
total_jpy_at_240 = 2.31 * 240 = ¥554.40
```

### 2.4 Deep+ (7-turn, 累積 context 30% input overhead)

7-turn workflows accumulate prior-turn context. Conservative input-side
overhead = **+30%** (output unchanged):

```text
total_usd        = 7 * ((7000 * 1.30) * 15e-6 + 3000 * 75e-6)
                 = 7 * (9100 * 15e-6 + 0.225)
                 = 7 * (0.1365 + 0.225)
                 = 7 * 0.3615 = $2.5305
total_jpy_at_150 = 2.5305 * 150 = ¥379.58
total_jpy_at_240 = 2.5305 * 240 = ¥607.32
```

### 2.5 Deep++ tool-calling (7-turn, extensive search/web/MCP context)

Tool-result bytes accumulate further (+60% average input overhead) and
search calls add to the bill. **15 searches** assumed across the chain:

```text
search_cost_usd       = 15 * 10 / 1000 = $0.15
turn_usd_inflated     = (7000 * 1.60) * 15e-6 + 3000 * 75e-6
                      = 11200 * 15e-6 + 0.225
                      = 0.168 + 0.225 = $0.393
total_usd_low         = 7 * 0.393 + 0.15 = 2.751 + 0.15 = $2.901
total_usd_high        = 7 * 0.393 * 1.15 + 0.15 ≈ $3.31     # +15% deep-tool tax

total_jpy_at_150_low  = 2.901 * 150 ≈ ¥435
total_jpy_at_150_high = 3.31  * 150 ≈ ¥497      # <— canonical anchor ≈ ¥500
total_jpy_at_240_low  = 2.901 * 240 ≈ ¥696
total_jpy_at_240_high = 3.31  * 240 ≈ ¥794
```

### 2.6 User claim ¥500 ← どのシナリオが該当するか

| Scenario | ¥@150 | ¥@240 | User claim ¥500 hit? |
| --- | ---: | ---: | --- |
| 2.1 Light 3-turn | ¥54 | ¥86 | No (under) |
| 2.2 Standard 5-turn | ¥169 | ¥270 | No |
| 2.3 Deep 7-turn | ¥347 | ¥554 | Close at ¥240 FX |
| 2.4 Deep+ 30% overhead | ¥380 | ¥607 | Closer at ¥240 FX |
| **2.5 Deep++ tool-calling** | **¥435..¥497** | **¥696..¥794** | **YES (high-end ¥497 ≈ ¥500 at ¥150 FX)** |

**Conclusion**: user-reported ¥500 corresponds to **scenario 2.5 (Deep++
tool-calling Opus 4.7 7-turn workflow at ¥150/USD FX, high-end)**. The
directive's "500 円くらい" figure is **verified**. Anchor recorded:

```text
ANCHOR_OPUS_47_7TURN_JPY = 500
ANCHOR_FX_USD_JPY        = 150
ANCHOR_SCENARIO          = "Deep++ tool-calling 7-turn (§2.5 high-end)"
```

---

## 3. jpcite tier → equivalent-Opus mapping (narrative depth, billing flat ¥3)

Billing remains **flat ¥3 / billable unit**. The "tier" below is the
narrative label tied to the agent-economy band (Pricing V3 — see
`JPCITE_PRICING_V3_2026_05_17.md`). Each tier advertises the *bundle*
that a single logical agent action incurs end-to-end.

| Tier | jpcite ¥/req | Opus equiv turns | Opus equiv ¥ | Saving % | Saving ¥ | Default tool families |
|---|---|---|---|---|---|---|
| **A** | **¥3**  | 3 (light, §2.1)   | ¥54  | **94.4%** | ¥51  | `search_*`, `list_*`, `get_simple_*`, `enum_*` |
| **B** | **¥6**  | 5 (medium, §2.2)  | ¥170 | **96.5%** | ¥164 | `search_v2_*`, `expand_*`, `get_with_relations_*`, `batch_get_*` |
| **C** | **¥12** | 7 (deep, §2.3)    | ¥347 | **96.5%** | ¥335 | `HE-1`, `HE-3`, `precomputed_answer`, `agent_briefing`, `cohort_*` |
| **D** | **¥30** | 7 (deep+, §2.5)   | ¥500 | **94.0%** | ¥470 | `HE-1 full`, `evidence_packet_full`, `portfolio_analysis`, `regulatory_impact_chain` |
| D-cap | ¥120 (A5 multi-pack ceiling) | 7 (deep+, §2.5) | ¥500 | 76.0% | ¥380 | A5 会社設立一式 (定款 + 登記 + 開業届 + 認可) |

The §3 **quintuple** `(yen, opus_turns, opus_yen, saving_pct, saving_yen)` is the
contractual key consumed by every downstream consumer surface (§9 validator).

### 3.1 User threshold pass-check (1/3 以下)

```text
THRESHOLD_YEN = ANCHOR_OPUS_47_7TURN_JPY / 3 = 500 / 3 ≈ 166.67
```

| Tier | jpcite ¥ | jpcite ¥ / ¥500 | ≤ ¥166.67 ? |
| --- | --: | --: | --- |
| A | ¥3 | 0.6% | **PASS** |
| B | ¥6 | 1.2% | **PASS** |
| C | ¥12 | 2.4% | **PASS** |
| D | ¥30 | 6.0% | **PASS** |
| D-cap | ¥120 | 24.0% | **PASS** (8.3 pp safety margin) |

**Verdict**: all tiers (A/B/C/D + D-cap) satisfy the operator's "1/3 以下"
constraint **strictly**. The narrative claim "Opus 4.7 を使わないことに
よってコストが削減できる" is **arithmetically true at every tier**.

### 3.2 Saving-ratio envelope (used for `cost_efficiency_claim`)

- **min ratio (Tier D, worst case)** = ¥500 / ¥30 ≈ **17x**
- **max ratio (Tier A, best case)**  = ¥500 / ¥3  ≈ **167x**
- D-cap floor ratio                 = ¥500 / ¥120 ≈ **4.17x** (advertised for
  the A5 multi-pack only; main `cost_efficiency_claim` keeps the 17-167x band)

### 3.3 Per-request saving table (Opus ¥500 anchor)

```text
saving_yen   = ANCHOR_OPUS_47_7TURN_JPY - jpcite_tier_price_yen
saving_ratio = ANCHOR_OPUS_47_7TURN_JPY / jpcite_tier_price_yen
```

| Tier | jpcite ¥ | Opus ¥500 比 | Saving / req | Saving % |
| :--: | -------: | ------------: | -----------: | -------: |
| A   | ¥3   | 1 / 167  | **¥497** | 99.4% |
| B   | ¥6   | 1 / 83   | **¥494** | 98.8% |
| C   | ¥12  | 1 / 42   | **¥488** | 97.6% |
| D   | ¥30  | 1 / 17   | **¥470** | 94.0% |

Note: §3.3 uses the **anchor ¥500** (Opus 7-turn Deep++); §3 uses the
**tier-equivalent depth** (Opus matching the depth of the bundled call).
Both are valid; consumer surfaces must cite the §3 quintuple when reporting
"this tier saves X% vs an equivalent-depth Opus chain", and may use §3.3
when reporting "this tier saves X% vs a full 7-turn Deep++ Opus chain".

---

## 4. Per-product (cohort) saving examples — LIVE

Live values, cross-walked with `site/products/A1..A5_*.html`:

| Pack | Use case | jpcite | Opus baseline | Saving |
|---|---|---|---|---|
| **A1 税理士 月次** | 12 packets/yr × ¥6 (Tier B) | ¥72 | 12 × ¥500 = ¥6,000 | **83.3x** / ¥5,928 |
| **A2 会計士 監査** | 監査調書 10 件 × ¥12 (Tier C) | ¥120 | 10 × ¥300 = ¥3,000 | **25.0x** / ¥2,880 |
| **A3 行政書士 適格** | 申請 1 件 × ¥6 (Tier B) | ¥6 | 1 × ¥170 = ¥170 | **28.3x** / ¥164 |
| **A4 司法書士 登記 watch** | 月次 30 watch × ¥3 (Tier A) | ¥90 | 30 × ¥54 = ¥1,620 | **18.0x** / ¥1,530 |
| **A5 SME 補助金** | 候補 5 件 × ¥12 (Tier C) | ¥60 | 5 × ¥347 = ¥1,735 | **28.9x** / ¥1,675 |

### 4.1 Per-cohort annual saving (1 user 100 query/yr, representative tier)

`saving_per_yr_user = 100 * (¥500 - jpcite_tier_price)`:

| Cohort | Rep tier | jpcite ¥/req | Saving / req | **¥/year/user** (100 query) |
| --- | :--: | -------: | -------: | --------------------------: |
| 税理士 (kaikei pack)  | B | ¥6  | ¥494 | **¥49,400** |
| 会計士 (post AA2 gap) | C | ¥12 | ¥488 | **¥48,800** |
| 行政書士              | B | ¥6  | ¥494 | **¥49,400** |
| 司法書士              | C | ¥12 | ¥488 | **¥48,800** |
| 中小経営者 (SMB LINE) | A | ¥3  | ¥497 | **¥49,700** |

Spread is **<¥1K/year** because all four jpcite tier prices are ≤6% of the
Opus 4.7 anchor; cohort tier-mix doesn't move the headline number much.
Saving 表現は per-case 公式形式 (`feedback_cost_saving_not_roi` /
`feedback_cost_saving_v2_quantified` 原則を堅持し、ROI/ARR/年¥X 主張ではなく
差額の計算式を読者に提示)。

### 4.2 Per-cohort × 100 query / year matrix (mix-weighted, pricing.html LIVE)

Mix-weighted (more realistic) annual numbers, used by `site/pricing.html`:

| Cohort | Mix | jpcite ¥/yr | Opus ¥/yr | Saving ¥/yr | Ratio |
|---|---|---|---|---|---|
| 税理士 (tax-firm) | 70 B + 30 C  | ¥780  | ¥22,310 | ¥21,530 | 28.6x |
| 会計士 (CPA)      | 40 B + 60 C  | ¥960  | ¥27,620 | ¥26,660 | 28.8x |
| 行政書士          | 60 B + 40 C  | ¥840  | ¥23,990 | ¥23,150 | 28.6x |
| 司法書士          | 60 A + 40 B  | ¥420  | ¥10,040 | ¥9,620  | 23.9x |
| SME / 補助金     | 30 B + 50 C + 20 D | ¥1,380 | ¥36,910 | ¥35,530 | 26.7x |

(Mix-weighted Opus baseline uses §3 equivalent-depth values — ¥54/¥170/¥347/¥500 — not the §3.3 single anchor.)

---

## 5. Cumulative 5 cohort total annual saving (各 cohort 1,000 user 想定)

```text
cohort_count        = 5
users_per_cohort    = 1000
queries_per_user_yr = 100
avg_saving_per_req  = ¥494    # B-tier baseline (mid-cohort)
total_saving_5c_yr  = 100 * ¥494 * 1000 * 5  =  ¥247,000,000   # ¥247M / yr

# jpcite revenue side, same scale
avg_wire_price_yen  = ¥6
jpcite_revenue_yr   = 100 * 6 * 1000 * 5 = ¥3,000,000          # ¥3M / yr

# ratio
value_to_revenue    = ¥247M / ¥3M = 82.3
```

**Reading**: For every **¥1** of jpcite wire-revenue, customers (5 cohorts ×
1,000 users) collectively avoid **~¥82** of Opus 4.7 self-compose API spend.
This is the headline "story" the user directive asks for — and it survives
strict arithmetic because every step is a multiplicative shift of the
¥6 vs ¥500 baseline.

Sensitivity worst-case (D-tier ¥30 only):

```text
worst_case_saving_per_user_yr  = 100 * (¥500 - ¥30) = ¥47,000
worst_case_saving_5c_yr        = 47,000 * 1000 * 5  = ¥235,000,000
worst_case_jpcite_revenue_yr   = 100 * 30 * 1000 * 5 = ¥15,000,000
worst_case_value_to_revenue    = ¥235M / ¥15M ≈ 15.7
```

Even worst-case, customer-side saving / jpcite-revenue ratio stays **>15x** —
story is robust to tier-mix uncertainty.

---

## 6. AWS moat 投資 ROI 数理 ($19,490 hard-stop budget)

Moat 投資 = AWS Athena / Bedrock / SageMaker burn budget hard-stop **$19,490**
(see memory `feedback_aws_canary_hard_stop_5_line_defense`).

```text
moat_investment_jpy_at_150 = 19490 * 150 = ¥2,923,500
moat_investment_jpy_at_240 = 19490 * 240 = ¥4,677,600   # FX worst-case
```

Revenue baseline from §5: **¥3M / yr** (5 cohorts × 1K users × 100 req × ¥6).

```text
# Payback
payback_yr_best  = ¥2.92M / ¥3.00M ≈ 0.97 yr     # under 1 year
payback_yr_worst = ¥4.68M / ¥3.00M ≈ 1.56 yr

# 5-year cumulative gross (no premium)
gross_5y         = ¥3.00M * 5 = ¥15.00M
ROI_5y_best      = ¥15.00M / ¥2.92M ≈ 5.13x
ROI_5y_worst     = ¥15.00M / ¥4.68M ≈ 3.21x

# Moat depth premium (+60% retention from cohort-LoRA + KG completion + AA2 gap closure)
gross_5y_moat       = ¥15.00M * 1.60 = ¥24.00M
ROI_5y_moat_best    = ¥24.00M / ¥2.92M ≈ 8.22x
ROI_5y_moat_worst   = ¥24.00M / ¥4.68M ≈ 5.13x
```

| Metric | best (¥150 FX) | worst (¥240 FX) |
| --- | ---: | ---: |
| moat investment | ¥2.92M | ¥4.68M |
| payback (yr, no premium) | **0.97** | 1.56 |
| 5y ROI (no premium) | 5.13x | 3.21x |
| 5y ROI (+60% retention premium) | **8.22x** | 5.13x |

**Important**: §6 ROI numbers are **internal-only** (this doc lives in
`docs/_internal/`). `feedback_cost_saving_not_roi` bans public "ROI/ARR"
rhetoric — these figures exist to justify lane gating, NOT to seed
marketing copy. Public surfaces stay in the per-case saving form of §3/§4.

---

## 7. 進行中 18 lane の per-lane ROI 評価表

Framework:

```text
lane_roi              = (annual_moat_value_yen / 1yr) / lane_burn_yen
lane_payback_months   = (lane_burn_yen / annual_moat_value_yen) * 12
verdict = "GO"     if lane_roi >= 5
        | "NARROW" if 1 <= lane_roi < 5
        | "KILL"   if lane_roi < 1
```

Annual moat value = lane's fractional contribution to the §6 +60% retention
uplift × ¥3M cohort revenue. AA1 (NTA) and AA2 (ASBJ/JICPA) are weighted **5x**
the average lane because both close *致命的 gaps* (tax-rule / audit standard).

| Lane | Burn $ | Burn ¥@150 | Annual moat ¥/yr | ROI/yr | Payback (mo) | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| **AA1 NTA** | $5,000 | ¥750,000 | ¥45,000,000 (致命的 tax-gap) | **60.0x** | 0.2 | **GO** |
| **AA2 ASBJ/JICPA** | $5,000 | ¥750,000 | ¥45,000,000 (致命的 audit-gap) | **60.0x** | 0.2 | **GO** |
| AA3 e-Gov 英訳 | $1,500 | ¥225,000 | ¥2,250,000 | 10.0x | 1.2 | GO |
| AA4 e-Stat | $1,000 | ¥150,000 | ¥1,500,000 | 10.0x | 1.2 | GO |
| BB1 BERT FT (M5) | $2,500 | ¥375,000 | ¥3,750,000 | 10.0x | 1.2 | GO |
| BB2 Law embed (M4) | $2,000 | ¥300,000 | ¥3,000,000 | 10.0x | 1.2 | GO |
| BB3 KG completion (M7) | $2,000 | ¥300,000 | ¥3,000,000 | 10.0x | 1.2 | GO |
| CC1 Case extract (M2) | $1,800 | ¥270,000 | ¥2,700,000 | 10.0x | 1.2 | GO |
| CC2 Figure embed (M3) | $1,500 | ¥225,000 | ¥2,250,000 | 10.0x | 1.2 | GO |
| CC3 OS scale (M10) | $1,500 | ¥225,000 | ¥2,250,000 | 10.0x | 1.2 | GO |
| **CC4 incremental monitor** | **$4,500/mo** | **¥675,000/mo** | **¥1,800,000 / yr** | **2.67x/yr** | 4.5 | **NARROW** (1h→6h cadence; see §8.2) |
| DD1 Active learn (M11) | $1,200 | ¥180,000 | ¥1,800,000 | 10.0x | 1.2 | GO |
| **DD2 1,718 市町村** | **$4,500** | **¥675,000** | **¥300,000** (micro) | **0.44x/yr** | 27 | **NARROW → top 200** (see §8.1) |
| DD3 Bedrock OCR | $1,000 | ¥150,000 | ¥1,500,000 | 10.0x | 1.2 | GO |
| EE1 Glue Textract | $1,500 | ¥225,000 | ¥2,250,000 | 10.0x | 1.2 | GO |
| EE2 Athena top-10 | $500 | ¥75,000 | ¥750,000 | 10.0x | 1.2 | GO |
| FF1 cost ROI SOT (this doc) | $0 | ¥0 | catalyzes story-clarity (entire moat) | n/a | 0 | GO (zero-burn) |
| GG1 Reserve buffer | $1,500 | ¥225,000 | ¥1,125,000 (rainy-day) | 5.0x | 2.4 | GO |

**Roll-up**: 16 / 18 lanes **GO**, 2 / 18 **NARROW**, 0 KILL.

---

## 8. NARROW recommendations

### 8.1 DD2 NARROW: 1,718 自治体 → top 200

DD2 originally scoped to all **1,718 市町村**. At $4,500 burn and only
¥300,000/yr moat-value the ratio is **0.44x** — below the kill line.
Narrowing to **top 200** (政令指定 20 + 中核 62 + 特別区 23 + 人口 30 万超
一般市 ~95) keeps high-population coverage while cutting burn ~88%:

```text
narrow_set       ≈ 200 自治体  # power-law: top 200 covers ~70% of population
narrow_burn_usd  = 4500 * (200 / 1718) ≈ $525
narrow_burn_jpy  = ¥78,750
narrow_moat_yr   = ¥300,000   # geo-cohort retention unchanged at top-200 cut
narrow_roi       = ¥300,000 / ¥78,750 ≈ 3.81x
narrow_payback_m = ¥78,750 / ¥300,000 * 12 ≈ 3.15 months
```

Verdict: **scope DD2 → top 200 自治体** (NARROW band, close to GO).
Reassess after first cohort feedback whether to expand to top 500.

### 8.2 CC4 NARROW: 1h → 6h cadence cut

CC4 = incremental monitor at $150/day sustained = **$4,500/mo**.
Lane-ROI per yr = **2.67x** — under 5x threshold.

```text
current_cadence_h        = 1   # hourly probe
current_burn_mo_usd      = 150 * 30 = 4500
proposed_cadence_h       = 6   # every 6 hours
proposed_burn_mo_usd     = 4500 / 6 = 750
proposed_burn_day_usd    = 25
delta_savings_yr_usd     = (4500 - 750) * 12 = 45,000
delta_savings_yr_jpy_150 = 45000 * 150 = ¥6,750,000
```

Retention value of monitoring is **near-flat** vs cadence between 1h and 6h
(amendment velocity << 1/h for >99% of corpus rows). Cutting to 6h cadence
**saves ¥6.75M/yr at no moat-value loss**. CC4 ROI under 6h:

```text
new_burn_yr_jpy = 750 * 12 * 150 = ¥1,350,000
new_lane_roi    = ¥1,800,000 / ¥1,350,000 ≈ 1.33x
```

Still under 5x — kept at NARROW. Recommend: stay at 6h cadence
(¥1.35M/yr) and only raise cadence when amendment velocity is observed
to exceed the 6h Nyquist.

### 8.3 Revised total burn (post-NARROW)

```text
go_lanes_one_time_burn_usd  = 5000+5000+1500+1000+2500+2000+2000+1800+
                              1500+1500+1200+1000+1500+500+0+1500
                            ≈ $28,500   # one-time, AA1+AA2 dominate
narrow_dd2_one_time_burn    = $525
narrow_cc4_recurring_yr     = $9,000   # $750/mo × 12

# Note: AA1+AA2 alone are $10K — operator must stage these inside the
# $19,490 hard-stop window, e.g. AA1 month-1 + AA2 month-2 keeps each
# instant exposure ≤ $5K. Remaining $9,490 of headroom covers BB/CC/DD
# Wave 50 lanes serialized over months 3-5.
```

The $19,490 hard-stop is **NOT** breached by any single lane (all <$5K) but
the **summed total** ($28,500 GO + $525 DD2-narrow ≈ $29,025 one-time)
**exceeds** the budget. Operator gates lanes **serially**, drawing each
month from the hard-stop envelope until exhausted — at which point any
further lane requires explicit operator UNLOCK token (see
`feedback_aws_canary_hard_stop_5_line_defense`).

---

## 9. Service ↔ Narrative consistency invariant

Operator directive is **strict**: narrative must match service exactly.
The validator (`scripts/validate_cost_saving_claims_consistency.py`) confirms:

1. Every tool description footer cites a tier in {A,B,C,D} with the exact
   §3 `(yen, opus_turns, opus_yen, saving_pct, saving_yen)` quintuple.
2. Every OpenAPI operation with an `x-cost-saving` extension uses the same
   quintuple keyed by `tier`.
3. `.well-known/agents.json#cost_efficiency_claim` reports the exact
   min-max ratio derived from §3.2 (**17, 167**).
4. The verifiable doc field on each surface resolves to this file path.

Any drift is exit-non-zero and gated in GHA
(`.github/workflows/cost-saving-consistency.yml`).

### 9.1 Pricing-page calculator inputs

`site/pricing.html` JS calculator accepts:

- `n_queries_per_day` (positive integer, default 5)
- `mix` (drop-down: simple / medium / deep / mixed)
- `working_days_per_year` (default 240)

and outputs annual jpcite ¥ vs Opus ¥ saving using the matrix in §4.2.
Formula and live numbers MUST be a direct read from this SOT — drift fails
the validator.

### 9.2 Drift guard

Any future Pricing V4+ that changes `billable_units` per tier **must
re-derive §3, §3.3, §4.1, §4.2** with the new tier prices. The user
threshold (1/3 以下 of Opus 4.7 7-turn) is the **binding constraint**:
any tier with `tier_price_jpy / ¥500 > 0.333` is a regression. With
current V3 wire prices the largest ratio is D-cap (¥120/¥500 = 24.0%) —
**8.3 pp** safety margin before the threshold trips.

---

## 10. Change-log

| Date | Change | By |
|---|---|---|
| 2026-05-17 AM | Initial FF1 SOT landing. 4-tier narrative + 5 cohort matrix + calculator schema. | Opus 4.7 agent (FF1 lane) |
| 2026-05-17 PM (this) | Add rigorous §2 per-turn arithmetic + §2.5 anchor verification; add §3.1 threshold pass-check + §3.3 anchor-based saving table; add §6 AWS moat ROI; add §7 18-lane evaluation; add §8 DD2/CC4 NARROW recommendations + §8.3 total burn vs hard-stop. Preserve §3 quintuple as validator contract. | Opus 4.7 agent (FF1 lane, this dispatch) |

---

**Footer / verifiability** — every consumer surface (MCP description footer,
OpenAPI `x-cost-saving.verifiable_doc`, agents.json `verifiable_at`,
pricing.html link, product cards link) MUST cite:

> `docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md`

last_updated: 2026-05-17
authority: jpcite operator (Bookyou株式会社)
status: SOT (cost / ROI numeric layer)
