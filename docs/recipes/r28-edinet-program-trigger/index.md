---
title: "EDINET 連動の補助金 trigger"
slug: "r28-edinet-program-trigger"
audience: "IR / 営業企画"
intent: "edinet_program_trigger"
tools: ["search_edinet", "search_programs", "get_corp_360"]
artifact_type: "edinet_trigger.json"
billable_units_per_run: 12
seo_query: "EDINET 補助金 連動 上場会社 IR トリガー"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# EDINET 連動の補助金 trigger

## 想定 user
上場会社の IR 部 / 経営企画部 / コーポレート部 / SaaS の営業企画部で、EDINET 適時開示 (有価証券報告書 / 四半期報告書 / 臨時報告書 / 大量保有報告書 / 自己株券買付状況) の重要事実発生を trigger に、対象会社の関連補助金候補 + 業種別動向 + 競合分析を 5 分で出す運用。M&A・組織再編・新規事業の機会探索 / 公共調達への参入機会発見 / 上場準備 (J-Adviser) の補助金活用 等で使う。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料)
- EDINET コード (5 桁、上場会社) or 法人番号 (13 桁)
- (任意) 監視業種フィルタ (JSIC 中分類)
- (任意) 重要事実分類 (M&A / 組織再編 / 新規事業 / 増資 / 配当 / etc.)
- Cron 環境 (週次 / 日次)

## 入力例
```json
{
  "edinet_codes": ["E12345", "E67890"],
  "corp_numbers": ["7010001234567"],
  "watch_facts": ["m_and_a", "new_business", "capital_increase", "delisting_threat"],
  "include_program_match": true,
  "lookback_days": 7,
  "client_tag": "ir-2026Q2"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: ir-2026Q2" \
  "https://api.jpcite.com/v1/edinet/E12345/material_facts?lookback=7"

curl -X POST -H "X-API-Key: $JPCITE_API_KEY" -H "Content-Type: application/json" \
  -d '{"edinet_codes":["E12345"],"watch_facts":["m_and_a","new_business"],"include_program_match":true}' \
  "https://api.jpcite.com/v1/edinet/trigger"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/corp/7010001234567/360?include=adoption,enforcement,edinet&lookback_years=3"
```
### Python
```python
import os
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="ir-2026Q2")
triggers = c.edinet_trigger(
    edinet_codes=["E12345", "E67890"],
    watch_facts=["m_and_a", "new_business", "capital_increase"],
    include_program_match=True, lookback_days=7,
)
for t in triggers.events:
    print(f"[{t.edinet_code}] {t.fact_type}: {t.summary}")
    for p in t.program_matches[:3]:
        print(f"  - {p.program_id}: {p.fit_score:.2f} (出典: {p.source_url})")
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
const triggers = await jpcite.edinet_trigger({
  edinet_codes: ["E12345", "E67890"],
  watch_facts: ["m_and_a", "new_business"],
  include_program_match: true, lookback_days: 7,
  client_tag: "ir-2026Q2",
});
console.log(`${triggers.events.length} 件の trigger 検知`);
```

## 出力例 (artifact)
```json
{
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://disclosure.edinet-fsa.go.jp/...",
  "scanned_period": "2026-05-04 to 2026-05-11",
  "events": [
    {
      "edinet_code": "E12345",
      "corp_number": "7010001234567",
      "fact_type": "m_and_a",
      "summary": "子会社化に関するお知らせ (XXX 株式会社の株式取得)",
      "disclosed_at": "2026-05-08T15:30:00+09:00",
      "doc_url": "https://disclosure.edinet-fsa.go.jp/.../doc.pdf",
      "program_matches": [
        {"program_id": "meti-ma-2026-r3", "fit_score": 0.78,
         "name": "事業承継・M&A 補助金", "tier": "A",
         "source_url": "https://portal.shoukei.go.jp/..."}
      ]
    }
  ],
  "client_tag": "ir-2026Q2",
  "known_gaps": ["EDINET 開示は上場会社のみ", "重要事実分類は xbrl タグ依存"]
}
```

## known gaps
- EDINET 開示は上場会社 + 大量開示書類提出者のみ、非上場中小は対象外
- 重要事実分類は xbrl タグ依存、新規 / 拡充された分類は jpcite 側の mapping 更新 1-2 週間 lag
- M&A 関連の補助金マッチは事業承継・M&A 補助金等の中央分のみ、自治体独自 M&A 支援は別系統
- インサイダー情報の取扱は上場会社内部ルール準拠、本 recipe は公開情報のみ
- 子会社・関連会社の重要事実は親会社 EDINET 開示のみ、子会社個別の補助金マッチは別 query

## 関連 tool
- `search_edinet` (EDINET 開示書類検索、重要事実の取得)
- `search_programs` (補助金マッチ)
- `get_corp_360` (法人 360 度ビュー)
- `edinet_trigger` (本 recipe 中核、適時開示 + 補助金マッチ)

## 関連 recipe
- [r03-sme-ma-public-dd](../r03-sme-ma-public-dd/index.md) — M&A DD、EDINET 重要事実の DD への組込
- [r12-audit-firm-kyc-sweep](../r12-audit-firm-kyc-sweep/index.md) — 監査法人 KYC、重要事実 axis
- [r24-houjin-6source-join](../r24-houjin-6source-join/index.md) — 法人 6 source join、EDINET 含む

## billable_units 試算
- 1 batch 12 units × ¥3 = ¥36 / 週
- 月 4 週 = ¥144 / 月、税込 ¥158
- 監視会社 100 社 = ¥1,200 / 月、税込 ¥1,320
- API fee delta: 監視会社 100 社 × 月 4 週 trigger で、外部 model/search API fee は約 ¥3,500/月 (1 batch cycle ¥875 = EDINET fetch + program link 推論) に対し jpcite は ¥1,200/月 (400 req × ¥3) → API fee delta 約 ¥2,300/月 / 監視会社あたり ¥23 (cf. `docs/canonical/cost_saving_examples.md` case 2 同系)

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- 公開資料 (EDINET 適時開示) の再配布は出典明記で OK
- IR レポート / 経営企画資料への組込可、jpcite + EDINET 出典の両明記
- インサイダー情報の取扱は上場会社内部ルール準拠

## 業法 fence
- 金融商品取引法 (EDINET 重要事実の取扱は社内ルール準拠、インサイダー判断は対象企業 IR 担当)
- 公認会計士法 — 監査意見そのものは jpcite 不可、scaffold + 一次 URL のみ
- 弁護士法 §72 — 法的判断は弁護士、本 recipe は事実通知層
- 景表法 §5 — `fit_score` は推定値、保証ではない旨を IR 資料末尾に注記推奨
