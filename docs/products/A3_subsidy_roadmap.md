# A3 — 補助金活用ロードマップ Pack

**Price**: ¥500 / req (= 167 metered units × ¥3)
**Tool**: `product_subsidy_roadmap_12month(houjin_bangou, scope_year=12)`
**MCP envelope**: `_billing_unit = 167`, `_disclaimer` = §52 / §47条の2 / §72 / §1 / §3
**Composed lanes**: N2 portfolio + N4 application rounds + N6 amendment alerts + N7 segment view

## 何が出るのか

1 回の MCP 呼び出しで **法人番号 1 件分・12 ヶ月分の補助金活用ロードマップ** をまとめて返します。手動だと N 個の MCP 呼び出し (portfolio → 各 program の round → alert → segment view → 必要書類 → 士業マッピング → 採択確率 …) を要する作業を 1 call に圧縮、`_billing_unit = 167` で ¥501 (≈ ¥500) を 1 ledger row として記録します。

## Sample output structure

```json
{
  "tool_name": "product_subsidy_roadmap_12month",
  "product_id": "A3",
  "schema_version": "products.a3.v1",
  "primary_result": {
    "status": "ok",
    "houjin_bangou": "8010001213708",
    "scope_months": 12,
    "summary": {
      "portfolio_size": 4,
      "total_rounds_in_window": 5,
      "total_estimated_subsidy_yen": 14800000,
      "amendment_alerts": 1
    }
  },
  "months": [
    {
      "month": "2026-08",
      "month_start": "2026-08-01",
      "month_end": "2026-08-31",
      "items": [
        {
          "program_id": "P-IT-DOUNYU-2026",
          "round_label": "第1回",
          "application_open_date": "2026-06-16",
          "application_close_date": "2026-08-15",
          "announced_date": "2026-10-14",
          "disbursement_start_date": "2026-11-13",
          "budget_yen": 5000000,
          "status": "upcoming",
          "applicability_score": 0.92,
          "applied_status": "unapplied",
          "adoption_probability_estimate": 0.65,
          "expected_subsidy_yen": 3250000,
          "competitor_density_estimate": 21,
          "required_documents": [
            "登記事項証明書 (履歴事項全部証明書)",
            "決算書 (直近2期分)",
            "事業計画書",
            "見積書 / 仕様書",
            "IT 導入支援事業者 連名申請書",
            "ベンダー見積書 (IT 導入補助金 様式)"
          ],
          "related_shihou": ["行政書士", "IT 導入支援事業者"],
          "source_url": "https://example/it_dounyu"
        }
      ],
      "item_count": 1,
      "estimated_total_yen": 3250000
    }
  ],
  "aggregate": {
    "scope_months": 12,
    "total_program_rounds": 5,
    "total_estimated_subsidy_yen": 14800000,
    "avg_competitor_density": 21,
    "risk_flags": []
  },
  "houjin_attributes": {
    "jsic_major": "E",
    "size_band": "中小",
    "prefecture": "東京都",
    "address": "東京都千代田区"
  },
  "segment_summary": {
    "rows_observed": 1,
    "median_adoption_count": 21,
    "top_program_count": 40,
    "filters": {"jsic_major": "E", "size_band": "中小", "prefecture": "東京都"}
  },
  "amendment_alerts": [
    {
      "alert_id": 1,
      "amendment_diff_id": 1,
      "impact_score": 80,
      "impacted_program_ids": ["P-IT-DOUNYU-2026", "P-MONOZUKURI-2026"]
    }
  ],
  "agent_next_actions": [
    {"step": "review upcoming deadlines", "items": ["..."]},
    {"step": "subscribe to amendment alerts", "items": ["1"]},
    {"step": "engage 士業", "items": []}
  ],
  "billing": {"unit": 167, "yen": 501, "product_id": "A3"},
  "_billing_unit": 167,
  "_disclaimer": "本 response は moat lane の retrieval ... §52 / §47条の2 / §72 / §1 / §3 ..."
}
```

## 各月バケット (month bucket) のフィールド

| field | meaning |
| --- | --- |
| `month` | `YYYY-MM` |
| `items[*].program_id` | 採択候補制度 ID (autonomath canonical) |
| `items[*].application_close_date` | 公募締切 (ソート軸) |
| `items[*].budget_yen` | 公募回 予算上限 (N4 raw) |
| `items[*].adoption_probability_estimate` | applicability_score (N2) × segment 採択密度 (N7) の決定的 blend |
| `items[*].expected_subsidy_yen` | `budget_yen × adoption_probability_estimate` (期待値) |
| `items[*].required_documents` | 公募要領ベースのスキャフォールド必要書類 list |
| `items[*].related_shihou` | 関連 士業 (行政書士 / 中小企業診断士 / IT 導入支援事業者 等) |
| `items[*].competitor_density_estimate` | N7 segment view 採択件数 中央値 |

## 集約情報 (aggregate)

| field | meaning |
| --- | --- |
| `total_program_rounds` | 12 ヶ月窓内の 公募回 合計 |
| `total_estimated_subsidy_yen` | 期待獲得額 合計 (full window) |
| `avg_competitor_density` | segment 採択件数 中央値 (固定) |
| `risk_flags` | budget 不明 / 採択確率 < 0.20 等の警告 list (最大 10) |

## NO LLM 保証

- A3 は **autonomath.db の SQLite SELECT のみ** で構築されます。`anthropic` / `openai` / `google.generativeai` 等の SDK 一切インポートしません。
- 採択確率予測は **scores の決定的 blend** (65% applicability_score + 35% adoption_density、上限 0.95) で、LLM 推論ではありません。
- CI guard `tests/test_no_llm_in_production.py` が A3 module path 配下の import を強制 enforce します。

## 法律遵守 fence

| § | 対象 | A3 stance |
| --- | --- | --- |
| 税理士法 §52 | 税務代理・税務書類作成・税務相談 | scaffold-only。税務助言は含みません |
| 公認会計士法 §47条の2 | 監査証明業務 | 含みません |
| 弁護士法 §72 | 法律事件 + 法律事務 | 一般情報の retrieval、法的助言は含みません |
| 行政書士法 §1 | 官公署提出書類の作成・代理 | scaffold-only、申請代理は含みません |
| 司法書士法 §3 | 登記・供託 代理 | 含みません |

最終的な 採択 / 申請判断 / 申請書類作成 / 申請代理 / 採択後 経理処理 は **士業の確認・委任** が必須です。

## 内部設計 — composed lanes

```
N2 (am_houjin_program_portfolio)
  → top-40 priority_rank ASC programs for the houjin
N4 (am_application_round)
  → per-program rounds within today..today+(scope_months*31+5) window
N6 (am_amendment_alert_impact)
  → houjin alerts where impacted_program_ids ∩ portfolio ≠ ∅
N7 (am_segment_view)
  → jsic_major × size_band × prefecture seed for competitor density
```

呼び出し fan-out は同期 SQLite で 4-6 query / call、p99 latency 100ms 未満を目標。

## 料金マッピング

- 1 req = ¥501 (税抜) = ¥3 × 167 units
- Stripe metered billing の `usage_events` には `tool="product_subsidy_roadmap_12month"` + `unit=167` で記録されます。
- ¥3/req の anonymous quota (3 req/日) では呼べません — paid API key (or 顧問先 fan-out) 必須。

## エラーパス

| status | 意味 |
| --- | --- |
| `ok` | 通常の 12 ヶ月ロードマップ |
| `no_portfolio` | houjin の portfolio が ETL 未着 (N2 row 0 件) |
| `db_unavailable` | autonomath.db が見えない (paths.runtime mismatch) |

いずれの場合も `_billing_unit` は 167 のまま — エラーでも ¥500 は課金されます (heavy compose の固定費)。
