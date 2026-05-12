---
title: "信用金庫渉外の取引先 watch"
slug: "r04-shinkin-borrower-watch"
audience: "信用金庫渉外"
intent: "borrower_watch"
tools: ["search_programs", "get_corp_360", "get_enforcement", "loan-programs-search"]
artifact_type: "borrower_digest.csv"
billable_units_per_run: 8
seo_query: "信用金庫 渉外 取引先 補助金 融資 watch"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 信用金庫渉外の取引先 watch

## 想定 user
254 信用金庫の渉外担当 (取引先 80-200 社/人)。月初に取引先全社の「新規採択補助金」「行政処分」「マル経推薦の併給可否」「日本政策金融公庫融資 + 47 信用保証協会 連動制度」を一括取得し、訪問前 5 分で「金利優遇打診 + 制度紹介 + 反社/処分 watch」を確定する運用。融資審査前 DD として「補助金交付対象になりそうな設備投資なら金利優遇 + 信用保証協会推薦書面」を当てる工数も含む。

## 必要な前提
- jpcite API key (¥3/req、初回 3 req/IP/日無料)
- `X-Client-Tag` (顧客別計上、`branch_xxx/houjin` 命名規約推奨)
- 取引先 法人番号リスト (CSV、勘定系から export)
- 担当支店コード (4 桁、信金中金フォーマット)

## 入力例
```json
{
  "corp_numbers": ["<取引先 法人番号 50-200 件>"],
  "client_tag": "branch_omiya/houjin",
  "include": ["adoption_30d", "enforcement_30d", "loan_match", "subsidy_match"],
  "loan_collateral": "not_required",
  "top_n_per_corp": 3
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: branch_omiya/houjin" \
  "https://api.jpcite.com/v1/corp/7010001234567/360?include=adoption,enforcement,subsidy_match,loan_match&months_back=1"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/loan-programs/search?collateral_required=not_required&prefecture=埼玉県"
```
### Python
```python
import os, csv
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"])
for hb in [r["houjin_bangou"] for r in csv.DictReader(open("customers.csv"))]:
    r = c.get_corp_360(corp_number=hb,
                       include=["adoption", "enforcement", "subsidy_match", "loan_match"],
                       months_back=1, client_tag=f"branch_omiya/{hb}")
    print(f"{hb}\t{len(r.adoptions)}\t{len(r.enforcements)}\t{(r.subsidy_matches or [{}])[0].get('program_id','-')}")
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
import fs from "node:fs";
const corps = fs.readFileSync("customers.csv", "utf8").split("\n").slice(1).map(l => l.split(",")[0]);
for (const hb of corps) {
  const r = await jpcite.get_corp_360({
    corp_number: hb, include: ["adoption", "enforcement", "subsidy_match", "loan_match"],
    months_back: 1, client_tag: `branch_omiya/${hb}`,
  });
  console.log(hb, r.adoptions?.length, r.enforcements?.length);
}
```

## 出力例 (artifact)
```json
{
  "corp_number": "7010001234567",
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://api.jpcite.com/v1/corp/7010001234567/360",
  "adoptions_30d": [{"program_id": "saitama-dx-2026", "adopted_at": "2026-04-28", "amount_jpy": 3000000}],
  "enforcements_30d": [],
  "subsidy_matches_top3": [
    {"program_id": "meti-mono-2026-r5", "fit_score": 0.78, "deadline": "2026-07-31"}
  ],
  "loan_match_top3": [
    {"loan_id": "jfc-marukei-2026", "name": "マル経融資", "collateral_required": false, "max_amount_jpy": 20000000}
  ],
  "client_tag": "branch_omiya/houjin",
  "known_gaps": ["municipal lag 7-14d"]
}
```

## known gaps
- 市町村独自補助金は週次差分、政令市以上は当日反映
- 反社 DB は別途専門業者契約必須、本 recipe は公示行政処分のみ
- 信用保証協会 推薦書面の自動生成は対象外 (scaffold + 一次 URL まで)
- マル経 (日本政策金融公庫 経営改善貸付) の月次推薦枠は信金別 quota 別途確認

## 関連 tool
- `search_programs` + `loan-programs/search` (補助金 + 融資の併給候補)
- `get_corp_360` (法人 360 度ビュー、本 recipe 中核)
- `get_enforcement` (行政処分 30 日窓)
- `check_invoice_status` (適格事業者状況)

## 関連 recipe
- [r03-sme-ma-public-dd](../r03-sme-ma-public-dd/) — M&A DD、隣接領域
- [r10-cci-municipal-screen](../r10-cci-municipal-screen/) — 商工会議所 市町村 sweep
- [r26-enforcement-rss-slack](../r26-enforcement-rss-slack/) — 行政処分 RSS、リスク監視

## billable_units 試算
- 1 取引先 8 units × ¥3 = ¥24 / 取引先 / 月
- 担当 100 取引先 = ¥2,400 / 月、税込 ¥2,640
- 担当 200 取引先 = ¥4,800 / 月、税込 ¥5,280
- 節約 (純 LLM vs jpcite ¥3/req): 担当 100 取引先 × 月 1 cycle で、純 LLM は約 ¥9,000/月 (1 cycle ¥90 = source 5,000 + tool 3 + repeat fetch) に対し jpcite は ¥2,400/月 (800 req × ¥3) → 節約 約 ¥6,600/月 / 取引先あたり ¥66 (cf. `docs/canonical/cost_saving_examples.md` case 3)

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- 信金内部 / 経営支援部レポートへの組込 OK、顧問先への直接配布は別途要相談
- `X-Client-Tag` を `branch_xxx/houjin` 形式で命名すると支店別請求書発行に統合可

## 業法 fence
- 弁護士法 §72 — 法的紛争予測は弁護士、本 recipe は事実通知層
- 金融商品取引法 — 信金法 / 銀行法上の与信判断は資格者
- 信用金庫法 — 推薦書面は所定様式、本 recipe は scaffold + 一次 URL まで
- 景表法 §5 — `fit_score` は推定値、顧客提案資料に注記推奨
