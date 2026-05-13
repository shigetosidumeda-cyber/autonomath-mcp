---
title: "適格事業者の抹消 watch"
slug: "r30-invoice-revoke-watch"
audience: "横串 (経理・税理士)"
intent: "invoice_revoke_watch"
tools: ["check_invoice_status", "get_invoice_history", "get_corp_360"]
artifact_type: "revoke_alert.json"
billable_units_per_run: 100
seo_query: "適格事業者 抹消 watch インボイス 廃業"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 適格事業者の抹消 watch

## 想定 user
EC / 卸売 / 商社 / メーカー / 飲食店チェーン 等の経理担当者・税理士事務所の所員が、仕入先 100-10,000 社の適格事業者登録が抹消 / 廃業 / 取消 / 名称変更されないか毎週検知して、消費税仕入税額控除のリスクを抑える運用。月次の `bulk_invoice_verify` (r11) より頻度を上げて週次 / 日次の `invoice_revoke_watch` を回し、抹消検知の翌営業日に支払保留 + 税区分修正を行う運用が想定読者。期末決算前 (3 月 / 12 月) の年次総点検では 10,000-50,000 社規模を 1 batch で sweep する用途にも対応。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料)
- 仕入先の登録番号 CSV (T + 13 桁、freee / マネーフォワード / 弥生会計から export)
- 週次 cron (n8n / GitHub Actions / Fly cron / Cloud Functions / Lambda 等)
- (推奨) `Idempotency-Key` ヘッダー (週次 batch の冪等性確保)
- (推奨) 仕入先別の支払予定額 — 抹消検知時の影響額試算用

## 入力例
```json
{
  "invoice_numbers": ["T7010001234567", "T8010001234568", "<T + 13 桁を 100-10,000 件 配列で>"],
  "watch": "revoke",
  "events": ["revoke", "expire", "name_change"],
  "client_tag": "weekly-2026Q2",
  "idempotency_key": "watch-2026-05-11-v1",
  "include_corp_360": false
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -X POST -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: weekly-2026Q2" \
  -H "Idempotency-Key: watch-2026-05-11-v1" -H "Content-Type: application/json" \
  -d @nums.json \
  "https://api.jpcite.com/v1/invoice/bulk_watch?event=revoke"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/invoice/T7010001234567/history"
```
### Python
```python
import os, csv, json, requests
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="weekly-2026Q2")
with open("vendor_invoices.csv") as f:
    nums = [row[0] for row in csv.reader(f) if row[0].startswith("T")]
res = c.bulk_invoice_watch(invoice_numbers=nums,
    events=["revoke", "name_change"], idempotency_key="watch-2026-05-11-v1")
revoked = [r for r in res.results if r.event == "revoke"]
if revoked:
    text = f"[抹消検知] {len(revoked)} 社"
    requests.post(os.environ["SLACK_WEBHOOK_URL"], json={"text": text})
with open(f"revoke_{res.fetched_at[:10]}.json", "w") as f:
    json.dump([r.__dict__ for r in revoked], f, ensure_ascii=False, indent=2)
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
import fs from "node:fs";
const nums = fs.readFileSync("vendor_invoices.csv", "utf8")
  .split("\n").filter(l => l.startsWith("T"));
const res = await jpcite.bulk_invoice_watch({
  invoice_numbers: nums, events: ["revoke", "name_change"],
  idempotency_key: "watch-2026-05-11-v1", client_tag: "weekly-2026Q2",
});
const revoked = res.results.filter(r => r.event === "revoke");
fs.writeFileSync("revoke_alert.json", JSON.stringify(revoked, null, 2));
```

## 出力例 (artifact)
```json
{
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://www.invoice-kohyo.nta.go.jp/regno-search/main",
  "scanned_total": 100,
  "active": 91,
  "revoked": 7,
  "expired": 0,
  "name_changed": 2,
  "results_revoked": [
    {"invoice_number": "T7010001234567", "event": "revoke",
     "revoked_date": "2026-04-30", "reason": "廃業", "corp_name": "サンプル商事株式会社"},
    {"invoice_number": "T8010001234568", "event": "revoke",
     "revoked_date": "2026-05-08", "reason": "取消"}
  ],
  "client_tag": "weekly-2026Q2",
  "known_gaps": ["抹消反映に 1-2 日遅延", "抹消理由詳細は限定公開"]
}
```

## known gaps
- 国税庁公表サイトの更新は 1-2 日遅延、月末 / 期末締の直前 watch では翌営業日 再 watch が安全
- 抹消理由詳細 (廃業 / 取消 / 死亡 / 法人解散) は公表サイト UI 表示に依存、本 API は分類後 enum のみ提供
- 月次 4M 行 bulk (`nta-bulk-monthly`、1st-of-month 03:00 JST) 直後の整合性は最大 24 時間
- 個人事業主の抹消は法人格と異なり、本人申出ベース、検知ラグは長め
- `name_change` (商号変更) は 抹消 + 新規登録 のペアとして reflect される場合あり

## 関連 tool
- `check_invoice_status` (単発の登録 status 確認)
- `bulk_invoice_watch` (本 recipe の中核、週次差分 watch)
- `get_invoice_history` (登録 / 抹消 / 商号変更履歴の縦覧)
- `get_corp_360` (法人 360 度ビュー、抹消 + 行政処分 + 採択履歴の組み合わせ)

## 関連 recipe
- [r11-ec-invoice-bulk-verify](../r11-ec-invoice-bulk-verify/index.md) — EC 経理月次 verify、本 recipe の前段
- [r12-audit-firm-kyc-sweep](../r12-audit-firm-kyc-sweep/index.md) — 監査法人 KYC、独立性チェック
- [r24-houjin-6source-join](../r24-houjin-6source-join/index.md) — 法人 6 source join、抹消 + 行政処分の組み合わせ素材

## billable_units 試算
- 1 batch 100 units × ¥3 = ¥300 / 週
- 月 4 週 = ¥1,200 / 月、税込 ¥1,320
- 仕入先 1,000 社 = ¥3,000 / 週 × 4 = ¥12,000 / 月、税込 ¥13,200
- 期末年次総点検 (10,000 社) = ¥30,000 / 期末、税込 ¥33,000
- API fee delta: 仕入先 1,000 社 × 月 4 週 で、外部 model/search API fee は約 ¥40,000/月 (1 batch cycle ¥10,000 = 1,000 社 × NTA fetch + diff) に対し jpcite は ¥12,000/月 (4,000 req × ¥3) → API fee delta 約 ¥28,000/月 / 社あたり ¥28 (cf. `docs/canonical/cost_saving_examples.md` case 3 同系)

## 商業利用条件
- PDL v1.0 (NTA 公開データ、出典明記必須) + CC-BY-4.0 (jpcite 編集物)
- 経理 / 税務 / 監査調書への組込 OK、外部公表は税理士確認推奨
- 仕入先への抹消通知 / 支払保留通知は事実通知に留め、信用毀損リスクに留意
- 公開資料に基づく公知情報、NDA 対象外

## 業法 fence
- 消費税法 §30 (仕入税額控除) の判断は税理士領域
- 経理処理 (買掛金修正 / 税区分修正) は事業者内部 OK、外部公表時は税理士確認
- 個人情報保護法 — 個人事業主の氏名 / 住所が含まれる場合、安全管理措置と利用目的明示
- 景表法 §5 — 仕入先への通知は事実通知に留め、評価表現 (悪質 / 危険) は避ける
