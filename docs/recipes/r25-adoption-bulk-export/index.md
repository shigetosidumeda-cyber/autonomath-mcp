---
title: "採択 bulk export"
slug: "r25-adoption-bulk-export"
audience: "SaaS / リサーチャー"
intent: "adoption_bulk_export"
tools: ["list_adoptions", "search_programs", "get_corp_360"]
artifact_type: "adoptions_export.parquet"
billable_units_per_run: 200
seo_query: "採択事例 bulk export 補助金 jPubs"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 採択 bulk export

## 想定 user
補助金 SaaS / 中小企業診断士事務所 / 大学院政策研究室 / シンクタンク / 経営コンサル会社で、補助金別の採択事例 (現状 2,286 件) を月次 / 四半期で bulk export し、自社 DB の `cases` テーブルや分析ノートブックに取り込む層。本 recipe は最も網羅性が高い endpoint で、program_id 別 / 業種別 / 都道府県別 / 採択日別の filter + parquet / JSON / CSV 出力に対応。年次レポート / 競合分析 / 業界動向把握の素材として使う。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料)
- `X-Client-Tag` (用途別計上)
- 抽出条件 (program_id list / 業種 / 都道府県 / 採択日 range)
- (推奨) `Idempotency-Key` (bulk batch の冪等性確保)

## 入力例
```json
{
  "program_ids": ["meti-mono-2024-r2", "meti-it-2024-r3"],
  "industry_jsic": ["E", "G"],
  "prefectures": ["東京都", "埼玉県", "神奈川県"],
  "adopted_date_after": "2024-04-01",
  "adopted_date_before": "2026-04-01",
  "format": "parquet",
  "client_tag": "research-2026Q2"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -X POST -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: research-2026Q2" \
  -H "Content-Type: application/json" \
  -d '{"program_ids":["meti-mono-2024-r2"],"industry_jsic":["E"],"prefectures":["東京都"],"format":"parquet"}' \
  "https://api.jpcite.com/v1/adoptions/bulk_export"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/jobs/{job_id}/result.parquet" -o adoptions.parquet
```
### Python
```python
import os
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="research-2026Q2")
job = c.bulk_export_adoptions(
    program_ids=["meti-mono-2024-r2", "meti-it-2024-r3"],
    industry_jsic=["E", "G"], prefectures=["東京都", "埼玉県"],
    adopted_date_after="2024-04-01", adopted_date_before="2026-04-01",
    format="parquet",
)
import pandas as pd
df = pd.read_parquet(job.result_url)
print(f"{len(df)} 件採択、出典: {df['source_url'].nunique()} ユニーク")
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
const job = await jpcite.bulk_export_adoptions({
  program_ids: ["meti-mono-2024-r2"], industry_jsic: ["E"],
  prefectures: ["東京都"], format: "parquet",
  client_tag: "research-2026Q2",
});
console.log(`採択 ${job.row_count} 件、URL: ${job.result_url}`);
```

## 出力例 (artifact)
```json
{
  "job_id": "adoption-export-2026-05-11",
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://www.chusho.meti.go.jp/.../adoption_list.pdf",
  "content_hash": "sha256:f2a3...8c91",
  "filter": {
    "program_ids": ["meti-mono-2024-r2"],
    "industry_jsic": ["E"],
    "prefectures": ["東京都"],
    "adopted_date_after": "2024-04-01",
    "adopted_date_before": "2026-04-01"
  },
  "row_count": 1247,
  "result_url": "https://r2.jpcite.com/adoptions/2026-05-11.parquet",
  "result_format": "parquet (snappy compressed, 8.3MB)",
  "sample_rows": [
    {"program_id": "meti-mono-2024-r2", "corp_number": "7010001234567",
     "name": "サンプル製作所(株)", "amount_jpy": 12000000, "adopted_at": "2024-09-15",
     "industry_jsic": "E29", "prefecture": "東京都"}
  ],
  "known_gaps": ["市町村補助金の採択は対象外", "個別事業計画書本文は別契約"]
}
```

## known gaps
- 市町村補助金の採択は対象外 (中央 + 都道府県 + 政令市まで)
- 個別事業計画書本文は別契約 (情報公開請求 / 公庫の個別開示)
- 採択時点の corpus snapshot で固定、後日の取下げ / 辞退情報は反映遅延あり
- 法人番号未付番の任意団体は捕捉不能
- 採択公表の HTML 改編で約 5-8% リンク切れ、sentinel 化済

## 関連 tool
- `list_adoptions` (本 recipe 中核、bulk export)
- `search_programs` (program_id 候補絞込)
- `get_corp_360` (採択企業の 360 度ビュー)
- `get_program_detail` (program 原文)

## 関連 recipe
- [r07-shindanshi-monthly-companion](../r07-shindanshi-monthly-companion/) — 診断士月次伴走、類似採択事例参照
- [r09-bpo-grant-triage-1000](../r09-bpo-grant-triage-1000/) — BPO トリアージ、優先架電基準
- [r24-houjin-6source-join](../r24-houjin-6source-join/) — 法人 6 source join

## billable_units 試算
- 1 batch 200 units × ¥3 = ¥600 / 月
- 月 5 batch (program 別 / 業種別) = ¥3,000 / 月、税込 ¥3,300
- 年 ¥36,000 / 年、税込 ¥39,600
- 節約 (純 LLM vs jpcite 標準従量料金): 月 5 batch × 200 cycle で、純 LLM は約 ¥10,000/月 (1 batch cycle ¥2,000 = bulk fetch 200 record + filter) に対し jpcite は ¥3,000/月 (1,000 req × ¥3) → 節約 約 ¥7,000/月 / batch あたり ¥1,400 (cf. `docs/canonical/cost_saving_examples.md` case 5 同系)

## 商業利用条件
- PDL v1.0 + CC-BY-4.0、出典明記必須
- リサーチャー / SaaS / 経営コンサルの分析資料への組込可、jpcite 出典明記
- 採択企業 (法人) 名は公知情報、信用毀損につながる解釈は避ける
- 二次卸 (他 SaaS への ETL 出力) は別途要相談

## 業法 fence
- 公開資料の再配布は出典明記で OK
- 個別事業計画書本文は情報公開請求対象、本 recipe 対象外
- 中小企業診断士 / 認定支援機関 ロールの業務範囲内で利用
- 景表法 §5 — 統計分析結果は事実列挙、推測 / 評価表現は避ける
