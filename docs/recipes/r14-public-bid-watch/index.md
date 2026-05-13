---
title: "営業企画の公共入札 watch"
slug: "r14-public-bid-watch"
audience: "営業企画"
intent: "public_bid_watch"
tools: ["search_bids", "get_corp_360", "list_adoptions"]
artifact_type: "bid_digest.csv"
billable_units_per_run: 20
seo_query: "公共入札 watch 営業 自治体 国 落札"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 営業企画の公共入札 watch

## 想定 user
官公庁向けに SaaS / コンサル / 物品 / 工事を提供する企業 (年商 ¥1-100 億規模) の営業企画部・公共事業部マネージャー。中央省庁 + 47 都道府県 + 20 政令市 + 中核市の入札公告 (官報 / 各省 portal / KKJ / 都道府県 e-入札) を毎朝ダイジェスト形式で受け取り、関心キーワード (例: クラウド / RPA / コンサルティング / IT 機器 / 翻訳) と最低額 (例: ¥500 万以上) でフィルタした案件一覧を営業担当へ配信する。落札結果も同時に縦覧し、競合落札社の動向を四半期レポートに反映する用途。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料)
- `X-Client-Tag` ヘッダー (営業案件別 / 担当別 の billable 計上)
- 関心キーワード (3-10 個程度、AND / OR 指定可) + 入札規模下限 (¥0-1B)
- (任意) 競合企業の法人番号 list (落札動向 watch 用、5-30 社)
- (推奨) 業種コード (JSIC 中分類) + 地域フィルタ (都道府県 / 国 / 自治体区分)

## 入力例
```json
{
  "keywords": ["クラウド", "コンサルティング", "RPA"],
  "min_amount_jpy": 5000000,
  "max_amount_jpy": 500000000,
  "regions": ["national", "tokyo", "kanagawa", "osaka"],
  "deadline_within_days": 30,
  "exclude_competitors": ["8010001234568"],
  "client_tag": "sales-2026Q2"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: sales-2026Q2" \
  "https://api.jpcite.com/v1/bids/search?kw=クラウド,コンサル&min=5000000&within=30&region=national,tokyo"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/bids/kkj-2026-05-001"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/corp/8010001234568/bid_history?lookback_years=3"
```
### Python
```python
import os, csv
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="sales-2026Q2")
bids = c.search_bids(keywords=["クラウド", "コンサルティング", "RPA"],
    min_amount_jpy=5000000, deadline_within_days=30,
    regions=["national", "tokyo", "kanagawa"])
with open("bid_digest.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["bid_id", "issuer", "deadline", "max_amount_jpy", "spec_url"])
    for b in bids:
        w.writerow([b.bid_id, b.issuer, b.deadline, b.max_amount_jpy, b.spec_url])
print(f"{len(bids)} 件抽出")
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
import fs from "node:fs";
const bids = await jpcite.search_bids({
  keywords: ["クラウド", "コンサルティング"],
  min_amount_jpy: 5000000, deadline_within_days: 30,
  regions: ["national", "tokyo"], client_tag: "sales-2026Q2",
});
const csv = ["bid_id,issuer,deadline,max_amount_jpy,spec_url"];
for (const b of bids) {
  csv.push(`${b.bid_id},${b.issuer},${b.deadline},${b.max_amount_jpy},${b.spec_url}`);
}
fs.writeFileSync("bid_digest.csv", csv.join("\n"));
```

## 出力例 (artifact)
```json
{
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://www.kkj.go.jp/...",
  "matched_bids": 18,
  "bids": [
    {
      "bid_id": "kkj-2026-05-001",
      "issuer": "総務省",
      "title": "クラウドサービス基盤運用支援",
      "deadline": "2026-06-10",
      "max_amount_jpy": 12000000,
      "spec_url": "https://www.kkj.go.jp/.../001.pdf",
      "tier": "S",
      "past_winners_3y": ["8010001234567", "8020005678901"]
    }
  ],
  "client_tag": "sales-2026Q2",
  "known_gaps": ["自治体独自 portal は API 化未完了", "公示日翌日に取込のため数時間ラグ"]
}
```

## known gaps
- 中央省庁 + 47 都道府県 + 20 政令市の公示は網羅、中核市以下は逐次拡大中
- 公示日翌日に取込 (深夜 03:00 JST 一括 ETL) のため数時間ラグ、緊急公告は手動 portal walk 推奨
- 落札結果は公示後 30-60 日で取込、即日反映ではない
- 落札後の応札書類本文 (技術提案書) は別途請求が必要 (情報公開請求)
- 競合落札社の `bid_history` は法人番号付き案件のみ、JV は代表社のみ捕捉

## 関連 tool
- `search_bids` (キーワード + 地域 + 締切で絞り込み)
- `get_bid_detail` (個別入札の仕様書 + 予定価格 + 過去落札社)
- `list_adoptions` (採択履歴、調達 + 補助金の組み合わせ把握)
- `get_corp_360` (競合企業の 360 度ビュー)
- `bid_history` (競合企業の過去 3 年落札動向)

## 関連 recipe
- [r03-sme-ma-public-dd](../r03-sme-ma-public-dd/index.md) — M&A DD、対象会社の公共調達依存度の確認
- [r25-adoption-bulk-export](../r25-adoption-bulk-export/index.md) — 採択 bulk export、競合動向の四半期集計

## billable_units 試算
- 1 朝 20 units × ¥3 = ¥60 / 日
- 月 20 営業日 = ¥1,200 / 月、税込 ¥1,320
- 年 240 営業日 = ¥14,400 / 年、税込 ¥15,840
- API fee delta: 月 20 営業日 × 朝 20 unit で、外部 model/search API fee は約 ¥4,000/月 (1 朝 cycle ¥200 = 入札 RSS 統合 + filter + tool 6) に対し jpcite は ¥1,200/月 (400 req × ¥3) → API fee delta 約 ¥2,800/月 / 営業日あたり ¥140 (cf. `docs/canonical/cost_saving_examples.md` case 3 同系)

## 商業利用条件
- PDL v1.0 (政府調達情報、出典明記) + CC-BY-4.0 (jpcite 編集)
- 営業企画レポート / 競合分析資料 / 経営会議資料への組込可、jpcite 出典明記必須
- 公開資料に基づく公知情報、NDA 対象外
- 落札結果の競合社名特定は公知事実、信用毀損につながる解釈は避ける

## 業法 fence
- 公共調達情報は公開、再配布は出典必須
- 落札後の応札書類本文は情報公開請求の対象
- 入札談合・官製談合の疑義検知は別 (公正取引委員会 / 独禁法 §3)
- 景表法 §5 — 競合動向の社内資料化は事実列挙に留め、優良誤認につながる表現は避ける
