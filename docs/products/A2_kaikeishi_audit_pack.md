# A2 — 会計士監査調書 Pack

> 1 MCP call で「監査調書 (workpaper) draft」をまるごと返す paid product. 4 セクション workpaper + J-SOX 5 軸 内部統制評価 + 重要事項 + サンプリング推奨 + 監査意見 4 区分 draft + 3 リスク評価 を deterministic に組み立てる. NO LLM. Scaffold-only.

## このプロダクトが解決する痛み

公認会計士の監査調書作成は、 (1) リスク評価 (Risk Assessment) — 業界 + 規模 + 地域ベンチマーク、 (2) 統制テスト — J-SOX 5 軸の運用評価、 (3) 実証手続 — サンプリング件数 + 信頼水準計算、 (4) 監査意見 4 区分判定 — の 4 軸を毎決算 1 法人あたり 10-20 時間かけて積み上げる作業です. Opus 4.7 で同等の調書 skeleton を生成しようとすると、token 量が膨らんで 1 法人あたり **¥5,000-15,000 の LLM cost**, さらに hallucination が §47条の2 (公認会計士法) 違反のすぐ隣にあります.

A2 は「LLM を一切経由せず、監査基準準拠の調書 skeleton + 4 区分意見 draft + J-SOX 5 軸 + サンプリング推奨 をワンショットで返す」paid product です. **¥200 / req** で 1 法人 1 監査期分の workpaper draft が手に入ります.

## MCP tool

```python
await client.call_tool(
    "product_audit_workpaper_pack",
    {
        "houjin_bangou": "1234567890123",
        "fiscal_year": 2026,
        "audit_type": "年次",  # or "四半期" or "レビュー"
    },
)
```

### 入力

| field | type | required | description |
| --- | --- | --- | --- |
| `houjin_bangou` | str (13 桁) | optional | 法人番号. 空文字なら skeleton mode. |
| `fiscal_year` | int (2000-2100) | required | 監査対象期 (西暦). |
| `audit_type` | str | required | `年次` / `四半期` / `レビュー` の 3 区分. |

### 出力 (主要フィールド)

| field | type | description |
| --- | --- | --- |
| `workpaper_skeleton` | list[4] | リスク評価 / 統制テスト / 実証手続 / 結論 の 4 セクション skeleton. |
| `internal_control_evaluation` | dict | J-SOX 5 軸 (権限分離 / 自動化 / モニタリング / リスク評価 / 報告). |
| `materiality_items` | list[3-4] | KAM (重要監査事項). 年次は税効果会計も追加. |
| `sampling_recommendation` | dict | サンプル件数 + 信頼水準 + 母集団下限. |
| `audit_opinion_draft` | dict | 4 区分 (無限定適正 / 限定付 / 不適正 / 意見不表明) draft 文面. |
| `risk_assessment` | dict | 固有 / 統制 / 発見 の 3 リスク軸. |
| `segment_view` | dict | N7 業界 (JSIC × size_band × prefecture) risk benchmark. |
| `amendment_alerts` | list | 直近 365 日の N6 改正影響. |
| `reasoning_chains` | list | N3 三段論法 (corporate_tax + commerce + labor 上位 5 件). |
| `billing` | dict | ¥200/req + value_proxy. |
| `_disclaimer` | str | §47条の2 / 会計士 / 監査基準 anchor. |

### サンプリング推奨 (監査タイプ別)

監査・保証実務委員会報告 第90号 に基づく属性サンプリングの標準値:

| audit_type | sample_size_baseline | confidence_level | tolerable_error_rate |
| --- | --- | --- | --- |
| 年次 | 60 | 0.95 | 0.05 |
| 四半期 | 25 | 0.90 | 0.08 |
| レビュー | 15 | 0.80 | 0.08 |

実際のサンプル件数は 母集団 / 過去誤謬率 / 統制依拠度 で再計算必須.

### Pricing (Tier D)

* **Per-call**: ¥200 / req (税抜).
* **Value proxy**: 同等成果物を Claude Opus 4.7 で生成すると ¥5,000-15,000 の LLM cost. jpcite は deterministic 計算で **96-98.7% saving**.

## 内部 lane composition

A2 は 3 個の moat lane を 1 リクエスト内で fan-out します:

* **HE-2** `prepare_implementation_workpaper(artifact_type='kansa_chosho')` — workpaper template.
* **N3** `walk_reasoning_chain(category='corporate_tax|commerce|labor')` — 三段論法 anchor list.
* **N7** `get_segment_view(jsic_major × size_band × prefecture)` — 業界 risk benchmark (法人番号から自動解決).

## 監査タイプ別の特例

* **年次** (annual statutory audit) — 4 セクション full + tax_provision (税効果会計) を KAM に追加.
* **四半期** (quarterly review under 金商法) — 同じ 4 セクションだが信頼水準を 90% に縮小.
* **レビュー** (interim review / voluntary engagement) — 実証手続セクションは「質問 + 分析的手続」に書き換え.

## 法的免責 (Critical)

* **公認会計士法 §47条の2** — 監査意見の表明 (監査報告書の作成、提出) は公認会計士の独占業務. 本 product は **scaffold + retrieval のみ** を提供し、最終 意見 + 監査報告書 は会計士が独立性要件を満たした上で署名する必要があります.
* **監査基準 (財務諸表監査の基準)** — リスク評価 / 統制テスト / 実証手続 / 意見形成 のすべての判断は会計士判断必須.
* **独立性要件** — 監査人の独立性 (Independence in Fact / Independence in Appearance) は本 product では検証していません. 会計士事務所側で別途確認してください.
* **J-SOX 評価範囲** — 重要勘定 + 重要拠点 + 決算財務報告プロセス + IT 全社統制 の限定範囲は会計士判断で決定.
* **一次資料確認** — 監査基準 / 監査・保証実務委員会報告 / 企業会計審議会公表物 で再検証必須.

## NO LLM 保証

本 product は **LLM 推論を一切実行しません**. 構造化された 監査調書 skeleton + N3 / N7 retrieval の合成のみで draft を生成しています. CI guard `tests/test_no_llm_in_production.py` が `anthropic` / `openai` / `google.generativeai` の import を検知して red 化します.

## サンプルレスポンス (skeleton mode, 抜粋)

```json
{
  "tool_name": "product_audit_workpaper_pack",
  "schema_version": "product.a2.v1",
  "primary_result": {
    "status": "ok",
    "product_id": "A2",
    "is_skeleton": true,
    "audit_type": "年次"
  },
  "workpaper_skeleton": [
    {"section_id": "ra", "section_name": "リスク評価 (Risk Assessment)", "citation_anchor": [...]},
    {"section_id": "ct", "section_name": "統制テスト (Tests of Controls)", "citation_anchor": [...]},
    {"section_id": "st", "section_name": "実証手続 (Substantive Procedures)", "citation_anchor": [...]},
    {"section_id": "cn", "section_name": "結論 (Conclusion)", "citation_anchor": [...]}
  ],
  "internal_control_evaluation": {
    "framework": "J-SOX (財務報告に係る内部統制の評価及び監査の基準)",
    "axes": [
      {"axis_id": "permission_separation", "axis_name_ja": "権限分離 (Segregation of Duties)", ...},
      {"axis_id": "automation", ...},
      {"axis_id": "monitoring", ...},
      {"axis_id": "risk_assessment", ...},
      {"axis_id": "reporting", ...}
    ]
  },
  "sampling_recommendation": {
    "audit_type": "年次",
    "sampling_method": "属性サンプリング (Attribute Sampling)",
    "confidence_level": 0.95,
    "tolerable_error_rate": 0.05,
    "sample_size_baseline": 60
  },
  "audit_opinion_draft": {
    "opinion_classification_options": [
      "無限定適正意見",
      "限定付適正意見",
      "不適正意見",
      "意見不表明"
    ],
    "drafts": {...}
  },
  "billing": {
    "tier": "D",
    "price_per_req_jpy": 200,
    "value_proxy": {
      "llm_equivalent_low_jpy": 5000,
      "llm_equivalent_high_jpy": 15000,
      "saving_low_pct": 98.7,
      "saving_high_pct": 96.0
    }
  },
  "_disclaimer": "..."
}
```

## 関連 product

* [A1 — 税理士月次決算 Pack](A1_zeirishi_monthly_pack.md) — 月次決算 draft (¥1,000/req or ¥100/法人/月).

## 内部 design doc

* `/Users/shigetoumeda/jpcite/docs/_internal/MOAT_PRODUCT_A1_A2_2026_05_17.md` — A1/A2 設計 + Tier-D pricing + Lane composition.
