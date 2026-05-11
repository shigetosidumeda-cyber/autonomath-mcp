---
title: "商工会議所の市町村 sweep"
slug: "r10-cci-municipal-screen"
audience: "商工会議所"
intent: "municipal_screen"
tools: ["list_municipal", "search_programs", "get_corp_360"]
artifact_type: "municipal_screen.csv"
billable_units_per_run: 40
seo_query: "商工会議所 市町村 補助金 sweep 会員企業"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 商工会議所の市町村 sweep

## 想定 user
都道府県商工会議所連合会 / 単位商工会議所 (会員企業 200-5,000 社規模) の経営支援部・会員支援部で、47 都道府県 + 自市町村 + 隣接市町村の補助金 / 助成金 / 認定制度を月初 sweep して、会員企業に Slack / メール / 月報 / 会員向け web 掲示板で fan-out する運用。マル経推薦・経営革新計画申請・小規模事業者持続化補助金等の単独施策と組み合わせて、会員 LTV 維持 + 新規入会推進の素材も生む。

## 必要な前提
- jpcite API key (¥3/req、初回 3 req/IP/日無料)
- `X-Client-Tag` (会員企業別計上 / 部署別請求)
- 会員企業 法人番号 list (200-5,000 件)
- 自市町村コード (5 桁 LGCode) + 隣接市町村コード
- (推奨) JSIC 中分類別の会員企業属性

## 入力例
```json
{
  "prefecture_code": "13",
  "municipality_codes": ["13104", "13108", "13109"],
  "member_corp_numbers": ["<会員企業 法人番号 200-1000 件>"],
  "include": ["municipal_subsidy", "tax_credit", "loan", "certification"],
  "tier_min": "B",
  "client_tag": "cci-shinjuku-2026"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: cci-shinjuku-2026" \
  "https://api.jpcite.com/v1/programs/municipal?prefecture=13&municipality=13104,13108&tier_min=B"

curl -X POST -H "X-API-Key: $JPCITE_API_KEY" \
  -H "Content-Type: application/json" \
  -d @members.json \
  "https://api.jpcite.com/v1/programs/bulk_match"
```
### Python
```python
import os, json
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="cci-shinjuku-2026")

# 1. 市町村独自制度一覧
municipal = c.list_municipal_programs(prefecture_code="13",
                                       municipality_codes=["13104"], tier_min="B")

# 2. 会員企業との bulk マッチング
members = json.load(open("members.json"))["corp_numbers"]
matches = c.bulk_match_programs(corp_numbers=members,
                                 prefecture="東京都",
                                 top_n_per_corp=3, client_tag="cci-shinjuku-2026")

# 3. fan-out CSV (会員別補助金 top3 + 締切)
import csv
with open("cci_screen.csv", "w") as f:
    w = csv.writer(f)
    w.writerow(["corp", "name", "top1_program", "fit_score", "deadline"])
    for r in matches.results:
        if r.top_programs:
            t = r.top_programs[0]
            w.writerow([r.corp_number, r.name, t.program_id, t.fit_score, t.deadline])
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
const matches = await jpcite.bulk_match_programs({
  corp_numbers: ["7010001234567"], prefecture: "東京都", top_n_per_corp: 3,
  client_tag: "cci-shinjuku-2026",
});
```

## 出力例 (artifact)
```json
{
  "prefecture_code": "13",
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://www.city.shinjuku.lg.jp/sangyo/...",
  "municipal_programs": [
    {"program_id": "shinjuku-it-2026", "name": "新宿区 IT 導入補助金",
     "max_amount_jpy": 500000, "subsidy_rate": "2/3", "deadline": "2026-09-30", "tier": "B"}
  ],
  "member_match_summary": {
    "total_members": 1200,
    "with_match": 847,
    "without_match": 353
  },
  "client_tag": "cci-shinjuku-2026",
  "known_gaps": ["municipal page redesign 検知遅延", "会員自己申告データに依存"]
}
```

## known gaps
- 自治体サイト改修で URL 変動による検知遅延 (URL 変更後 1-3 週間 lag)
- 公示 → jpcite 取込 7-14 日 (週次 ETL バッチ)
- 1,741 市町村のうち RSS / API 提供は 280、残り 1,461 はスクレイピング週次バッチ
- 会員企業の業種 / 規模等の属性データは商工会議所側自己申告ベース、jpcite は補完情報まで
- マル経推薦の信用金庫 / 商工会 quota は自治体別 / 信金別、本 recipe は対象制度の存在のみ

## 関連 tool
- `list_municipal` (本 recipe 中核、市町村制度一覧)
- `search_programs` (キーワード + 業種 + tier)
- `get_corp_360` (会員企業 360 度ビュー)
- `bulk_match_programs` (会員企業との一括マッチ)
- `municipal_diff` (差分取得、cron 用)

## 関連 recipe
- [r04-shinkin-borrower-watch](../r04-shinkin-borrower-watch/) — 信金 watch、隣接領域
- [r07-shindanshi-monthly-companion](../r07-shindanshi-monthly-companion/) — 診断士月次伴走、経営革新計画
- [r29-municipal-grant-monitor](../r29-municipal-grant-monitor/) — 市町村独自補助金モニター

## billable_units 試算
- 1 sweep 40 units × ¥3 = ¥120 / 月 (1 市町村)
- 5 市町村 × 月 = ¥600 / 月、税込 ¥660
- 会員 1,000 社 マッチ = ¥3,000 / 月、税込 ¥3,300
- ROI: 会員 LTV 維持 (年会費 ¥30K × 会員 1,000 = ¥30M 年間) で API 費用は完全回収

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- 月報 / 会員向け web 掲示板 / Slack / メール配信に組込 OK
- jpcite + 自治体出典の両明記、会員企業への直接配布 OK

## 業法 fence
- 商工会議所法 (商工会議所の業務範囲内)
- 中小企業診断士登録規則 — 経営助言は診断士領域、本 recipe は scaffold + 一次 URL まで
- 行政書士法 §1 — 申請書面作成は行政書士
- 景表法 §5 — `tier` / `fit_score` は推定値、保証ではない旨を配信末尾に注記推奨
