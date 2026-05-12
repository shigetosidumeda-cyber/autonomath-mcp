# STATE: Wave 49 tick#3 — Calculator RUM funnel wire (4 → 5 stage G1)

- **Wave**: 49 永遠ループ tick#3
- **Lane**: `/tmp/jpcite-w49-calc-rum-wire.lane` (atomic mkdir claim)
- **Worktree**: `/tmp/jpcite-w49-calc-rum-wire`
- **Branch**: `feat/jpcite_2026_05_12_wave49_calc_rum_wire`
- **Base**: `origin/main` @ `74ec7b8f2` (Wave 49 mig288 boot manifest hot-fix)

## Why

Wave 49 tick#11 で `cost_saving_calculator.html` は 200 LIVE
6 use case 90.3% off reproduce OK が確認できた。
しかし **funnel 計測が 0** — `rum_funnel_collector.js` が
calculator HTML に未配線で、`inferStep()` も 4 stage
(landing / free / signup / topup) のみだったため、
cost-saving v2 の reproducibility surface に到達した
ユーザーが G1 funnel から完全に抜け落ちていた。

memory **`feedback_cost_saving_v2_quantified`** が要求する
「JS calculator 公開で再現可能化」を funnel 計測まで含めて
完成させるため、5 stage 目 `calc_engaged` を additive 追加する。

## 5-stage Funnel (after this PR)

| # | step | path | event source |
|---|------|------|--------------|
| 1 | `landing`      | `/` `/index.html`                         | auto view |
| 2 | `free`         | `/onboarding*`                            | auto view |
| 3 | `signup`       | `/pricing*`                               | view + `data-funnel-cta` click |
| 4 | `topup`        | `/topup*` `/checkout*` + Stripe webhook   | view + server emit |
| 5 | **`calc_engaged`** | **`/tools/cost_saving_calculator*`**  | **view + `jpcite:funnel:complete` on first input change** |

## Changes (2 file additive)

```
 site/assets/rum_funnel_collector.js    | 19 +++++++++++++------
 site/tools/cost_saving_calculator.html | 20 ++++++++++++++++++++
 2 files changed, 33 insertions(+), 6 deletions(-)
```

### 1. `site/tools/cost_saving_calculator.html` (+20 lines)

- `</body>` 直前に `<script src="/assets/rum_funnel_collector.js" defer></script>` 配線。
- 6 input 要素 (`model`/`search`/`fx`/`jpcite`/`scale-case`/`scale-n`) のうち
  最初の change event で `CustomEvent('jpcite:funnel:complete')` を dispatch。
  collector がそれを拾って `step_complete` beacon を emit。
- 既存 `render()` / 6 input listener は触らない (additive only)。

### 2. `site/assets/rum_funnel_collector.js` (+13/-6 lines)

- `inferStep()` に `if (p.indexOf("/tools/cost_saving_calculator") === 0) return "calc_engaged";`
  を 5 番目の case として追加 (4 既存 case の後)。
- header docstring を 4-step → 5-step 説明に書き換え (rationale 含む)。
- `ALLOWED_STEPS` 等の他箇所は変更なし — server side `functions/api/rum_beacon.ts`
  の allow-set 更新は別 PR で fold する (この PR は purely client-side wiring)。

### 3. `tests/test_calc_rum_wire.py` (+121 lines, new)

4 structural test:

1. `test_calculator_html_loads_rum_funnel_collector` — script tag 存在 + `defer` + `</body>` 前。
2. `test_calculator_html_dispatches_funnel_complete_event` — `jpcite:funnel:complete` dispatch あり。
3. `test_rum_collector_inferstep_has_calc_engaged_case` — `inferStep()` に `calc_engaged` + canonical path 参照。
4. `test_rum_collector_preserves_4_pre_existing_steps` — destruction-free: 既存 4 step 残存。

## Verify

- `node --check site/assets/rum_funnel_collector.js` → JS_SYNTAX_OK
- 4 structural test → ALL_4_TESTS_PASS (local importlib, conftest UTC bypass)
- HTML body/html 開閉 count == 1 / script tag pos < `</body>` pos / defer attr 存在

## Memory rules adhered

- **`feedback_dual_cli_lane_atomic`** — mkdir lane claim + worktree from origin/main。
- **`feedback_destruction_free_organization`** — additive only、`rm`/`mv` ゼロ、既存 4 step
  全残存テスト (test #4) で gate。
- **`feedback_cost_saving_v2_quantified`** — calculator 公開の funnel 計測まで完成、
  `calc_engaged` という独立 stage で「reproducibility surface 到達者」を見える化。

## Out of scope

- Server-side `functions/api/rum_beacon.ts` の `ALLOWED_STEPS` 拡張 (別 PR)。
- Status dashboard (`site/status/rum.html`) の 5-stage 表示 (別 PR、tick#4+ 候補)。
- Calculator 自体の機能拡張 (rewrite 禁止指示厳守)。
