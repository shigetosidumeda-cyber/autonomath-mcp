---
title: "EC 経理の適格事業者一括検証"
slug: "r11-ec-invoice-bulk-verify"
audience: "EC 経理"
intent: "invoice_bulk_verify"
tools: ["check_invoice_status", "bulk_invoice_verify", "get_corp_360"]
artifact_type: "invoice_audit.csv"
billable_units_per_run: 500
seo_query: "EC 経理 適格事業者 一括 確認 インボイス"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# EC 経理の適格事業者一括検証

## 想定 user
EC 事業者 (年商 ¥1-50 億規模) の経理担当者・財務部マネージャーが、月次仕入先 500-5,000 社の適格事業者登録番号 (T + 13 桁) を一括 verify して、消費税仕入税額控除の漏れを防ぐ。月末締めの 3 営業日以内に「抹消・廃業・取消」を検知し、買掛金支払時の税区分修正、得意先別の請求書再発行依頼、税理士への月次レポート提出に直結させる運用が想定読者。期末決算前 (3 月 / 12 月) の年次総点検では 10,000 社規模を 1 batch で sweep する用途にも対応。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料、JST 翌日 00:00 リセット)
- `X-Client-Tag` ヘッダー (仕入先別 / 部門別の billable 計上)
- 仕入先の登録番号 CSV (T + 13 桁、freee / マネーフォワード / 弥生会計から export)
- (推奨) 月次の支払予定額・取引高 — 抹消検知時の影響額試算に使用
- (推奨) 仕入税額控除対象 / 対象外区分 — 検証結果と紐付け

## 入力例
```json
{
  "invoice_numbers": ["T7010001234567", "T8010001234568", "<T + 13 桁 を 100-10,000 件配列で>"],
  "client_tag": "ec-mar-2026",
  "watch_events": ["revoke", "expire", "name_change"],
  "include_corp_360": false,
  "language": "ja"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -X POST -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: ec-mar-2026" \
  -H "Content-Type: application/json" -d @invoices.json \
  "https://api.jpcite.com/v1/invoice/bulk_verify"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/invoice/T7010001234567/history"
```
### Python
```python
import os, csv, json
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="ec-mar-2026")
with open("vendor_invoices.csv") as f:
    nums = [row[0] for row in csv.reader(f) if row[0].startswith("T")]
res = c.bulk_invoice_verify(invoice_numbers=nums, watch_events=["revoke", "expire"])
revoked = [r for r in res.results if r.status != "active"]
with open("hold_payment.csv", "w", newline="") as out:
    w = csv.writer(out)
    w.writerow(["invoice_number", "status", "revoked_date", "reason"])
    for r in revoked:
        w.writerow([r.invoice_number, r.status, r.revoked_date, r.reason])
print(f"{len(revoked)} 件抹消検知")
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
import fs from "node:fs";
const nums = fs.readFileSync("vendor_invoices.csv", "utf8")
  .split("\n").filter(l => l.startsWith("T"));
const res = await jpcite.bulk_invoice_verify({
  invoice_numbers: nums, watch_events: ["revoke", "expire"], client_tag: "ec-mar-2026",
});
const revoked = res.results.filter(r => r.status !== "active");
fs.writeFileSync("hold_payment.json", JSON.stringify(revoked, null, 2));
```

## 出力例 (artifact)
```json
{
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://www.invoice-kohyo.nta.go.jp/regno-search/main",
  "client_tag": "ec-mar-2026",
  "total_verified": 500,
  "active": 487,
  "revoked": 9,
  "expired": 0,
  "name_changed": 4,
  "results": [
    {"invoice_number": "T7010001234567", "status": "active",
     "registered_date": "2023-10-01", "corp_name": "サンプル商事株式会社"},
    {"invoice_number": "T8010001234568", "status": "revoked",
     "registered_date": "2023-10-01", "revoked_date": "2026-04-30", "reason": "廃業"}
  ],
  "known_gaps": ["月末抹消反映に 1-2 日遅延", "抹消理由詳細は限定公開"]
}
```

## known gaps
- 国税庁公表サイトの更新は 1-2 日遅延、月末 / 期末締の直前 verify では翌営業日 再 verify 推奨
- 抹消理由 (廃業 / 取消 / 死亡) の詳細は公表サイト UI 上の表示に依存、本 API は分類後 enum のみ
- 個人事業主の登録は法人番号無し、`T + 13 桁` 末尾チェックデジット検証で前処理推奨
- 商号変更 (`name_change`) は履歴遡及 5 年が標準、それ以前は古い名称が `corp_name` に残る場合あり
- 月次 4M 行 bulk (`nta-bulk-monthly`、1st-of-month 03:00 JST) 直後の整合性は最大 24 時間

## 関連 tool
- `check_invoice_status` (単発の登録 status 確認)
- `bulk_invoice_verify` (本 recipe の中核)
- `get_invoice_history` (登録 / 抹消 / 商号変更履歴の縦覧)
- `get_corp_360` (法人 360 度ビュー、抹消 + 行政処分の組み合わせ検知)

## 関連 recipe
- [r01-tax-firm-monthly-review](../r01-tax-firm-monthly-review/) — 税理士月次レビュー、顧問先別の抹消検知 + 税区分修正
- [r12-audit-firm-kyc-sweep](../r12-audit-firm-kyc-sweep/) — 監査法人 KYC、独立性チェック + 適格事業者突合
- [r30-invoice-revoke-watch](../r30-invoice-revoke-watch/) — 抹消 watch、週次 cron + 検知時 Slack alert

## billable_units 試算
- 1 batch 500 units × ¥3 = ¥1,500 / 月、税込 ¥1,650
- 年 12 batch = ¥18,000 / 年、税込 ¥19,800
- 期末年次総点検 (10,000 社) = ¥30,000 / 期末、税込 ¥33,000

## 商業利用条件
- PDL v1.0 (NTA 公開データ、出典明記必須) + CC-BY-4.0 (jpcite 編集物)
- EC 事業者内部の月次レポート / 監査調書 / 税務調査対応資料への組込 OK
- 第三者 (取引先・株主) への配布は jpcite 出典明記の上で可

## 業法 fence
- 消費税法 §30 (仕入税額控除) の判断は税理士領域、本 recipe は事実通知層まで
- 経理処理 (買掛金修正 / 税区分修正) は事業者内部で実施可、外部公表は税理士確認推奨
- 個人情報保護法 — 個人事業主の氏名 / 住所が含まれる場合、安全管理措置と利用目的明示
- 景表法 §5 — 仕入先への抹消通知時は事実通知に留め、信用毀損につながる表現は避ける
