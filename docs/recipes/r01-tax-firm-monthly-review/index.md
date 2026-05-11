---
title: "税理士事務所の月次顧問先一括レビュー"
slug: "r01-tax-firm-monthly-review"
audience: "税理士"
intent: "monthly_review"
tools: ["search_programs", "get_corp_360", "check_invoice_status"]
artifact_type: "monthly_review.pdf"
billable_units_per_run: 18
seo_query: "税理士 顧問先 月次 補助金 助成金 一括 確認"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 税理士事務所の月次顧問先一括レビュー

## 想定 user
所員 3-10 名・顧問先 50-300 社 (法人 7 割 / 個人事業 3 割) の中堅税理士事務所。月初の巡回監査前に、各顧問先について「直近 30 日の補助金採択公表」「適格事業者番号の有効性」「行政処分 / 公表事案の有無」「未申請の合致補助金 top3」を一括で取得し、面談時の話題と提案ネタを 5 分で揃えたい所長・科目担当者を主たる対象とする。手動なら 1 社 5 分 × 100 社 = 8 時間/月の事務作業が、本 recipe で 5 分 + 確認 30 分に短縮される。

## 必要な前提
- jpcite API key (¥3/req、初回 3 req/IP/日無料、JST 翌日 00:00 リセット)
- `X-Client-Tag` ヘッダ (顧問先別計上、`api_keys` 親子発行で子キー fan-out 可)
- 顧問先の法人番号リスト (CSV / Excel / 弥生・PCA・freee・MF 等の会計 SW export)
- (任意) `client_profiles` テーブルへ事前登録 (JSIC 業種 + 設立年 + 都道府県) すると `subsidy_matches` の fit_score が +0.1-0.2 改善

## 入力例
```json
{
  "corp_numbers": ["7010001234567", "8010001234568"],
  "months_back": 1,
  "client_tag": "kojin-001",
  "include": ["adoption", "invoice", "enforcement", "subsidy_match"],
  "subsidy_top_n": 3,
  "language": "ja"
}
```
- `corp_numbers`: 13 桁 法人番号 (国税庁付番)。1 req あたり最大 200 件、超過時は自動 chunk。
- `months_back`: 採択 / 処分 を遡る月数 (1-12)。月次運用は 1。
- `client_tag`: 課金行に付与される識別子 (`usage_events.client_tag`、migration 085)。顧問先別請求書発行に使う。
- `subsidy_top_n`: 1 法人あたりの推奨補助金件数 (1-10、既定 3)。

## 実行 (curl / Python / TypeScript)
### curl
```bash
# 1 社単位の 360 view
curl -H "X-API-Key: $JPCITE_API_KEY" \
     -H "X-Client-Tag: kojin-001" \
     "https://api.jpcite.com/v1/corp/7010001234567/360?include=adoption,invoice,enforcement,subsidy_match&months_back=1"

# 100 社 bulk
curl -X POST -H "X-API-Key: $JPCITE_API_KEY" \
     -H "X-Client-Tag: kojin-001" \
     -H "Content-Type: application/json" \
     -d @clients.json \
     "https://api.jpcite.com/v1/corp/bulk_360"
```
### Python
```python
import os, json
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"])
clients = json.load(open("clients.json"))
review_rows = []
for cn in clients["corp_numbers"]:
    snap = c.get_corp_360(
        corp_number=cn,
        include=["adoption", "invoice", "enforcement", "subsidy_match"],
        months_back=1,
        client_tag=cn,
    )
    review_rows.append({
        "corp": cn,
        "invoice_ok": snap.invoice_registered,
        "new_adoption": len(snap.adoptions_30d),
        "top_subsidy": (snap.subsidy_matches_top3[:1] or [{}])[0].get("program_id"),
        "enforcement": bool(snap.enforcement_30d),
    })
import pandas as pd
pd.DataFrame(review_rows).to_excel("monthly_review_2026-05.xlsx", index=False)
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
import fs from "node:fs";
const clients = JSON.parse(fs.readFileSync("clients.json", "utf8"));
const rows: any[] = [];
for (const cn of clients.corp_numbers) {
  const s = await jpcite.get_corp_360({
    corp_number: cn,
    include: ["adoption", "invoice", "enforcement", "subsidy_match"],
    months_back: 1,
    client_tag: cn,
  });
  rows.push({ corp: cn, invoice: s.invoice_registered, top: s.subsidy_matches_top3?.[0]?.program_id });
}
fs.writeFileSync("monthly_review.json", JSON.stringify(rows, null, 2));
```

## 出力例 (artifact)
```json
{
  "corp_number": "7010001234567",
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://api.jpcite.com/v1/corp/7010001234567/360",
  "invoice_registrant": {"registered": true, "registered_date": "2023-10-01"},
  "adoptions_30d": [],
  "enforcements_30d": [],
  "subsidy_matches_top3": [
    {"program_id": "METI-MONOZUKURI-2026", "name": "ものづくり補助金 第18次", "fit_score": 0.82, "tier": "S", "source_url": "https://portal.monodukuri-hojo.jp/..."}
  ],
  "client_tag": "kojin-001",
  "known_gaps": ["municipal lag 7-14d"]
}
```

## known gaps
- 市町村独自補助金は ingest 周期で 7-14 日遅延、S/A tier は当日反映
- 過去採択履歴は顧問先自己申告依存、jPubs API で完全捕捉できないケースあり
- `subsidy_top_n=10` 超は別 endpoint (bulk_match)、本 recipe は top3 想定
- enforcement の `公表 → 取込` は 24-72 時間ラグ

## 関連 tool
- `search_programs` (キーワード + 業種 + 規模)
- `get_corp_360` (法人 360 度ビュー、本 recipe 中核)
- `check_invoice_status` (適格事業者状況)
- `list_adoptions` (採択履歴)
- `apply_eligibility_chain_am` (排他ルールチェック、Wave 21)

## 関連 recipe
- [r02-pre-closing-subsidy-check](../r02-pre-closing-subsidy-check/) — 決算前最終チェック、月次の延長
- [r07-shindanshi-monthly-companion](../r07-shindanshi-monthly-companion/) — 診断士月次伴走、提案 phase 引継ぎ
- [r11-ec-invoice-bulk-verify](../r11-ec-invoice-bulk-verify/) — 適格事業者一括検証

## billable_units 試算
- 1 顧問先 18 units (`get_corp_360` 12 + matching 6) × ¥3 = ¥54 / 顧問先 / 月
- 顧問先 100 社 = ¥5,400 / 月、税込 ¥5,940
- 年 12 ヶ月 = ¥64,800 / 年、税込 ¥71,280
- ROI: 顧問契約解除 1 件回避 (¥3-10万/月 × 12 = ¥36-120万/年) で API 費用は完全回収、67-222 倍

## 商業利用条件
- PDL v1.0 + CC-BY-4.0、出典明記必須
- 月次レポート / 顧問先伴走資料への組込・印刷頒布 OK
- 第三者配布は別途要相談

## 業法 fence
- 税理士法 §52 (税務代理 / 税務書類作成 / 税務相談は税理士独占)
- 中小企業診断士登録規則 — 経営助言 / 補助金申請伴走は診断士領域
- 行政書士法 §1 — 申請書面作成は行政書士、本 recipe は scaffold + 一次 URL まで
- 景表法 §5 — `fit_score` / `max_amount_jpy` は推定値、保証ではない旨を末尾注記推奨

## canonical_source_walkthrough

> 一次資料 / canonical source への walk-through。Wave 21 C6 で全 30 recipes に追加。

### 使う tool
- **MCP tool**: `get_corp_360`
- **REST endpoint**: `/v1/corp/{corp_number}/360`
- **jpcite.com docs**: <https://jpcite.com/recipes/r01-tax-firm-monthly-review/>

### expected output
- JSON: invoice_registrant.registered=true + adoptions_30d=[] + subsidy_matches_top3.length<=3 + fetched_at + source_url
- 全 response に `fetched_at` (UTC ISO 8601) + `source_url` (一次資料 URL) 必須
- `_disclaimer` envelope (税理士法 §52 / 行政書士法 §1 / 司法書士法 §3 / 弁護士法 §72 等の業法 fence 該当時)

### 失敗時 recovery
- **404 Not Found**: 法人番号が国税庁 houjin-bangou.nta.go.jp に未登録 — 入力 13 桁を再確認
- **429 Too Many Requests**: anonymous quota 3 req/日 を超過 — API key を発行 (https://jpcite.com/keys) or X-Forwarded-For 別 IP
- **5xx / timeout**: Fly Tokyo region 一時障害 — 60s 待機後再試行、status.jpcite.com で確認

### canonical source (一次資料)
- 国税庁 適格事業者公表サイト: <https://www.invoice-kohyo.nta.go.jp/>
- 中小企業庁 補助金一覧: <https://www.chusho.meti.go.jp/>
- e-Gov 法令検索: <https://laws.e-gov.go.jp/>
- 国立国会図書館 NDL: <https://www.ndl.go.jp/>
- jpcite 一次資料 license 表: <https://jpcite.com/legal/licenses>
