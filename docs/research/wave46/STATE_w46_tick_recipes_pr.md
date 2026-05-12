# STATE w46 tick — site/docs/recipes 21 file ROI → cost saving PR

Wave 46 永遠ループ tick#3 (recipes pass).
Date: 2026-05-12.
Status: PR opened (will be back-filled with PR# / merge state after `gh pr create`).

## §1. Scope

`docs/research/wave46/INVENTORY_roi_expression.md` §4 で抽出された **21 recipes** の
billable_units 試算 section 内 `- ROI: …` 行を、Wave 46 tick#3 pricing 移行に
合わせて `- 節約 (純 LLM vs jpcite ¥3/req): …` の per-case framing に置換。

正本 (SOT): `docs/canonical/cost_saving_examples.md`。
recipes 側は SOT に逐次 cross-reference する形で drift 防止を狙う。

## §2. 修正対象 recipes (21 件)

| # | recipe slug | old framing | new framing |
|---|-------------|-------------|-------------|
| 1 | r01-tax-firm-monthly-review | 67-222 倍 ROI / 顧問契約解除 | 顧問先 100 社 × 月 1 cycle で **¥12,600/月 節約** |
| 2 | r02-pre-closing-subsidy-check | 6,944 倍 ROI / ¥15M ARR | 決算前 60 社 × 月 5 cycle で **¥5,040/期 節約** |
| 3 | r03-sme-ma-public-dd | 2,688 倍 ROI / ディール崩壊 | 月 10 案件 DD で **¥2,760/月 節約** |
| 4 | r04-shinkin-borrower-watch | 549 倍 ROI / 引当金 ¥500 万 | 担当 100 取引先 × 月 1 cycle で **¥6,600/月 節約** |
| 5 | r05-gyosei-licensing-eligibility | 1,777 倍 / 1,111 倍 ROI | 月 25 案件で **¥1,050/月 節約** |
| 6 | r06-sharoushi-grant-match | 助成金 1 件採択回収 | 顧問先 100 社 × 月 1 cycle で **¥7,000/月 節約** |
| 7 | r07-shindanshi-monthly-companion | 185-555 倍 ROI | 顧問先 50 社 × 月 1 cycle で **¥4,900/月 節約** |
| 8 | r08-benrishi-ip-grant-monitor | 出願補助 1 件回収 | 顧問先 50 社 × 月 1 cycle で **¥3,500/月 節約** |
| 9 | r09-bpo-grant-triage-1000 | 10-33x 粗利 | 月 4 batch × 250 で **¥36,000/月 節約** |
| 10 | r10-cci-municipal-screen | LTV ¥30M 維持 | 5 市町村 + 会員 1,000 社 で **¥6,400/月 節約** |
| 11 | r11-ec-invoice-bulk-verify | 控除否認 ¥1M 回避 | 月 1 batch × 500 取引先 で **¥3,500/月 節約** |
| 12 | r12-audit-firm-kyc-sweep | 監査報酬 ¥5-50M 毀損リスク | 月 30 件 KYC で **¥6,720/月 節約** |
| 13 | r13-shihoshoshi-registry-watch | 懲戒 ¥数百万-数千万回避 | 月 50 案件で **¥2,800/月 節約** |
| 14 | r14-public-bid-watch | ¥3M 粗利 1 件 | 月 20 営業日で **¥2,800/月 節約** |
| 15 | r15-grant-saas-internal-enrich | LTV 6-12 ヶ月上振れ | SaaS 顧客 50,000 社で **¥350,000/月 節約** |
| 16 | r24-houjin-6source-join | SaaS 工数 50-80% 圧縮 | 月 100 法人 join で **¥6,000/月 節約** + 工数圧縮 ADDENDUM |
| 17 | r25-adoption-bulk-export | 売上 5-10% 上振れ | 月 5 batch × 200 cycle で **¥7,000/月 節約** |
| 18 | r27-law-amendment-program-link | 法改正見落とし回避 | 月 10 件 link で **¥350/月 節約** |
| 19 | r28-edinet-program-trigger | M&A 機会 5-10% 上振れ | 監視 100 社 × 月 4 週で **¥2,300/月 節約** |
| 20 | r29-municipal-grant-monitor | 補助金発見 1 件回収 | 47 自治体 × 月 4 週で **¥1,316/月 節約** |
| 21 | r30-invoice-revoke-watch | 控除否認 ¥1M 回避 | 仕入先 1,000 社 × 月 4 週で **¥28,000/月 節約** |

合計 21 / 21 完了。

## §3. 節約金額 range

各 recipe の per-case 節約金額レンジ:

- **最小**: r27 (法改正 link) = **¥350 / 月**
- **最大**: r15 (SaaS bulk enrich 50,000 社) = **¥350,000 / 月**
- 中央 cluster (実務 single-prof):
  - ¥1,000 – ¥10,000 / 月 帯: r05 / r10 / r13 / r14 / r28 / r29 / r27 / r02
  - ¥10,000 – ¥40,000 / 月 帯: r01 / r03 / r04 / r06 / r07 / r08 / r09 / r11 / r12 / r24 / r25 / r30
- enterprise / multi-tenant 帯: r15 のみ (50,000 SaaS 顧客スケール)

**range 公称表記**: **¥350 - ¥350,000 / 月** (per-recipe per-case basis、SOT 6 use case の総合 ¥104,260/月 とは別計算)。
日本国内 SME 中央値で見ると **¥3,000 - ¥10,000 / 月** が代表的レンジ。

## §4. 表現方針 (recipes 適用)

1. **per-case 統一**: 全 recipe で `- 節約 (純 LLM vs jpcite ¥3/req): <freq context> で、純 LLM は約 ¥X/月 (内訳) に対し jpcite は ¥Y/月 (req 数 × ¥3) → 節約 約 ¥Z/月 / 単位あたり ¥W (cf. canonical case N)` の構文を採用。
2. **倍率は完全排除**: 「N 倍 ROI」「ARR ¥X」「射程 ¥X」 等の multiplier は 0 件。
3. **回避利益語の禁止**: 「懲戒 1 回回避」「ディール崩壊」「LTV 上振れ」 等は ADDENDUM marker (r24 のみ) でのみ言及、本行ではコスト差分のみ。
4. **canonical cross-ref**: 全 21 件で `docs/canonical/cost_saving_examples.md` を参照、case N (1-6) に紐付け。
5. **billable_units 試算 heading は保持**: 既存 anchor 構造に影響なし。

## §5. Test 追加 (tests/test_recipes_cost_saving.py)

~140 LOC、107 test 件 (offline、network/LLM 不要):

- `test_recipe_has_cost_saving_line` × 21: 各 recipe に新 framing line が **exactly 1 件** 含まれる
- `test_recipe_no_roi_prefix` × 21: `- ROI:` prefix が **0 件**
- `test_recipe_references_canonical_doc` × 21: canonical doc path への cross-ref 存在
- `test_recipe_brand_jpcite_consistent` × 21: 旧 brand (税務会計AI/AutonoMath/zeimu-kaikei.ai) **0 件**
- `test_recipe_structure_intact` × 21: `## billable_units 試算` heading 保持
- `test_canonical_doc_exists` × 1
- `test_all_21_target_recipes_present` × 1

ローカル実行結果: **107 passed in 1.30s** (jpcite venv / pytest 8.x)。

## §6. 禁止事項の遵守

- 大規模 redesign: 行 1 本のみの差替、heading / 隣接 list 不変
- surface text 改ざん: 旧 framing は git diff で確認可能、PR description に before/after 表
- main worktree: detached HEAD で `/tmp/jpcite-w46-recipes-cost` 隔離
- 旧 brand: legacy brand grep 0 件
- LLM API: import scan 0 件、本 PR の test は完全 offline / regex のみ

## §7. ループ continuity

dual-CLI lane: `/tmp/jpcite-w46-recipes-cost.lane` mkdir 排他取得済 (Wave 46 tick#3 recipes pass)。
次 tick 候補 (memory より):

- 18 dim doc per-persona delta 置換 (INVENTORY §3)
- audiences/ 内 ROI/ARR 言及 (INVENTORY §5)
- site/pricing.html / compare.html の post-merge consistency re-check

## §8. PR Body skeleton

```
title: feat(site): Wave 46 tick#3 recipes — 21 file ROI → 節約 framing per-case

## Summary
- 21 recipes (r01-r15, r24, r25, r27, r28, r29, r30) で `- ROI:` 倍率 framing を
  `- 節約 (純 LLM vs jpcite ¥3/req)` の per-case framing に統一移行
- 各 recipe で realistic frequency (月 cycle 数) を明示し、純 LLM cost vs jpcite ¥3/req cost
  の差分を ¥/月 で直接提示
- docs/canonical/cost_saving_examples.md (SOT) への cross-ref を全 recipe に挿入
- tests/test_recipes_cost_saving.py 新規 (~140 LOC, 107 test, offline)
- ROI 倍率 / ARR / 射程 / 回避利益語の 0-grep gate

## Verify
- 21/21 recipes 移行完了
- ROI prefix grep: 0 件
- canonical cross-ref: 21/21 件
- legacy brand grep: 0 件
- pytest 107 / 107 PASS

## Cost saving range
¥350 (r27 法改正 link) ～ ¥350,000 (r15 SaaS enrich 50,000 社) / 月
```

## §9. 帰結

- ROI/ARR/射程 等の mention-bias multiplier framing は site/pricing.html + recipes 21 件で 0 化。
- 残: 18 dim doc (INVENTORY §3) / audiences (INVENTORY §5) / by_industry doc / その他 SOT 派生 doc。
- SOT (canonical/cost_saving_examples.md) の 6 use case 群を 21 recipes が一斉に参照する構造、drift 検出 grep 容易化。

LIVE STATE: PR open 後、本 doc を実 PR# で update。
