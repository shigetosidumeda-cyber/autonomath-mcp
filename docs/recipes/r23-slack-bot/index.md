---
title: "Slack bot で社内チャンネル配信"
slug: "r23-slack-bot"
audience: "Slack bot 運用"
intent: "slack_distribution"
tools: ["search_programs", "list_adoptions", "get_enforcement"]
artifact_type: "slack_app_manifest.yaml"
billable_units_per_run: 1
seo_query: "Slack bot jpcite 補助金 配信"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# Slack bot で社内チャンネル配信

## 想定 user
社内 Slack workspace を持つ士業事務所 (税理士 / 行政書士 / 中小企業診断士)、補助金 SaaS スタートアップ、信用金庫 / 商工会 / 商工会議所の渉外担当部、コンサル会社、地銀の中小企業支援部、で「補助金 watch」「適格事業者 alert」「行政処分 watch」channel を作り、顧問先 / 取引先 / 会員企業 50-500 社の差分通知を毎朝 9 時 (or 任意 cadence) に配信する運用。Slack 内で URL クリックで一次資料へ遷移、bot reply で詳細問合せも可能化。GitHub Actions / Fly cron / n8n / Cloud Functions の cron 経由で `chat.postMessage` を呼ぶ構成。

## 必要な前提
- jpcite API key (¥3/req、初回 3 req/IP/日無料)
- Slack workspace
- Slack App 作成権限 + Bot token (`xoxb-...`)
- 配信先 channel (`#grant-watch` 等) + bot を channel に invite 済
- Cron 環境 (GitHub Actions / Fly cron / n8n / Cloud Functions / Lambda 等)

## 入力例
```json
{
  "corp_numbers": ["7010001234567", "8010001234568"],
  "channel": "#grant-watch",
  "schedule": "0 9 * * 1-5",
  "events": ["new_adoption", "new_enforcement", "invoice_revoke"],
  "client_tag": "slackbot-2026",
  "since_window": "1d"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: slackbot-2026" \
  "https://api.jpcite.com/v1/corp/7010001234567/delta?since=1d&events=new_adoption,new_enforcement"

curl -X POST -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"channel":"#grant-watch","text":"[新規採択] サンプル製作所(株) - ものづくり補助金 第18次"}' \
  "https://slack.com/api/chat.postMessage"
```
### Python
```python
import os
from slack_sdk import WebClient
from jpcite import Client
c = Client(api_key=os.environ["JPCITE_API_KEY"], client_tag="slackbot-2026")
slack = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
corps = open("watch_list.txt").read().split()
for hb in corps:
    delta = c.get_corp_delta(corp_number=hb, since="1d",
                              events=["new_adoption", "new_enforcement"])
    if delta.has_changes:
        text = f"[{hb}] 新規採択 {len(delta.new_adoptions)} 件 + 行政処分 {len(delta.new_enforcements)} 件"
        slack.chat_postMessage(channel="#grant-watch", text=text)
```
### TypeScript
```ts
import { WebClient } from "@slack/web-api";
import { jpcite } from "@jpcite/sdk";
const slack = new WebClient(process.env.SLACK_BOT_TOKEN);
const corps = (await Bun.file("watch_list.txt").text()).trim().split("\n");
for (const hb of corps) {
  const delta = await jpcite.get_corp_delta({
    corp_number: hb, since: "1d", events: ["new_adoption", "new_enforcement"],
    client_tag: "slackbot-2026",
  });
  if (delta.has_changes) {
    await slack.chat.postMessage({
      channel: "#grant-watch",
      text: `[${hb}] 新規採択 ${delta.new_adoptions.length} 件 (出典: ${delta.source_url})`,
    });
  }
}
```

## 出力例 (artifact)
```json
{
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://www.chusho.meti.go.jp/...",
  "scanned_corps": 50,
  "delta_corps": 7,
  "posted_to": "#grant-watch",
  "messages_posted": 7,
  "messages_sample": [
    {
      "corp": "7010001234567",
      "type": "new_adoption",
      "title": "ものづくり補助金 第18次 採択",
      "amount_jpy": 12000000,
      "source_url": "https://portal.monodukuri-hojo.jp/..."
    }
  ],
  "client_tag": "slackbot-2026",
  "known_gaps": ["Slack 配信は API レート (1 msg/s/channel)", "大量 corp の配信は Block Kit パジネーション要"]
}
```

## known gaps
- Slack 配信は API レート (1 msg/s/channel) — 50 社で約 1 分、500 社では Block Kit + summary パターン推奨
- Block Kit のテキスト上限は 3,000 文字 / block、長文は分割
- 大量 channel 跨ぎ配信は `slack.conversations.list` で channel ID 取得を事前 cache 化
- Slack Free workspace は履歴 90 日制限、長期 retention は Standard 以上
- Bot token のスコープ (`chat:write` + `channels:read`) 不足は post 失敗、再 install で scope 追加

## 関連 tool
- `search_programs` (キーワード + 業種 + 地域 + tier)
- `list_adoptions` (採択履歴縦覧)
- `get_enforcement` (行政処分配信)
- `get_corp_delta` (法人別差分取得、bot の主力)
- `check_invoice_status` (適格事業者状況)

## 関連 recipe
- [r22-n8n-zapier-webhook](../r22-n8n-zapier-webhook/) — n8n / Zapier、ノーコード接続
- [r26-enforcement-rss-slack](../r26-enforcement-rss-slack/) — 行政処分 RSS 配信
- [r28-edinet-program-trigger](../r28-edinet-program-trigger/) — EDINET 連動、有報連動 alert

## billable_units 試算
- 1 件 1 unit × ¥3 = ¥3
- 顧問先 50 社 × 20 営業日 = ¥3,000 / 月、税込 ¥3,300
- 顧問先 500 社 × 20 営業日 = ¥30,000 / 月、税込 ¥33,000
- 初回 Slack App 作成 + bot token 取得は 15 分 ¥0、運用継続コストのみ従量

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- Slack 投稿に jpcite 出典 (`source_url`) 明記
- 社内利用範囲では問題なし、外部配信 (顧問先への Slack Connect 共有) は別契約 / 出典明記の上で可
- Slack 利用規約 (商用利用条項 + データ取扱) も併読

## 業法 fence
- bot は事実配信のみ、助言は資格者
- 社内利用範囲では問題なし、外部配信は別契約
- 業法 fence (税理士法 §52 / 行政書士法 §1 / 弁護士法 §72) — bot 出力は scaffold、個別助言は資格者
- 景表法 §5 — `tier` / `subsidy_rate` は推定値、配信文末に注記推奨

## canonical_source_walkthrough

> 一次資料 / canonical source への walk-through。Wave 21 C6 で全 30 recipes に追加。

### 使う tool
- **MCP tool**: `Slack bot + audit-log RSS`
- **REST endpoint**: `/v1/audit-log.rss + Slack webhook`
- **jpcite.com docs**: <https://jpcite.com/recipes/r23-slack-bot/>

### expected output
- Slack channel: 採択公表/改正/処分 1h 周期 post
- 全 response に `fetched_at` (UTC ISO 8601) + `source_url` (一次資料 URL) 必須
- `_disclaimer` envelope (税理士法 §52 / 行政書士法 §1 / 司法書士法 §3 / 弁護士法 §72 等の業法 fence 該当時)

### 失敗時 recovery
- **404 Not Found**: Slack webhook URL 失効 — Slack 側 reissue
- **429 Too Many Requests**: Slack 側 rate limit 1 msg/sec — batch 化
- **5xx / timeout**: Slack outage は statuspage.slack.com で確認

### canonical source (一次資料)
- 国税庁 適格事業者公表サイト: <https://www.invoice-kohyo.nta.go.jp/>
- 中小企業庁 補助金一覧: <https://www.chusho.meti.go.jp/>
- e-Gov 法令検索: <https://laws.e-gov.go.jp/>
- 国立国会図書館 NDL: <https://www.ndl.go.jp/>
- jpcite 一次資料 license 表: <https://jpcite.com/legal/licenses>
