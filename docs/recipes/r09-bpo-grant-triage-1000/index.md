---
title: "補助金問い合わせトリアージ 1000 件"
slug: "r09-bpo-grant-triage-1000"
audience: "業務支援チーム"
intent: "bulk_triage"
tools: ["search_programs", "get_corp_360", "check_eligibility"]
artifact_type: "triage.csv"
billable_units_per_run: 1000
seo_query: "補助金 問い合わせ トリアージ 大量 照合"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 補助金問い合わせトリアージ 1000 件

## 想定 user
親会社 / 地銀 / メガバンク / 商工会連合会 / 信金中金 / 産業創造機構 等から、傘下 / 取引先 / 会員企業 500-5,000 社の公開情報レビューを依頼される業務支援チーム。月次 / 四半期で 1,000 社の法人番号 CSV を受領し、各社につき候補制度 top 5 + 排他ルール確認状況 + 要確認 band (low/mid/high) を初期レビュー表に整理し、人間レビュー・専門家確認の優先順位付けに使う。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料、bulk 利用は事前 prepay 推奨)
- `X-Client-Tag` (委託元別計上)
- 1,000 社の法人番号 CSV (法人番号 + 任意で 業種 / 所在地 / 直近売上 / 従業員数)
- (推奨) 委託元の業種 (JSIC 中分類) リスト

## 入力例
```json
{
  "corp_numbers": ["<法人番号 1,000 件 配列>"],
  "top_n_per_corp": 5,
  "include_exclusion_check": true,
  "include_review_band": true,
  "client_tag": "ginkou-A-2026Q2",
  "filter": {"tier": ["S", "A", "B"], "deadline_within_days": 90, "max_amount_jpy_min": 500000}
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -X POST -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: ginkou-A-2026Q2" \
  -H "Content-Type: application/json" -d @corps_1000.json \
  "https://api.jpcite.com/v1/programs/bulk_match"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/jobs/{job_id}/result.csv"
```
### Python
```python
import os, csv
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"])
with open("corps_1000.csv") as f:
    corp_numbers = [row[0] for row in csv.reader(f) if row]
res = c.bulk_match_programs(corp_numbers=corp_numbers, top_n_per_corp=5,
    include_exclusion_check=True, include_review_band=True,
    client_tag="ginkou-A-2026Q2",
    filter={"tier": ["S", "A", "B"], "deadline_within_days": 90})
with open("triage_1000.csv", "w", newline="") as out:
    w = csv.writer(out)
    w.writerow(["corp", "top1_program", "fit_score", "review_band", "exclusion_hit"])
    for r in sorted(res.results, key=lambda x: x.top_programs[0].fit_score, reverse=True):
        if not r.top_programs: continue
        top = r.top_programs[0]
        w.writerow([r.corp_number, top.program_id, top.fit_score, top.review_band, r.exclusion_hits])
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
import fs from "node:fs";
const corps = fs.readFileSync("corps_1000.csv", "utf8")
  .split("\n").map(l => l.split(",")[0]).filter(Boolean);
const res = await jpcite.bulk_match_programs({
  corp_numbers: corps, top_n_per_corp: 5,
  include_exclusion_check: true, include_review_band: true,
  client_tag: "ginkou-A-2026Q2",
  filter: { tier: ["S", "A", "B"], deadline_within_days: 90 },
});
```

## 出力例 (artifact)
```json
{
  "job_id": "bulk-2026-05-11-abc123",
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://api.jpcite.com/v1/programs/bulk_match",
  "content_hash": "sha256:f2a3...8c91",
  "total_corps": 1000,
  "matched_corps": 947,
  "unmatched_corps": 53,
  "elapsed_seconds": 187,
  "results": [
    {
      "corp_number": "7010001234567",
      "top_programs": [
        {"program_id": "meti-mono-2026-r5", "fit_score": 0.82, "review_band": "mid",
         "tier": "A", "deadline": "2026-07-31", "max_amount_jpy": 10000000,
         "source_url": "https://portal.monodukuri-hojo.jp/koubo/2026/r5/youkou.pdf"}
      ],
      "exclusion_hits": [],
      "client_tag": "ginkou-A-2026Q2"
    }
  ],
  "known_gaps": ["rate-limit 10 req/s で 1,000 社 約 2 分"],
  "recommended_followup": [
    "fit_score >= 0.75 の 87 社を人間レビュー優先",
    "0.60-0.75 の 234 社は、人間レビュー後に案内可否を判断する候補として保留",
    "0.50-0.60 の 626 社を四半期再算定対象に編入"
  ]
}
```

## known gaps
- rate-limit 10 req/s: 1,000 社で約 2 分、10,000 社では async job + R2 ダウンロード方式 (時間 22 分)
- 市区町村独自補助金: 1,741 のうち RSS / API 提供は 280、残り 1,461 はスクレイピング週次バッチで 7-14 日 lag
- 個人事業主 / 任意団体: 法人番号未付番のため bulk_match 対象外
- review_band: 過去 36 ヶ月の業種別公開採択実績と類似企業の公開情報を使った要確認 band。採択確率ではなく、データ薄い業種は "unknown"
- exclusion 抵触の前提条件: 納税状況 / 反社チェック / 役員兼任は jpcite では取得しない

## 関連 tool
- `bulk_match_programs` (本 recipe 中核、大量 法人番号 bulk マッチング)
- `get_corp_360` (個社深掘り、架電前の追加調査)
- `check_eligibility` (個別補助金の eligibility chain 確認)
- `apply_eligibility_chain` (公開版 21、複合補助金組合せ)
- `match_due_diligence_questions` (公開版 22、与信 DD 30-60 質問)

## 関連 recipe
- [r24-houjin-6source-join](../r24-houjin-6source-join/index.md) — 6 source join、素材 endpoint
- [r25-adoption-bulk-export](../r25-adoption-bulk-export/index.md) — 採択 bulk export、後段の集計

## billable_units 試算

- API fee delta: API fee delta の前提と再現式は [docs/canonical/cost_saving_examples.md](../../canonical/cost_saving_examples.md) を参照。
- 1 batch 1,000 units (法人 1 社 1 unit) × ¥3 = ¥3,000 / 委託
- 月 5 委託 = ¥15,000 / 月 (税込 ¥16,500)
- 月 20 委託 = ¥60,000 / 月 (税込 ¥66,000)

## 商業利用条件
- PDL v1.0 + CC-BY-4.0、出典明記必須
- 委託元 (地銀 / 商工会 / メガバンク) への再配布時は jpcite 出典明記必須
- 法人番号は公開情報 — 個別社名と紐付けても 個人情報保護法対象外
- 業務支援チーム内部の triage ロジック (fit_score 閾値 / レビュー優先度基準) は二次著作物扱い

## 業法 fence
- 業務支援チームは公開情報の整理のみ。申請可否判断・申請書面作成・提出代行は資格者または利用者本人の確認へ引き継ぐ
- 個人情報保護法 — 法人番号は対象外、代表者氏名 / 担当者連絡先 等は別途同意 + 安全管理
- 下請法 / 独禁法 — 親会社→傘下企業へのトリアージ結果押し付けは優越的地位の濫用に抵触し得る
- 景表法 — 要確認 band (low/mid/high) は公開情報に基づく初期整理であり、採択・受給・業績改善を保証しない旨を artifact に明記
