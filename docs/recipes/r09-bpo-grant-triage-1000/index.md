---
title: "BPO の補助金トリアージ 1000 件"
slug: "r09-bpo-grant-triage-1000"
audience: "BPO"
intent: "bulk_triage"
tools: ["search_programs", "get_corp_360", "check_eligibility"]
artifact_type: "triage_table.csv"
billable_units_per_run: 1000
seo_query: "BPO 補助金 トリアージ 大量 自動化"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# BPO の補助金トリアージ 1000 件

## 想定 user
親会社 / 地銀 / メガバンク / 商工会連合会 / 信金中金 / 産業創造機構 等から、傘下 / 取引先 / 会員企業 500-5,000 社の補助金フィット度算定を一括委託される BPO 事業者。月次 / 四半期で 1,000 社の法人番号 CSV を受領し、各社につき適合補助金 top 5 + 排他ルール抵触有無 + 採択確率帯 (low/mid/high) を 5 分でテーブル化し、優先架電 100 社 / 案内 DM 900 社の振分けを行う。

## 必要な前提
- jpcite API key (¥3/req、初回 3 req/IP/日無料、bulk 利用は事前 prepay 推奨)
- `X-Client-Tag` (委託元別計上)
- 1,000 社の法人番号 CSV (法人番号 + 任意で 業種 / 所在地 / 直近売上 / 従業員数)
- (推奨) 委託元の業種 (JSIC 中分類) リスト

## 入力例
```json
{
  "corp_numbers": ["<法人番号 1,000 件 配列>"],
  "top_n_per_corp": 5,
  "include_exclusion_check": true,
  "include_adoption_probability": true,
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
    include_exclusion_check=True, include_adoption_probability=True,
    client_tag="ginkou-A-2026Q2",
    filter={"tier": ["S", "A", "B"], "deadline_within_days": 90})
with open("triage_1000.csv", "w", newline="") as out:
    w = csv.writer(out)
    w.writerow(["corp", "top1_program", "fit_score", "adoption_prob", "exclusion_hit"])
    for r in sorted(res.results, key=lambda x: x.top_programs[0].fit_score, reverse=True):
        if not r.top_programs: continue
        top = r.top_programs[0]
        w.writerow([r.corp_number, top.program_id, top.fit_score, top.adoption_prob, r.exclusion_hits])
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
import fs from "node:fs";
const corps = fs.readFileSync("corps_1000.csv", "utf8")
  .split("\n").map(l => l.split(",")[0]).filter(Boolean);
const res = await jpcite.bulk_match_programs({
  corp_numbers: corps, top_n_per_corp: 5,
  include_exclusion_check: true, include_adoption_probability: true,
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
        {"program_id": "meti-mono-2026-r5", "fit_score": 0.82, "adoption_prob": "mid",
         "tier": "A", "deadline": "2026-07-31", "max_amount_jpy": 10000000,
         "source_url": "https://portal.monodukuri-hojo.jp/koubo/2026/r5/youkou.pdf"}
      ],
      "exclusion_hits": [],
      "client_tag": "ginkou-A-2026Q2"
    }
  ],
  "known_gaps": ["rate-limit 10 req/s で 1,000 社 約 2 分"],
  "recommended_followup": [
    "fit_score >= 0.75 の 87 社を優先架電",
    "0.60-0.75 の 234 社を案内 DM",
    "0.50-0.60 の 626 社を四半期再算定対象に編入"
  ]
}
```

## known gaps
- rate-limit 10 req/s: 1,000 社で約 2 分、10,000 社では async job + R2 ダウンロード方式 (時間 22 分)
- 市区町村独自補助金: 1,741 のうち RSS / API 提供は 280、残り 1,461 はスクレイピング週次バッチで 7-14 日 lag
- 個人事業主 / 任意団体: 法人番号未付番のため bulk_match 対象外
- adoption_prob: 過去 36 ヶ月の業種別採択率 + 類似企業の採択実績、データ薄い業種は "unknown"
- exclusion 抵触の前提条件: 納税状況 / 反社チェック / 役員兼任は jpcite では取得しない

## 関連 tool
- `bulk_match_programs` (本 recipe 中核、大量 法人番号 bulk マッチング)
- `get_corp_360` (個社深掘り、架電前の追加調査)
- `check_eligibility` (個別補助金の eligibility chain 確認)
- `apply_eligibility_chain_am` (Wave 21、複合補助金組合せ)
- `match_due_diligence_questions` (Wave 22、与信 DD 30-60 質問)

## 関連 recipe
- [r15-grant-saas-internal-enrich](../r15-grant-saas-internal-enrich/) — SaaS 内部 enrich、BPO の自社化 path
- [r24-houjin-6source-join](../r24-houjin-6source-join/) — 6 source join、素材 endpoint
- [r25-adoption-bulk-export](../r25-adoption-bulk-export/) — 採択 bulk export、後段の集計

## billable_units 試算
- 1 batch 1,000 units (法人 1 社 1 unit) × ¥3 = ¥3,000 / 委託
- 月 5 委託 = ¥15,000 / 月 (税込 ¥16,500)
- 月 20 委託 = ¥60,000 / 月 (税込 ¥66,000)
- ROI: 委託元から ¥30-100 / 社 受領前提なら ¥30,000-100,000 / 委託で 10-33x 粗利

## 商業利用条件
- PDL v1.0 + CC-BY-4.0、出典明記必須
- 委託元 (地銀 / 商工会 / メガバンク) への再配布時は jpcite 出典明記必須
- 法人番号は公開情報 — 個別社名と紐付けても 個人情報保護法対象外
- BPO 内部の triage ロジック (fit_score 閾値 / 優先架電基準) は二次著作物扱い

## 業法 fence
- BPO は情報整理のみ、申請代行は別資格者 (中小企業診断士 / 行政書士 / 公認会計士 / 税理士) へ受渡し
- 個人情報保護法 — 法人番号は対象外、代表者氏名 / 担当者連絡先 等は別途同意 + 安全管理
- 下請法 / 独禁法 — 親会社→傘下企業へのトリアージ結果押し付けは優越的地位の濫用に抵触し得る
- 景表法 — 採択確率帯 (low/mid/high) は統計推定、保証ではない旨を artifact に明記

## canonical_source_walkthrough

> 一次資料 / canonical source への walk-through。Wave 21 C6 で全 30 recipes に追加。

### 使う tool
- **MCP tool**: `subsidy_combo_finder + bulk fan-out`
- **REST endpoint**: `/v1/programs/combo (1000 客 bulk)`
- **jpcite.com docs**: <https://jpcite.com/recipes/r09-bpo-grant-triage-1000/>

### expected output
- JSON × 1000: triage_score[A/B/C] + recommended_program_ids[3]
- 全 response に `fetched_at` (UTC ISO 8601) + `source_url` (一次資料 URL) 必須
- `_disclaimer` envelope (税理士法 §52 / 行政書士法 §1 / 司法書士法 §3 / 弁護士法 §72 等の業法 fence 該当時)

### 失敗時 recovery
- **404 Not Found**: client_profiles 未登録 — 事前 POST バッチで登録
- **429 Too Many Requests**: parent/child API key 5 並列 (mig 086)
- **5xx / timeout**: Cloudflare cache hit を狙う、12:00-15:00 JST 推奨

### canonical source (一次資料)
- 国税庁 適格事業者公表サイト: <https://www.invoice-kohyo.nta.go.jp/>
- 中小企業庁 補助金一覧: <https://www.chusho.meti.go.jp/>
- e-Gov 法令検索: <https://laws.e-gov.go.jp/>
- 国立国会図書館 NDL: <https://www.ndl.go.jp/>
- jpcite 一次資料 license 表: <https://jpcite.com/legal/licenses>
