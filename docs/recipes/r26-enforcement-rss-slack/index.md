---
title: "行政処分 RSS → Slack 配信"
slug: "r26-enforcement-rss-slack"
audience: "横串 (リスク監視)"
intent: "enforcement_rss"
tools: ["get_enforcement", "search_enforcement", "get_corp_360"]
artifact_type: "enforcement_feed.xml"
billable_units_per_run: 1
seo_query: "行政処分 RSS Slack 配信 監視"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# 行政処分 RSS → Slack 配信

## 想定 user
銀行 / 信用金庫 / 監査法人 / 大手会計事務所 / 商工会連合会 / 損害保険会社 / 大手企業のコンプライアンス部署で、対象業種 (建設 / 金融 / 食品衛生 / 産廃 / 運送 / 介護 / 医療等) の行政処分 (営業停止 / 業務改善命令 / 是正勧告 / 免許取消) を RSS feed + Slack channel 配信で常時監視する用途。リスク早期把握 (融資審査の与信再評価 / 監査契約の独立性影響 / 取引先の信用毀損リスク) を目的とし、専任の 1 担当が毎日 5 分以内に新規処分を縦覧できる運用を設計する。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料)
- RSS reader (Feedly / Inoreader / Slack RSS app / Microsoft Teams RSS connector 等)
- 監視業種フィルタ (JSIC 中分類 or キーワード)
- (任意) Slack workspace + RSS app installed
- (任意) 監視対象法人番号リスト (取引先 / 顧問先 50-500 社)

## 入力例
```json
{
  "industry_filter": ["construction", "finance", "food_sanitation"],
  "format": "rss",
  "severity_min": "warning",
  "regions": ["national", "all_prefectures"],
  "client_tag": "compliance-rss-2026"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl "https://api.jpcite.com/v1/enforcement/rss?industry=construction,finance&severity_min=warning"

curl -H "X-API-Key: $JPCITE_API_KEY" \
  "https://api.jpcite.com/v1/enforcement-cases/mlit-2026-0511-001"

curl -X POST -H "X-API-Key: $JPCITE_API_KEY" -H "Content-Type: application/json" \
  -d '{"corp_numbers": ["7010001234567"], "since": "1d"}' \
  "https://api.jpcite.com/v1/enforcement/bulk_match"
```
### Python
```python
import os, feedparser
from jpcite import Client
c = Client(api_key=os.environ.get("JPCITE_API_KEY"))
feed = feedparser.parse("https://api.jpcite.com/v1/enforcement/rss?industry=construction,finance")
from datetime import datetime, timezone, timedelta
cutoff = datetime.now(timezone.utc) - timedelta(days=1)
for entry in feed.entries:
    pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    if pub >= cutoff:
        print(f"[{pub:%Y-%m-%d}] {entry.title} - {entry.link}")
```
### TypeScript
```ts
const r = await fetch(
  "https://api.jpcite.com/v1/enforcement/rss?industry=construction&format=json"
);
const items = await r.json();
for (const i of items.entries) {
  console.log(i.title, i.link, i.pubDate);
}
```

## 出力例 (artifact)
```xml
<rss version="2.0">
  <channel>
    <title>jpcite 行政処分 RSS (建設業)</title>
    <link>https://api.jpcite.com/v1/enforcement/rss</link>
    <description>建設業法 §28 等に基づく業務停止 / 監督処分 RSS</description>
    <item>
      <title>○○建設(株) 営業停止 30 日</title>
      <link>https://www.mlit.go.jp/totikensangyo/const/...</link>
      <pubDate>Mon, 11 May 2026 09:00:00 GMT</pubDate>
      <guid>mlit-2026-0511-001</guid>
      <category>建設業法 §28</category>
      <description>所在地: 東京都, 処分理由: ..., 出典: https://www.mlit.go.jp/...</description>
    </item>
  </channel>
</rss>
```

## known gaps
- 自治体独自処分は欠損あり (47 都道府県のうち独自 DB 提供は 22 県)、残り 25 県は四半期まとめ更新で 30-90 日 lag
- 個人事業主処分は別ストリーム、本 RSS は法人格を持つ事業者処分のみ
- 公表サイトの HTML 改編で約 5-8% リンク切れあり (sentinel 化済)
- 中小企業・個人事業主の処分は地方紙報道との突合で完全捕捉、本 RSS は中央 portal + 47 県の公示分のみ
- 名誉毀損リスクのため、社外への直接配信時は事業者名のマスキング検討推奨

## 関連 tool
- `get_enforcement` (個別処分の詳細)
- `search_enforcement` (キーワード + 業種 + severity + 期間で絞り込み)
- `get_corp_360` (法人 360 度ビュー、取引先 watch との突合)
- `enforcement_bulk_match` (法人番号 list との突合、取引先一括スクリーニング)

## 関連 recipe
- [r04-shinkin-borrower-watch](../r04-shinkin-borrower-watch/index.md) — 信金 watch、取引先与信再評価
- [r12-audit-firm-kyc-sweep](../r12-audit-firm-kyc-sweep/index.md) — 監査法人 KYC、独立性チェック
- [r23-slack-bot](../r23-slack-bot/index.md) — Slack bot 配信、社内 channel fan-out

## billable_units 試算
- RSS は 1 fetch 1 unit × ¥3
- 日次 30 件 fetch + 詳細 lookup = ¥90-300 / 月、税込 ¥99-330
- 取引先 500 社 突合 月次 = ¥1,500 / 月、税込 ¥1,650
- 初回 RSS reader 設定は 5 分 ¥0、運用継続コストのみ従量

## 商業利用条件
- PDL v1.0 (政府公表処分の再配布、出典明記必須) + CC-BY-4.0 (jpcite 編集物)
- RSS / Slack 配信時は jpcite + 一次資料 (mlit.go.jp 等) の両出典明記
- 社内コンプラ部署 + 監査調書への組込 OK、外部公表は事実通知に留める
- 公表処分情報は公知事実、不開示合意 (NDA) 対象外

## 業法 fence
- 公開処分情報は再配布 OK
- 個人特定は名誉毀損リスクあり、社内利用推奨、外部配信時は事業者名のマスキング検討
- 与信判断 / 取引中止 等の意思決定は社内ルール + 弁護士法 §72 (法的判断は弁護士)
- 景表法 §5 — RSS タイトルは事実通知に留め、評価表現 (悪質 / 危険) は避ける
