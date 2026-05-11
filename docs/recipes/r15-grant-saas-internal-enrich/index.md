---
title: "補助金 SaaS の内部 enrich"
slug: "r15-grant-saas-internal-enrich"
audience: "補助金 SaaS"
intent: "internal_enrich"
tools: ["bulk_match_programs", "get_corp_360", "list_municipal"]
artifact_type: "enrich_table.parquet"
billable_units_per_run: 5000
seo_query: "補助金 SaaS API 内部 enrich 法人 6 source"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 補助金 SaaS の内部 enrich

## 想定 user
B2B 補助金検索 SaaS / 補助金診断 SaaS / 中小企業向け資金調達プラットフォーム の開発元 (年商 ¥3-50 億規模、開発 5-30 人体制) が、自社 DB に登録された顧客企業 1,000-50,000 社の補助金マッチング結果・最新採択履歴・適格事業者状態を一括埋めて、検索 UI / レコメンド精度を上げる。月次 / 四半期で全顧客の `enrich_table` を再生成し、SaaS の `最新お知らせ` 機能 / `あなたに合う補助金 top 5` レコメンド / `事業者状態 alert` 等の機能を駆動する用途。

## 必要な前提
- jpcite API key (¥3/req、初回 3 req/IP/日無料、bulk 利用は事前 prepay 推奨)
- `X-Client-Tag` (SaaS 顧客別計上 / parent-child sub API key で内部按分)
- 法人番号バルク CSV (1,000-50,000 件)
- (推奨) 顧客の業種 (JSIC 中分類) + 所在地 + 直近売上 + 従業員数
- (推奨) Idempotency-Key ヘッダー (大量 batch の冪等性確保)

## 入力例
```json
{
  "corp_numbers": ["<法人番号 5,000 件、配列で投入>"],
  "include": ["match_top5", "adoption_5y", "invoice", "enforcement_3y"],
  "fit_score_min": 0.5,
  "client_tag": "saas-internal-2026Q2",
  "idempotency_key": "enrich-2026-05-11-v1",
  "language": "ja"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -X POST -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: saas-internal-2026Q2" \
  -H "Idempotency-Key: enrich-2026-05-11-v1" -H "Content-Type: application/json" \
  -d @bulk.json "https://api.jpcite.com/v1/enrich/bulk"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/jobs/enrich-2026-05-11-v1/status"

curl -L -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/jobs/enrich-2026-05-11-v1/result.parquet" -o enrich.parquet
```
### Python
```python
import os, time
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="saas-internal-2026Q2")
corp_numbers = open("customers.csv").read().split()
job = c.bulk_enrich_async(corp_numbers=corp_numbers,
    include=["match_top5", "adoption_5y", "invoice"],
    fit_score_min=0.5, idempotency_key="enrich-2026-05-11-v1")
while job.status not in ("done", "failed"):
    time.sleep(10)
    job = c.get_job(job.job_id)
import pandas as pd
df = pd.read_parquet(job.result_url)
df.to_parquet("internal_enrich_2026-05.parquet", compression="zstd")
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
const corps = (await Bun.file("customers.csv").text()).trim().split("\n");
const job = await jpcite.bulk_enrich_async({
  corp_numbers: corps, include: ["match_top5", "adoption_5y"],
  fit_score_min: 0.5, idempotency_key: "enrich-2026-05-11-v1",
  client_tag: "saas-internal-2026Q2",
});
const result = await jpcite.get_job_result(job.job_id);
```

## 出力例 (artifact)
```json
{
  "job_id": "enrich-2026-05-11-v1",
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://api.jpcite.com/v1/enrich/bulk",
  "content_hash": "sha256:a3f4...8c91",
  "total_corps": 5000,
  "matched_corps": 4732,
  "unmatched_corps": 268,
  "elapsed_seconds": 587,
  "result_url": "https://r2.jpcite.com/enrich/enrich-2026-05-11-v1.parquet",
  "result_format": "parquet (snappy compressed)",
  "rows_sample": [
    {
      "corp_number": "7010001234567",
      "match_top5": [{"program_id": "meti-mono-2026-r5", "fit_score": 0.82, "tier": "A"}],
      "adoption_5y": [{"program": "meti-it-2024-r3", "amount_jpy": 4500000}],
      "invoice_status": "active"
    }
  ],
  "known_gaps": ["municipal lag 7-14d", "5000 件 batch は約 10 分要 (10 req/s)"]
}
```

## known gaps
- rate-limit 10 req/s: 5,000 件 batch は約 10 分、50,000 件は約 90 分 (async + R2 直 DL 推奨)
- 自治体独自データ: 1,741 市町村のうち RSS / API 提供は 280、残り 1,461 はスクレイピング週次バッチで 7-14 日 lag
- 法人番号未付番: 個人事業主 / 任意団体は `bulk_enrich` 対象外
- fit_score の根拠: 過去 36 ヶ月の業種別採択率 + 類似企業の採択実績ベース
- enrich の更新周期: 月次が標準、自治体補助金は週次差分のみ補完、四半期に full re-enrich 推奨

## 関連 tool
- `bulk_enrich` (本 recipe の中核、async job)
- `bulk_match_programs` (個別マッチング、SaaS UI からの即時呼出)
- `get_corp_360` (個社深掘り、SaaS 詳細画面)
- `list_municipal` (自治体補助金縦覧、地域 filter 用)
- `apply_eligibility_chain_am` (排他ルールチェック、Wave 21)

## 関連 recipe
- [r09-bpo-grant-triage-1000](../r09-bpo-grant-triage-1000/) — BPO トリアージ、SaaS 化前段
- [r24-houjin-6source-join](../r24-houjin-6source-join/) — 6 source join、本 recipe の素材レイヤ
- [r25-adoption-bulk-export](../r25-adoption-bulk-export/) — 採択 bulk export、参照データの月次再生成

## billable_units 試算
- 1 batch 5,000 units × ¥3 = ¥15,000 / 月、税込 ¥16,500
- 顧客 50,000 社 月次 = ¥150,000 / 月、税込 ¥165,000
- 年 ¥1,800,000、税込 ¥1,980,000
- ROI: SaaS 顧客から ¥3,000-10,000 / 月 / 顧客 受領前提なら ¥150,000 enrich コストで 顧客 LTV 6-12 ヶ月分の上振れ効果

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- SaaS 内部の検索 UI / レコメンド / alert への利用 OK、最終出力に jpcite 出典明記
- 顧客企業向け再配布 (SaaS 経由の表示) は jpcite 出典明記の上で可
- 二次卸 (他 SaaS への ETL 出力) は別途要相談

## 業法 fence
- SaaS は情報提供のみ、申請代行 / 経営助言は資格者経由 (税理士法 §52 / 中小企業診断士 / 行政書士法 §1)
- 個別の補助金採択可能性の保証は禁止、本 recipe は統計的シグナル (fit_score) のみ提供
- 個人情報保護法 — 法人番号は対象外、代表者氏名等を扱う場合は安全管理措置
- 景表法 §5 — `fit_score` / `tier` は推定値、保証ではない旨を SaaS UI に明示
