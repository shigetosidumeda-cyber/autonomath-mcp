# Wave 48 tick#1 — cost saving v2 quantify PR (STATE)

**Date**: 2026-05-12
**Branch**: `feat/jpcite_2026_05_12_wave48_cost_saving_v2_quantify`
**Lane**: `/tmp/jpcite-w48-cost-quantify.lane` (mkdir 排他取得)
**Worktree**: `/tmp/jpcite-w48-cost-quantify`
**memory**: `feedback_cost_saving_not_roi` (厳守) / `feedback_destruction_free_organization` (ADDENDUM marker で historical 残置) / `feedback_no_mvp_no_workhours` / `feedback_dual_cli_lane_atomic`

## 背景 (user 指示 2026-05-12 21:00 JST)

旧 cost saving 説明は 14 audience page × persona × 時給 ベース。 「AI agent 経由で普通の Claude/GPT を使うのと比べて jpcite が安い」という **顧客が即理解できる量化** がまだ無い。 v2 で **token 単価 + web search 課金 vs ¥3/req** を side-by-side で出す。

## 成果物 (4 ファイル新規 / 2 site update / 1 STATE doc)

| path | 種別 | LOC | 役割 |
|---|---|---|---|
| `docs/canonical/cost_saving_examples.md` | UPDATE | +160 | v2 section append (§ A 素 LLM コスト / § B jpcite / § C 6 case calc / § D 公式 pricing / § E Python script / § F disclaimer) |
| `tools/cost_saving_calculator.html` | NEW | 207 | static HTML + JS calculator (model select / FX / jpcite price / 6 use case live + 月次スケール) |
| `tests/test_cost_saving_v2_calculator.py` | NEW | 154 | 14 assertion: 6 UC math + 8 doc/HTML integrity |
| `site/pricing.html` | UPDATE | +18 | ADDENDUM 枠で v2 サマリ + calculator link |
| `site/compare.html` | UPDATE | +1 | 価格モデル列に v2 数字 inline + calculator link |
| `docs/research/wave48/STATE_w48_cost_saving_v2_pr.md` | NEW | 本ファイル | report |

## 6 use case 定量比較 (canonical SOT — doc / HTML / test 完全一致)

**前提**: Claude Sonnet 4.5 ($3/$15 per MTok) + Anthropic web search ($10/1k) + USD/JPY 150 + jpcite ¥3/req

| # | use case | in tok | out tok | search | req | 純 LLM ¥ | jpcite ¥ | **節約 ¥** |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | M&A DD (法人 360°) | 120,000 | 20,000 | 25 | 4 | 136.50 | 12 | **124.50** |
| 2 | 補助金 1 件 要件抽出 | 80,000 | 15,000 | 18 | 2 | 96.75 | 6 | **90.75** |
| 3 | 税理士 措置法該当 | 60,000 | 12,000 | 15 | 2 | 76.50 | 6 | **70.50** |
| 4 | 行政書士 許認可 | 90,000 | 15,000 | 20 | 2 | 104.25 | 6 | **98.25** |
| 5 | 信金 マル経 | 40,000 | 8,000 | 10 | 2 | 51.00 | 6 | **45.00** |
| 6 | dev 試作 endpoint | 50,000 | 10,000 | 12 | 5 | 63.00 | 15 | **48.00** |
| **合計** | 6 case 1 セット |  |  |  |  | **528.00** | **51** | **477.00** |

**月次/年次 スケール (#3 中央値 / API fee delta reference)**:
- 月 100 case (税理士 100 顧問): 純 LLM ¥7,650 / jpcite ¥600 → 月次 API fee delta **¥7,050** / 年換算 **¥84,600**
- 月 1,800 case (問い合わせ triage): 純 LLM ¥137,700 / jpcite ¥10,800 → 月次 API fee delta **¥126,900** / 年換算 **¥1,522,800**

## 検算 (3 軸 verify)

| verify | 結果 |
|---|---|
| `python3 cost calc` (canonical Python) | 6 UC pure / jpcite / saving 数字 全一致 |
| `html.parser` valid (tools/cost_saving_calculator.html) | 0 error / 0 open tag remaining |
| `test_cost_saving_v2_calculator.py` 14 assertion | ALL PASS (6 UC math + 8 doc/HTML integrity) |
| ROI / ARR / 年商 grep (v2 section) | 0 hit (memory `feedback_cost_saving_not_roi` 厳守) |
| 旧 brand grep (AutonoMath / zeimu-kaikei / 税務会計AI) | 0 hit in calculator HTML |
| LLM API import (src/ scripts/ tests/) | 不変 (本 PR は静的 doc/HTML/test のみ) |

## 一次参照 (公式 pricing inline)

- Anthropic Pricing: https://www.anthropic.com/pricing — Claude Sonnet 4.5 $3 input / $15 output per MTok / web_search_20250305 $10 per 1k
- OpenAI Pricing: https://openai.com/api/pricing/ — GPT-5 $1.25 input / $10 output, web search $10/$25/$30 per 1k (low/medium/high)
- 取得日: 2026-05-12 (v2 disclaimer 1 で 2026-11 再 verify 約束)

## memory 適合

- `feedback_cost_saving_not_roi`: v2 section 内に "ARR" / "年商" / "ROI 倍率" 0 hit (historical 14 page 表は ROI marker 残置、 v2 は touch せず) — test_canonical_doc_no_roi_arr_language で grep ガード
- `feedback_destruction_free_organization`: site/pricing.html v1 cost examples + v1 vs web search 表は **そのまま温存**、 v2 は ADDENDUM (dashed border + "Wave 48 tick#1 ADDENDUM" marker) で additive 追加。 rm / mv 0 件
- `feedback_no_mvp_no_workhours`: v2 全機能フル提供 (calculator 5 model / 4 search vendor / 月次年次スケール 全部出す)、 工数試算 / フェーズ分け なし
- `feedback_dual_cli_lane_atomic`: `mkdir /tmp/jpcite-w48-cost-quantify.lane` で排他 lane 取得済、 worktree も別 path
- `feedback_action_bias`: 即実装 → grep verify → test verify → PR open
- `feedback_validate_before_apply`: 数字 3 度 recalc (誤った最初の値 → realistic multi-turn baseline 採用) → doc / HTML / test 同期完了後に push

## 禁止事項クリア

- [x] ROI / ARR / 年¥X 表現 (v2 section に 0 件)
- [x] Anthropic 非公式 pricing 引用 (公式 URL 直リンク + 2026-05-12 取得 stamp)
- [x] main worktree (新 branch `feat/jpcite_2026_05_12_wave48_cost_saving_v2_quantify` で隔離)
- [x] rm / mv (全部 append-only / ADDENDUM marker)
- [x] 旧 brand (AutonoMath / zeimu-kaikei / 税務会計AI) 復活 (calculator HTML grep 0)
- [x] LLM API 呼出 (PR は静的 doc/HTML/test のみ、 src/ 変更なし)

## 次手 (Wave 48 tick#2 候補)

- 6 use case を業種 page (cpa_firm / tax_advisor / construction / shinkin 等) の cost saving table に v2 数字注入 (Wave 46 で 3 page 完了済、 残 14 page を v2 化)
- gpt-5 baseline での同等 calc を § E に追加 (cheaper input でも search × multi-turn で結果近似なので jpcite 優位は維持)
- calculator HTML に MCP playground 直リンク追加で agent 経由 ¥3 を即体感させる
