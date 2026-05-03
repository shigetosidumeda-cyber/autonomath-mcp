---
exec_id: I8_cookbook
title: Cookbook 12 recipe 実装 + mkdocs nav 接続
date: 2026-05-04
agent: cookbook_12_implementer
related_research: analysis_wave18/research_W2_6_cookbook_30_2026-05-04.md
---

# I8 — Cookbook 12 recipe 実装

## スコープ

W2-6 で抽出された 30-recipe outline のうち「即書ける Top 5 + 残り 7 即書ける」12 本を `docs/cookbook/` 配下に配置。

## 完了

- 12 ファイル新設 (`docs/cookbook/<slug>.md`)
- `docs/cookbook/index.md` (12 recipe 早見表 + cohort 早見 + コスト概観)
- `mkdocs.yml` nav に Cookbook (1 概要 + 12 サブ) を追加
- `docs/index.md` ホームの「最初に読むもの」表に Cookbook 行追加
- `docs/api-reference.md` 冒頭に Cookbook へのナビゲーション 1 行追加
- `mkdocs build --strict` PASS (warnings: 0)

## ファイル一覧

| ID | ファイル | 主 cohort | 免責 |
|---|---|---|---|
| R01 | docs/cookbook/r01-weekly-alert-per-client.md | C2 ZEI | §52 |
| R02 | docs/cookbook/r02-tax-cliff-digest.md | C2 ZEI | §52 |
| R03 | docs/cookbook/r03-monthly-invoice-verify.md | C2 ZEI | PDL v1.0 出典 |
| R09 | docs/cookbook/r09-corp-360-view.md | C1 MA | §72 + §52 |
| R10 | docs/cookbook/r10-case-studies-search.md | C5 HOJ | — |
| R11 | docs/cookbook/r11-enforcement-watch.md | C1 MA | (M&A 文脈で §72) |
| R16 | docs/cookbook/r16-claude-desktop-install.md | All | — |
| R17 | docs/cookbook/r17-cursor-mcp.md | All | — |
| R18 | docs/cookbook/r18-chatgpt-custom-gpt.md | All | — |
| R19 | docs/cookbook/r19-gemini-extension.md | All | — |
| R20 | docs/cookbook/r20-openai-agents.md | All | — |
| R21 | docs/cookbook/r21-pref-heatmap.md | C7 SKK | — |

## 各 recipe 構成

- TL;DR
- runnable サンプル (curl + bash / Python / MCP)
- expected output 抜粋
- **代替手段 vs jpcite cost** (¥3/req 税込 ¥3.30 ベース、手動巡回 ¥5,000/h との比較)
- §52 / §72 / §1 disclaimer (該当時のみ)
- 関連レシピ + API reference へのリンク

## 制約遵守

- **LLM API 呼ばない**: production code に anthropic / openai / google.generativeai の import を一切追加していない。Recipe 内の Python コード例は customer 側の LLM 呼び出しサンプル (R19/R20) で、jpcite サーバーは 1 行も叩かない。
- **一次資料 URL のみ**: 各 recipe は portal.monodukuri-hojo.jp / www.tokyo-kosha.or.jp / www.nta.go.jp / chusho.meti.go.jp など一次資料 URL のみを引用例に使用。アグリゲータ (noukaweb 等) は登場させない。
- **¥3/req 不変**: コスト計算は全て ¥3 (税込 ¥3.30) ベース。tier 別料金や seat fee に言及していない。
- **pre-commit hook 通過**: mkdocs build --strict + (commit step で) pre-commit hooks が走る。

## 検証

```bash
.venv/bin/mkdocs build --strict
# → INFO -  Documentation built in 1.98 seconds (warnings: 0)
```

## 残課題 (out of scope)

- W2-6 outline の残り 18 recipe (Category 1-6 中の R04-R08 / R12-R15 / R22-R30) は今回未着手。
- `scripts/cookbook_smoke.py` (W2-6 §7 の検証 hook) は未作成。30 endpoint 全 smoke は別 wave で。
- `docs/prompt_cookbook.md` 冒頭の cross-ref ("dev-first 12 scripts は cookbook/index.md を参照") は未追加。次 wave で artifact split を明示する想定。
