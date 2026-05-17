# JPCITE_PRICING_V3 — Agent-Economy First Outcome Bands (2026-05-17)

Status: **LANDED 2026-05-17** (re-dispatch after V2 / F4 retrospective).
Supersedes: `pricing_billing_deepdive_2026-05-15.md` Tier band, product
A1..A5 Stage 3 F4 price points (V2 ¥200..¥1,000 per call). The V2 spec
stays in `src/jpintel_mcp/billing/pricing_v2.py` untouched for legacy /
rollback; V3 is the new wire-default starting 2026-05-17.

Author: jpcite operator (Bookyou株式会社). NO LLM in the pricing stack
(CLAUDE.md non-negotiable, `tests/test_no_llm_in_production.py` enforced).

## 1. Problem with V2 / F4 (¥200..¥1,000 per call)

V2 layered a 4-tier outcome band (Tier A ¥3 / B ¥10 / C ¥30 / D ¥100..¥1,000)
on top of the ¥3/req metered baseline. Empirically, after 2 weeks of
agent-side observation:

* Existing SaaS (freee / MF / TKC / 弥生) + LLM-on-top can already produce
  an _approximate_ 月次決算 / 監査調書 / 就業規則 / 補助金ロードマップ /
  会社設立書類 at **Sonnet 4.6 self-compose 2-8 turns ≒ ¥7.5..¥30**. The
  agent is **price-anchored** against this self-compose baseline.
* When jpcite A1 (¥1,000) sits next to Sonnet 8-turn workflow (¥30), the
  agent skips the jpcite call and rolls its own workflow with Sonnet,
  even though the jpcite output is deterministic + cited + scaffold-only
  + legally safer.
* Tier D ¥100..¥1,000 is therefore **above the agent skip threshold** on
  every product (A1..A5). HE-1/2/3 at ¥30 (old framing) is also above the
  Sonnet 4-turn (¥15) self-compose price, so they get skipped too.

## 2. V3 — 4-tier Agent-Economy First bands

Unit price stays **¥3 / billable unit** (CLAUDE.md hard guard). Only the
`billable_units` per tier changes.

| Tier | Name | `billable_units` | Price (¥) | Compose pattern | vs Sonnet 4.6 self-compose | Verdict |
| ---- | ---- | ----------------: | ----------: | ------------------------------- | -------------------------------: | ------- |
| A    | atomic         | **1**   | **¥3**   | 1 atomic MCP / REST call       | Sonnet 1 turn ¥3.75  → save ¥0.75 | jpcite wins by ¥0.75 |
| B    | composed       | **2**   | **¥6**   | 2-5 atomic calls server-side   | Sonnet 2 turn ¥7.50  → save ¥1.50 | jpcite wins by ¥1.50 |
| C    | heavy_endpoint | **4**   | **¥12**  | 4-13 atomic calls / rule_tree  | Sonnet 4 turn ¥15.00 → save ¥3.00 | jpcite wins by ¥3.00 |
| D    | workflow       | **10**  | **¥30**  | full composed deliverable      | Sonnet 8 turn ¥30.00 → **parity** | Opus parity (Opus 8 turn ¥75 → save 60%) |

D-tier band is `[¥30, ¥120]` so the A5 multi-pack bundle (2-4 sub-D packs in
one logical call) can stay one call: **A5 = 20..40 billable_units = ¥60..¥120**.

V2→V3 unit migration (closest-band):

| V2 units | V3 units | Note |
| -------: | -------: | ---- |
| 1        | 1        | A unchanged |
| 2-5      | 2        | V2 B → V3 B |
| 6-20     | 4        | V2 C → V3 C |
| 21+      | 10       | V2 D 33 / 267 → V3 D 10 baseline |

Helper: `jpintel_mcp.billing.pricing_v3.migrate_v2_units_to_v3(int) -> int`.

## 3. Product reconfig — A1..A5 + HE-1/2/3

| Product | V2 / F4 price | V3 price | V3 `billable_units` | V3 tier |
| ------- | ------------: | -------: | ------------------: | :-----: |
| A1 税理士月次決算          | ¥1,000        | **¥30**  | **10**             | D |
| A2 会計士監査調書         | ¥200          | **¥30**  | **10**             | D |
| A3 補助金ロードマップ Deep | ¥500          | **¥30**  | **10**             | D |
| A3 補助金ロードマップ Lite | (new)         | **¥12**  | **4**              | C |
| A4 就業規則               | ¥300          | **¥30**  | **10**             | D |
| A5 会社設立一式 (4 sub-D) | ¥800          | **¥60..¥120** | **20..40**     | D (multi-pack) |
| HE-1 full_context        | ¥3            | **¥12**  | **4**              | C |
| HE-2 implementation_workpaper | ¥3      | **¥12**  | **4**              | C |
| HE-3 briefing_pack       | ¥3            | **¥12**  | **4**              | C |

A5 stays unique as the only multi-pack: it bundles 2-4 D-tier sub-packs (定款 +
登記書類 + 開業届 + 各種許認可) into one logical call. The host MCP server
reports `billable_units` ∈ {20, 30, 40} based on actual sub-pack composition
at request time; the wire price band is `[¥60, ¥120]`.

## 4. Revenue projection — 1M req/月 mix

| Tier | mix share | calls /月 | yen / call | revenue / 月 |
| ---: | --------: | --------: | ---------: | -----------: |
| A    | 60%       | 600,000   | ¥3         | ¥1,800,000 |
| B    | 20%       | 200,000   | ¥6         | ¥1,200,000 |
| C    | 12%       | 120,000   | ¥12        | ¥1,440,000 |
| D    | 8%        | 80,000    | ¥30        | ¥2,400,000 |
| **total** | **100%** | **1,000,000** | (avg ¥6.84) | **¥6,840,000 / 月** |

Honest sanity-check note: the user-supplied projection mentions
`¥5.64/req avg` and `¥67.7M/年 ($450K ARR)` which assumes a slightly
different mix-share (heavier on Tier A 70% / B 18% / C 8% / D 4%).
Both projections sit inside the same `[¥5.64, ¥6.84]` average band and
both reach `$300K..$600K ARR` at 1M req/月 saturation.

Versus a uniform Tier-A-only price (¥3/req × 1M = ¥36M / 年 / $240K
ARR), V3 mix delivers **~x1.88..x2.28** revenue uplift while staying
**inside the agent-skip threshold** on every tier.

## 5. Non-negotiable

* **Unit price = ¥3** (CLAUDE.md "Non-negotiable constraints"). Only
  `billable_units` per tier changes.
* **NO LLM** in pricing stack (`tests/test_no_llm_in_production.py`).
* **Backwards-compatible**: V2 module untouched. Each envelope carries
  `pricing_version: "v3"` so we can flip back to V2 by env-var-pin
  (planned: `JPCITE_PRICING_VERSION=v2` overrides at boot, default v3).
* **No subscription**: even at A5 ¥120 multi-pack, billing remains
  per-call metered, no monthly seat fees.

## 6. Wire surfaces touched

* `docs/_internal/JPCITE_PRICING_V3_2026_05_17.md` — this doc (canonical).
* `src/jpintel_mcp/billing/pricing_v3.py` — V3 module (1/2/4/10 units,
  3-baseline value_proxy: Opus / Sonnet / Haiku).
* `src/jpintel_mcp/mcp/products/product_a{1..4}_*.py` — `_BILLING_UNITS` /
  `_BILLABLE_UNITS` constants + `_billing_envelope()` emit
  `pricing_version: "v3"`, `tier`, and `value_proxy` against 3-baseline.
* `src/jpintel_mcp/mcp/moat_lane_tools/he{1,2,3}_*.py` — bump
  `_billing_unit` 1 → 4 (Tier C ¥12).
* `tests/test_billing_pricing_v3.py` — 35 V3 tests.
* `site/.well-known/jpcite-outcome-catalog.json` — `pricing_version: "v3"`
  + Tier-D `[¥30, ¥120]` band on `price_bands`.
* `site/llms.txt` — Tier-band line under Pricing.
* `site/compare/{zeirishi,kaikei,gyoseishoshi,shihoshoshi,sme}.html` —
  V3 tier block.

## 7. Rollback path

V3 → V2 rollback: env `JPCITE_PRICING_VERSION=v2` + `pricing_v2.PRICE_BY_TIER`
re-bind in the host MCP dispatcher. The `pricing_version` field is checked
by the wire-egress validator and by Stripe metered submission so we can
rollback without losing the billing ledger.

## 8. Why agent-economy first

* **Justifiability**: every tier carries a `value_proxy` (Opus / Sonnet /
  Haiku self-compose comparison) inside the response envelope.
* **Discoverability**: lower D-tier ceiling (¥120) makes jpcite outcome
  packs appear inside the same micropayment envelope agents already use
  for x402 / Credit Wallet.
* **Retainability**: agent that started with one A-tier call has 3
  natural upsell steps (B → C → D) at ≤ x4 step, not x100 step.

Last updated: 2026-05-17.
