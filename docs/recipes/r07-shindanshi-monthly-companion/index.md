---
title: "中小企業診断士の月次伴走"
slug: "r07-shindanshi-monthly-companion"
audience: "中小企業診断士"
intent: "monthly_companion"
tools: ["search_programs", "get_corp_360", "apply_eligibility_chain_am", "bundle_application_kit"]
artifact_type: "companion_log.md"
billable_units_per_run: 14
seo_query: "中小企業診断士 経営革新 補助金 伴走 認定支援機関"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 中小企業診断士の月次伴走

## 想定 user
認定経営革新等支援機関ロールを持つ中小企業診断士 (1 人事務所〜30 人法人) で、顧問先 30-80 社の月次伴走を行う。各社の業種 × 都道府県 × 設備投資計画 × 経営状況から該当制度を当てる工数を本 recipe で 1 社 5 分以内に圧縮し、`find_complementary_programs_am` + `apply_eligibility_chain_am` + `forecast_program_renewal` で 補完候補 + 排他 chain + 来期更新確度を 3 req で取得、その後 `bundle_application_kit` で 申請 scaffold を assemble する。月次レビュー + 個社診断 + 提案 kit の 3 phase を 1 セッションで完結。

## 必要な前提
- jpcite API key (¥3/req、初回 3 req/IP/日無料)
- `X-Client-Tag` (顧問先別計上、認定支援機関 ID 連動)
- 顧問先 法人番号 + 業種 + 都道府県 + 直近売上 + 従業員数
- (推奨) `saved_searches.profile_ids` (mig 097) 事前登録で月次 fan-out 自動化
- (推奨) 過去 3 年の採択履歴 + 重複申請禁止条項のチェック用

## 入力例
```json
{
  "corp_number": "7010001234567",
  "industry_jsic": "E",
  "prefecture": "埼玉県",
  "revenue_jpy": 350000000,
  "employees": 42,
  "capex_plan_jpy": 15000000,
  "top_n": 5,
  "include_chain": true,
  "include_renewal_forecast": true,
  "client_tag": "shindan-2026Q2"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -X POST -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: shindan-2026Q2" \
  -H "Content-Type: application/json" \
  -d '{"revenue_jpy":350000000,"employees":42,"industry_jsic":"E","prefecture":"埼玉県","capex_plan_jpy":15000000,"top_n":5}' \
  "https://api.jpcite.com/v1/programs/prescreen"

curl -X POST -H "X-API-Key: $JPCITE_API_KEY" -H "Content-Type: application/json" \
  -d '{"program_ids":["meti-mono-2026-r5","saitama-dx-2026"]}' \
  "https://api.jpcite.com/v1/programs/eligibility_chain"
```
### Python
```python
import os
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="shindan-2026Q2")
matches = c.prescreen_programs(
    revenue_jpy=350000000, employees=42, industry_jsic="E",
    prefecture="埼玉県", capex_plan_jpy=15000000, top_n=5,
)
chain = c.eligibility_chain([m.program_id for m in matches[:3]])
kit = c.bundle_application_kit(program_id=matches[0].program_id, corp_number="7010001234567")
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
const matches = await jpcite.prescreen_programs({
  revenue_jpy: 350000000, employees: 42, industry_jsic: "E",
  prefecture: "埼玉県", capex_plan_jpy: 15000000, top_n: 5,
  client_tag: "shindan-2026Q2",
});
const kit = await jpcite.bundle_application_kit({
  program_id: matches[0].program_id, corp_number: "7010001234567",
});
```

## 出力例 (artifact)
```json
{
  "corp_number": "7010001234567",
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://api.jpcite.com/v1/programs/prescreen",
  "candidates": [
    {"program_id": "METI-MONOZUKURI-2026", "name": "ものづくり補助金 第18次",
     "fit_score": 0.87, "subsidy_rate": "1/2", "max_amount_jpy": 12500000,
     "tier": "S", "source_url": "https://portal.monodukuri-hojo.jp/..."}
  ],
  "eligibility_chain": [
    {"step": 1, "rule": "中小企業者の範囲", "passed": true},
    {"step": 2, "rule": "認定経営革新等支援機関 確認書", "passed": true},
    {"step": 3, "rule": "過去 3 年採択履歴", "passed": true}
  ],
  "exclusions": [],
  "renewal_forecast": {"prob": 0.78, "next_round_estimate": "2026-09"},
  "application_kit": {
    "documents": ["事業計画書", "見積書", "賃上げ計画", "認定支援機関確認書"],
    "estimated_prep_hours": 8
  },
  "client_tag": "shindan-2026Q2",
  "known_gaps": ["市町村独自分は対象外"]
}
```

## known gaps
- 認定経営革新等支援機関の業務範囲外の助言は対象外、本 recipe は scaffold + 一次 URL まで
- 採択確率は過去採択率ベースの推定、保証ではない
- 申請書面 (事業計画書 / 経営革新計画申請書) の自動生成は行政書士法 §1 で fence、scaffold のみ
- `industry_jsic` 1 文字 (E=製造業) 必須、サブ分類は別 input
- 排他ルール 181 件は逐次拡充、新規制度の排他は 30 日 lag

## 関連 tool
- `prescreen_programs` (本 recipe 中核、5 input → top_n 候補)
- `find_complementary_programs_am` (補完候補、Wave 21)
- `apply_eligibility_chain_am` (排他 chain、Wave 21)
- `forecast_program_renewal` (来期更新確度、Wave 22)
- `bundle_application_kit` (申請 kit assembly、Wave 22)

## 関連 recipe
- [r01-tax-firm-monthly-review](../r01-tax-firm-monthly-review/) — 税理士月次、税制控除との連動
- [r02-pre-closing-subsidy-check](../r02-pre-closing-subsidy-check/) — 決算前最終チェック
- [r24-houjin-6source-join](../r24-houjin-6source-join/) — 法人 6 source join

## billable_units 試算
- 1 顧問先 14 units (prescreen 5 + chain 3 + forecast 1 + kit 5) × ¥3 = ¥42 / 顧問先 / 月
- 顧問先 50 社 = ¥2,100 / 月、税込 ¥2,310
- 顧問先 80 社 (上位事務所) = ¥3,360 / 月、税込 ¥3,696
- ROI: 補助金提案 1 件取りこぼし回避 (¥30-100 万報酬 + 顧問契約 (¥5-15 万/月) 解約 = ¥60-180 万/年) で 185-555 倍

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- 月次レポート / 顧問先伴走資料への組込 OK、jpcite + 中企庁 / 経産省出典の両明記
- 認定支援機関 ID + X-Client-Tag を付与で事務所内利用扱い

## 業法 fence
- 中小企業診断士登録規則 — 経営助言の業務範囲内
- 行政書士法 §1 — 申請書面作成は行政書士、本 recipe は kit assembly (scaffold) まで
- 税理士法 §52 — 税務代理は税理士、補助金会計処理は税理士連携
- 弁護士法 §72 — 法的紛争予測は弁護士
- 景表法 §5 — `fit_score` / `renewal_forecast` は推定値、保証ではない

## canonical_source_walkthrough

> 一次資料 / canonical source への walk-through。Wave 21 C6 で全 30 recipes に追加。

### 使う tool
- **MCP tool**: `smb_starter_pack + subsidy_roadmap_3yr`
- **REST endpoint**: `/v1/discover/smb_starter + /v1/programs/roadmap`
- **jpcite.com docs**: <https://jpcite.com/recipes/r07-shindanshi-monthly-companion/>

### expected output
- JSON: starter_programs[5] + roadmap.year_1/2/3 + total_addressable_amount_jpy
- 全 response に `fetched_at` (UTC ISO 8601) + `source_url` (一次資料 URL) 必須
- `_disclaimer` envelope (税理士法 §52 / 行政書士法 §1 / 司法書士法 §3 / 弁護士法 §72 等の業法 fence 該当時)

### 失敗時 recovery
- **404 Not Found**: 中小企業診断士領域外 keyword — 行政書士 / 税理士 fence へ案内
- **429 Too Many Requests**: Client-Tag client-{id} fan-out
- **5xx / timeout**: 60s wait

### canonical source (一次資料)
- 国税庁 適格事業者公表サイト: <https://www.invoice-kohyo.nta.go.jp/>
- 中小企業庁 補助金一覧: <https://www.chusho.meti.go.jp/>
- e-Gov 法令検索: <https://laws.e-gov.go.jp/>
- 国立国会図書館 NDL: <https://www.ndl.go.jp/>
- jpcite 一次資料 license 表: <https://jpcite.com/legal/licenses>
