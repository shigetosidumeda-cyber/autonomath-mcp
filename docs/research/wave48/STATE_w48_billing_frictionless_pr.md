# Wave 48 tick#2 — billing frictionless PR

**Date**: 2026-05-12
**Branch**: `feat/jpcite_2026_05_12_wave48_billing_frictionless_v2`
**Lane**: `/tmp/jpcite-w48-billing-frictionless.lane` (atomic mkdir)
**User directive**: 「ユーザーからの課金導線ノンフリクション、迷子ゼロ」
**Memory anchors**: feedback_dual_cli_lane_atomic, feedback_destruction_free_organization,
  feedback_keep_it_simple, feedback_zero_touch_solo, feedback_autonomath_no_ui

---

## Deliverables (4 files, ~870 LOC net new)

| Path | Status | LOC | Purpose |
| --- | --- | --- | --- |
| `site/onboarding.html` | NEW | 224 | 4-step linear wizard + progress bar + skip + cost-saving reminders + FAQ |
| `site/assets/billing_progress.js` | NEW | 256 | Progress strip + idle-hint modal (30 s) + STEPS export + auto-mount |
| `site/pricing.html` | EDIT | +12 / 0 destructive | "¥0 から始められる" callout + `data-billing-progress` mount + script tag |
| `tests/test_billing_frictionless_flow.py` | NEW | 218 | 21 tests covering flow, idle, callout, breadcrumb, anti-pattern guards |

**Local verify** (jpcite venv Python 3.13):
```
$ pytest tests/test_billing_frictionless_flow.py -x -q
21 passed in 0.99s
```

---

## 4-step seamless flow

```
Step 1 (free)    →  Step 2 (signup)   →  Step 3 (topup)        →  Step 4 (use)
匿名 3 req/日       GitHub OAuth /        Credit Wallet /          API キー発行 /
登録なし            magic link 1 click    x402 USDC / Stripe       MCP server URL
playground.html     signin.html           wallet.html              dashboard.html#keys
```

Each step is a self-contained `<article data-step-id="X">` block with:

- 1 primary CTA (`.ob-cta`) leading to the next step
- 1 in-flow skip link (`.ob-skip`) to jump ahead — no "back" button needed
- 1 `.ob-saving` reminder of cost / savings in concrete numbers
- Linear top-to-bottom order verified by `test_onboarding_step_order_is_linear`

3 payment rails advertised (Credit Wallet / x402 / Stripe) so visitors with
different operating models do not get rail-locked. auto-topup default ON
sentence appears in Step 3.

---

## 迷子検知 (idle-hint) implementation

`site/assets/billing_progress.js` ships:

1. **Progress strip** auto-mounted into any page with `<div data-billing-progress>`
   (now: pricing.html, onboarding.html). Shows:
   - Current step + remaining free quota (`jpciteFreeRemaining` localStorage echo)
   - Step pills with done / current / pending colour states
   - Per-step "次へ:" primary CTA targeting the next href
2. **Idle detection** (`IDLE_MS = 30000`): listens to click / keydown / scroll /
   mousemove / touchstart with passive listeners; after 30 s of inactivity, opens
   a modal with the *next* step's hint copy + "あとで" close button.
3. **Step persistence** in `localStorage['jpciteBillingStep']` so a visitor
   returning later resumes on the right step.

Zero LLM-API import (anti-pattern guard `test_progress_js_has_no_external_deps`).

---

## Breadcrumb chain (迷子ゼロ)

```
ホーム  ›  料金  ›  はじめての方
```

- pricing.html breadcrumb already existed (`ホーム › 料金`).
- onboarding.html new breadcrumb extends the chain with `pricing.html` linked
  in the middle so the visitor can always navigate back.
- `data-billing-progress` strip at the top of both pages echoes the same
  4-step funnel so the "where am I" question is answerable in <1 s.

---

## Anti-patterns proactively blocked

| Memory | Guard in tests |
| --- | --- |
| `feedback_keep_it_simple` | `test_onboarding_no_tier_hierarchy` — no "Pro / Enterprise / tier N / プラン階層" leak |
| `feedback_zero_touch_solo` | `test_onboarding_no_human_touch_features` — no "営業担当 / Slack / DPA 個別調印" |
| `feedback_legacy_brand_marker` | `test_onboarding_no_legacy_brand_in_body` — body strips 税務会計AI / AutonoMath / zeimu-kaikei.ai (JSON-LD header allowed) |
| `feedback_no_operator_llm_api` | `test_progress_js_has_no_external_deps` — no `anthropic` / `openai` / ESM `import` |
| `feedback_destruction_free_organization` | All new files are additive; pricing.html change is +12 lines insert before existing hero + 1 line script tag inject — zero rm/mv |

---

## Files changed (final)

```
A  docs/research/wave48/STATE_w48_billing_frictionless_pr.md
A  site/assets/billing_progress.js
A  site/onboarding.html
M  site/pricing.html               (frictionless callout + progress mount + script tag)
A  tests/test_billing_frictionless_flow.py
```

## PR

- Title: `feat(billing): frictionless 4-step funnel + idle-hint (Wave 48 tick#2)`
- URL: filled in after `gh pr create`
- Acceptance: 21/21 local test pass, no rm/mv, no LLM API, no tier hierarchy
