---
title: "司法書士の登記簿補完 watch"
slug: "r13-shihoshoshi-registry-watch"
audience: "司法書士"
intent: "registry_watch"
tools: ["get_corp_360", "list_adoptions", "get_enforcement"]
artifact_type: "registry_supplement.json"
billable_units_per_run: 8
seo_query: "司法書士 登記 補完 補助金 行政処分"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 司法書士の登記簿補完 watch

## 想定 user
司法書士法人 (1-15 人体制、年間 商業登記 200-1,500 件 / 不動産登記 500-3,000 件) で、商業登記申請 (役員変更 / 商号変更 / 本店移転 / 目的変更) や事業承継案件・M&A 法務 DD で「登記簿だけでは見えない実態」を補完して受任判断・本人確認 (犯罪収益移転防止法 §4) の精度を上げる司法書士。具体的には (1) 補助金採択・返還義務残期間、(2) 行政処分歴・公表事案、(3) 適格事業者抹消 / 商号変更履歴、(4) 直近 5 年の代表者・本店所在地変更の縦覧、を 5 分で取得して受任面談前に整理する。

## 必要な前提
- jpcite API key (¥3/req、初回 3 req/IP/日無料)
- `X-Client-Tag` ヘッダー (案件別 / 顧客別の billable_units 計上)
- 法人番号 (国税庁 13 桁) — 商業登記の会社法人等番号 (12 桁) からは末尾 0 付加で変換
- (任意) 申請予定の登記類型 (役員変更 / 本店移転 / 目的変更 / 合併 / 分割)
- (任意) 関連法人 (親会社 / 子会社 / 関連会社) の法人番号

## 入力例
```json
{
  "corp_number": "7010001234567",
  "lookback_years": 5,
  "include": ["adoption", "enforcement", "invoice_history", "amendment_log"],
  "watch_events": ["representative_change", "address_change", "name_change", "purpose_change"],
  "client_tag": "case-2026-0511"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: case-2026-0511" \
  "https://api.jpcite.com/v1/corp/7010001234567/360?lookback_years=5&include=adoption,enforcement,invoice_history,amendment_log"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/corp/7010001234567/name_history?lookback_years=10"
```
### Python
```python
import os, json
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="case-2026-0511")
snap = c.get_corp_360(corp_number="7010001234567", lookback_years=5,
    include=["adoption", "enforcement", "invoice_history", "amendment_log"])
report = {
    "corp": snap.corp_number,
    "name_current": snap.name,
    "name_changes_5y": [a for a in snap.amendment_log if a.field == "name"],
    "representative_changes_5y": [a for a in snap.amendment_log if a.field == "representative"],
    "active_subsidy_obligations": snap.adoptions_with_clawback,
    "enforcement_5y": snap.enforcement_history,
    "invoice_status": snap.invoice_status,
}
with open("registry_supplement.json", "w") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
import fs from "node:fs";
const snap = await jpcite.get_corp_360({
  corp_number: "7010001234567", lookback_years: 5,
  include: ["adoption", "enforcement", "invoice_history", "amendment_log"],
  client_tag: "case-2026-0511",
});
fs.writeFileSync("registry_supplement.json", JSON.stringify(snap, null, 2));
```

## 出力例 (artifact)
```json
{
  "corp_number": "7010001234567",
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://www.houjin-bangou.nta.go.jp/...",
  "corp_name": "サンプル商事株式会社",
  "lookback_years": 5,
  "amendment_log": [
    {"changed_at": "2024-06-15", "field": "representative", "from": "山田太郎", "to": "山田次郎"},
    {"changed_at": "2023-04-01", "field": "address", "from": "東京都港区...", "to": "東京都千代田区..."}
  ],
  "active_subsidy_obligations": [
    {"program": "meti-monozukuri-r4", "amount_jpy": 12000000, "obligation_end": "2029-09-14", "remaining_months": 40}
  ],
  "enforcement_5y": [],
  "invoice_status": "active",
  "invoice_revocations": [],
  "known_gaps": ["登記簿そのものの取得は別 API (登記情報提供サービス)", "個人事業主は法人番号無しのため別系統"]
}
```

## known gaps
- 登記情報提供サービス (オンライン登記簿) の本体は別契約必須、本 recipe は補完情報層のみ
- 個人事業主は法人番号未付番のため別 endpoint (`invoice_registrants` の T + 13 桁 検索) で対応
- 海外子会社・休眠会社は適格事業者登録外の場合は捕捉不能
- 商号変更 5 年超は古い名称が残存しないケースあり (法人番号公表サイトの遡及限界)
- 代表者変更の同名異人判定は別 API、本 recipe は氏名文字列ベース

## 関連 tool
- `get_corp_360` (法人 4 source 統合 view、商業登記補完)
- `list_adoptions` (採択履歴 + 財産処分制限期間)
- `get_enforcement` (行政処分 / 公表事案)
- `check_invoice_status` (適格事業者状況 + 抹消履歴)
- `get_amendment_log` (商号 / 住所 / 代表者 変更の縦覧)

## 関連 recipe
- [r03-sme-ma-public-dd](../r03-sme-ma-public-dd/) — M&A DD、買収側の事前調査
- [r12-audit-firm-kyc-sweep](../r12-audit-firm-kyc-sweep/) — 監査法人 KYC、独立性チェックの素材
- [r24-houjin-6source-join](../r24-houjin-6source-join/) — 法人 6 source join、本 recipe の素材レイヤ

## billable_units 試算
- 1 案件 8 units × ¥3 = ¥24 / 案件
- 月 50 案件 (中堅司法書士法人) = ¥1,200 / 月、税込 ¥1,320 / 月
- 月 200 案件 (大手) = ¥4,800 / 月、税込 ¥5,280 / 月
- ROI: 受任後の事故 (本人確認漏れ / 補助金返還義務見落とし) 1 件回避 = 司法書士法人の懲戒・損害賠償リスク回避 ¥数百万-¥数千万

## 商業利用条件
- PDL v1.0 (NTA 法人番号 / 適格事業者) + CC-BY-4.0 (jpcite 編集物)
- 受任面談資料 / 法務 DD レポート / 商業登記申請書添付資料への組込可、jpcite 出典明記必須
- 顧客 (依頼者) への提供時は事実通知に留め、法的判断 (弁護士法 §72) は別途弁護士手元

## 業法 fence
- 司法書士法 §3 (登記申請代理 / 供託 / 法務局提出書類作成は司法書士独占)
- 弁護士法 §72 (法的紛争・契約条項解釈は弁護士領域、本 recipe は事実列挙のみ)
- 犯罪収益移転防止法 §4 (本人確認の義務遂行) — 本 recipe は補完情報、最終的な本人確認は司法書士自身
- 個人情報保護法 — 代表者氏名 / 住所等は個人情報、業務上必要な範囲での取得 + 安全管理が前提
