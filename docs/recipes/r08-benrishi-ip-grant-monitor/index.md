---
title: "弁理士の知財補助金モニター"
slug: "r08-benrishi-ip-grant-monitor"
audience: "弁理士"
intent: "ip_grant_monitor"
tools: ["search_programs", "get_corp_360", "list_deadlines"]
artifact_type: "ip_grant_list.json"
billable_units_per_run: 10
seo_query: "弁理士 知財 特許 補助金 助成 マッチング"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 弁理士の知財補助金モニター

## 想定 user
特許事務所 (弁理士 1-15 人体制、顧問先 30-200 社) で、出願費用補助・中小企業海外出願補助金 (JPO)・INPIT 知財総合支援窓口の地域伴走補助・産業財産権訴訟費用補助・職務発明支援等の助成制度を顧問先別に month-by-month watch する弁理士。月 5-50 件の新規出願・年 30-150 件のオフィス・アクション応答を抱えつつ、顧問先の出願戦略相談で「使える補助金を見落とすと中堅企業からの紹介経路が痩せる」事務所が想定読者。月初の月次レポート (顧問先別の出願済 + 出願予定 + 締切 30 日内補助金) を 5 分以内に書き出す運用を目標とする。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料、JST 翌日 00:00 リセット)
- `X-Client-Tag` ヘッダー (顧問先別の billable_units 計上、後の請求書発行に使用)
- 顧問先の法人番号リスト (13 桁) と (任意) 出願人コード (8 桁)
- 関心キーワード (特許 / 意匠 / 商標 / 海外出願 / PCT / マドプロ等)
- (推奨) 過去 5 年の出願実績 (公報番号 + 出願日 + IPC) — fit_score 計算に使用

## 入力例
```json
{
  "keywords": ["特許", "海外出願", "PCT"],
  "corp_size": "sme",
  "corp_numbers": ["7010001234567", "8010001234568"],
  "include": ["jpo_subsidy", "inpit_local", "prefecture_ip", "tax_credit_rd"],
  "deadline_within_days": 60,
  "language": "ja"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: client-001" \
  "https://api.jpcite.com/v1/programs/search?keyword=知財&size=sme&deadline_within_days=60"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/corp/7010001234567/ip_subsidy_match?lookback_years=5"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/programs/deadlines?source=jpo&within_days=60"
```
### Python
```python
import os
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="client-001")
rows = []
for hb in open("ip_clients.txt").read().split():
    matches = c.search_programs(keywords=["特許", "海外出願"], corp_size="sme",
                                 corp_number=hb, deadline_within_days=60,
                                 include=["jpo_subsidy", "inpit_local", "prefecture_ip"])
    rows.append({"corp": hb, "candidates": [m.program_id for m in matches[:3]]})
import pandas as pd
pd.DataFrame(rows).to_excel("ip_monitor_2026-05.xlsx", index=False)
```
### TypeScript
```ts
import { jpcite } from "@jpcite/sdk";
import fs from "node:fs";
const corps = fs.readFileSync("ip_clients.txt", "utf8").split("\n").filter(Boolean);
const rows: any[] = [];
for (const hb of corps) {
  const r = await jpcite.search_programs({
    keywords: ["特許", "海外出願"], corp_size: "sme", corp_number: hb, deadline_within_days: 60,
  });
  rows.push({ corp: hb, candidates: r.slice(0, 3).map(m => m.program_id) });
}
fs.writeFileSync("ip_monitor.json", JSON.stringify(rows, null, 2));
```

## 出力例 (artifact)
```json
{
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://www.jpo.go.jp/system/process/shutugan/joyaku/jouhou/hojo-josei.html",
  "matched_programs": [
    {"program_id": "jpo-sme-overseas-2026", "name": "中小企業等海外出願支援事業",
     "max_amount_jpy": 3000000, "subsidy_rate": "1/2", "deadline": "2026-06-15", "tier": "S"},
    {"program_id": "inpit-shutugan-r6", "name": "知財総合支援窓口 専門家派遣",
     "max_amount_jpy": 0, "subsidy_rate": "現物給付", "deadline": "通年", "tier": "A"}
  ],
  "client_attribution": {"client_tag": "client-001", "corp_number": "7010001234567"},
  "known_gaps": ["地方自治体独自の知財支援は逐次追加中"]
}
```

## known gaps
- INPIT 都道府県知財総合支援窓口は窓口ごとの運用差あり、本 recipe は中央 portal の公示分のみ
- PCT 出願補助 / マドプロ補助は申請窓口が JPO 本省 / 各経産局 / JETRO で分散
- 地方自治体独自の知財支援 (例: 東京都中小企業振興公社) は逐次追加、47 都道府県全件即時カバー未完了
- 研究開発税制 (措置法 §42-4) の知財関連加算は税理士領域、本 recipe は 項目整理 + 一次 URL まで

## 関連 tool
- `search_programs` (キーワード + 業種 + 締切で絞り込み)
- `get_corp_360` (法人 360 度ビュー、出願実績との突合)
- `list_deadlines` (60 日以内の締切カレンダー)
- `get_program_detail` (補助金原文の取得)
- `apply_eligibility_chain` (排他ルールチェック、公開版 21)

## 関連 recipe
- [r01-tax-firm-monthly-review](../r01-tax-firm-monthly-review/index.md) — 税理士月次、知財補助金 + 税制控除
- [r07-shindanshi-monthly-companion](../r07-shindanshi-monthly-companion/index.md) — 診断士月次伴走、事業計画 + 知財戦略
- [r29-municipal-grant-monitor](../r29-municipal-grant-monitor/index.md) — 市町村 IP 助成の差分配信

## billable_units 試算

- API fee delta: API fee delta の前提と再現式は [docs/canonical/cost_saving_examples.md](../../canonical/cost_saving_examples.md) を参照。
- 1 顧問先 1 回 = 10 units × ¥3 = ¥30 / 顧問先 / 月
- 顧問先 50 社 = ¥1,500 / 月、税込 ¥1,650 / 月
- 顧問先 100 社 = ¥3,000 / 月、税込 ¥3,300 / 月

## 商業利用条件
- PDL v1.0 + CC-BY-4.0、出典明記必須
- 月次レポート / 顧問先伴走資料への組込・印刷頒布 OK
- 第三者 (他事務所) への配布は別途要相談

## 業法 fence
- 弁理士法 §4 — 出願代理は弁理士独占、本 recipe は補助金マッチング情報の整理のみ
- 行政書士法 §1 — 申請書面作成は行政書士 / 認定支援機関、本 recipe は 項目整理 + 一次 URL まで
- 中小企業診断士登録規則 — 経営助言 / 事業計画の専門判断は診断士領域
- 景表法 §5 — `tier` / `subsidy_rate` は推定 / 公示値、保証ではない旨を 顧問先資料に注記推奨
