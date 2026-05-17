# A1 — 税理士月次決算 Pack

> 1 MCP call で「月次決算 draft」をまるごと返す paid product. 損益計算書 + 仕訳 + 課税仕入計算 + 改正対応指示 + warning を deterministic に組み立てる. NO LLM. Scaffold-only.

## このプロダクトが解決する痛み

税理士の月次決算は、(1) 当月仕訳の集計、(2) 課税区分の判定、(3) 直近の通達 / 法令改正の反映、(4) 翌月源泉所得税納付期限の確認 — の 4 軸を毎月毎月 5-10 法人 × 30 分かけて手作業で行う作業の繰り返しが現実です. AI 経由で完全自動化しようとすると、LLM の hallucination リスクが §52 (税理士法) 違反のすぐ隣にあり、しかも Opus 4.7 経由で同等の draft を作らせると 1 法人あたり ¥3,000-15,000 の LLM cost が積み上がります.

A1 は「LLM を経由せず、決定的に法定要件を満たした月次決算 scaffold をワンショットで返す」ことを目的にした paid product です. 1 法人 1 ヶ月分の draft が **¥1,000 / req** または **¥100 / houjin / 月** (購読制) で得られます.

## MCP tool

```python
await client.call_tool(
    "product_tax_monthly_closing_pack",
    {
        "houjin_bangou": "1234567890123",
        "fiscal_year": 2026,
        "month": 5,
    },
)
```

### 入力

| field | type | required | description |
| --- | --- | --- | --- |
| `houjin_bangou` | str (13 桁) | optional | 法人番号. 空文字なら skeleton mode (構造だけ返す). |
| `fiscal_year` | int (2000-2100) | required | 会計期 (西暦). |
| `month` | int (1-12) | required | 月. |

### 出力 (主要フィールド)

| field | type | description |
| --- | --- | --- |
| `profit_loss` | list[13] | 損益計算書 skeleton (510 売上 〜 920 当期純利益). amount = `None` (operator fill). |
| `journal_entries` | list[5] | 仕訳 template (売上 / 仕入 / 給与 / 社保 / 家賃). |
| `consumption_tax_calc` | dict | 課税仕入計算 (10% / 8% / 非課税 / 不課税 4 バケット). |
| `amendment_alerts` | list | 直近 90 日の N6 改正影響 alert. |
| `warnings` | list | high / medium / low severity の red flag. |
| `filing_window` | dict | N4 税務署 window (法人住所から自動解決). |
| `reasoning_chains` | list | N3 三段論法 anchor (corporate_tax + consumption_tax 上位 5 件). |
| `recipe` | dict | N8 `recipe_tax_monthly_closing` summary. |
| `next_actions` | list[3] | (1) operator fill / (2) verify with 税理士 / (3) submit. |
| `billing` | dict | ¥1,000/req + ¥100/月 + value_proxy. |
| `_disclaimer` | str | §52 / 税理士 / 一次資料 anchor. |

### Pricing (Tier D)

* **Per-call**: ¥1,000 / req (税抜).
* **Per-houjin subscription**: ¥100 / 法人 / 月. 1 法人につき月内何度でも再実行可能.
* **Value proxy**: 同等成果物を Claude Opus 4.7 で生成すると ¥3,000-15,000 の LLM cost. jpcite は deterministic 計算で **67-93% saving**.

## 内部 lane composition

A1 は 5 個の moat lane を 1 リクエスト内で fan-out します:

* **HE-2** `prepare_implementation_workpaper(artifact_type='gessji_shiwake')` — テンプレート + portfolio + reasoning + window + alert を合成.
* **N3** `walk_reasoning_chain(category='corporate_tax|consumption_tax')` — 三段論法 anchor list.
* **N4** `find_filing_window(kind='tax_office')` — 税務署 window 解決.
* **N6** `am_amendment_alert_impact` — 法人毎の 90 日改正 alert.
* **N8** `recipe_tax_monthly_closing.yaml` — 13-step call sequence summary.

## 法的免責

* **税理士法 §52** — 税務代理 (申告書の作成、提出、税務相談) は税理士の独占業務. 本 product は **scaffold + retrieval のみ** を提供し、確定申告書 / 月次決算書を提出する責任は税理士に帰属します.
* **監査基準 (中小企業の会計に関する指針)** — 月次仕訳の妥当性 + 課税区分 + 計上時期 は税理士判断必須.
* **一次資料確認** — 仕訳科目 / 税率 / 控除区分 は必ず 国税庁告示 + e-Gov 法令 + 通達 (法基通 / 消基通) で再検証してください.

## NO LLM 保証

本 product は **LLM 推論を一切実行しません**. 構造化された 月次決算 skeleton + N3 / N6 retrieval の合成のみで draft を生成しています. CI guard `tests/test_no_llm_in_production.py` が `anthropic` / `openai` / `google.generativeai` の import を検知して red 化します.

## 関連 product

* [A2 — 会計士監査調書 Pack](A2_kaikeishi_audit_pack.md) — 監査調書 skeleton + 内部統制評価 + 監査意見 draft (¥200/req).

## 内部 design doc

* `/Users/shigetoumeda/jpcite/docs/_internal/MOAT_PRODUCT_A1_A2_2026_05_17.md` — A1/A2 設計 + Tier-D pricing + Lane composition.
