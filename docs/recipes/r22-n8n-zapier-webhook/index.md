---
title: "n8n / Zapier Webhook"
slug: "r22-n8n-zapier-webhook"
audience: "no-code 自動化"
intent: "webhook_automation"
tools: ["search_programs", "get_corp_360", "list_adoptions"]
artifact_type: "n8n_workflow.json"
billable_units_per_run: 1
seo_query: "n8n Zapier jpcite Webhook 自動化"
total_time: "PT5M"
date_created: "2026-05-11"
date_modified: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# n8n / Zapier Webhook

## 想定 user
コードを書かずに n8n / Zapier / Make / IFTTT でワークフロー化したい中小企業のバックオフィス担当 / 経営企画 / 補助金担当者で、jpcite の補助金新規公示・採択公表・行政処分・適格事業者抹消を Slack / Microsoft Teams / Discord / メール / LINE Notify / Google Sheets / Notion 等に流す自動化を 5 分で構築する。Cron トリガー (n8n は ¥0 セルフホスト可、Zapier は月 ¥0-2,500 から、Make は月 ¥0-1,650 から) と HTTP Request ノード / Webhooks ノードの組み合わせで完結。

## 必要な前提
- jpcite API key (標準従量料金、初回 3 req/IP/日無料、JST 翌日 00:00 リセット)
- n8n / Zapier / Make / IFTTT アカウント
- Cron トリガー or Webhook 受信 endpoint
- (任意) 通知先 channel (Slack workspace + bot token / Teams webhook URL / Discord webhook URL / LINE Notify token 等)

## 入力例
```json
{
  "trigger": "cron 0 9 * * 1",
  "endpoint": "/v1/programs/new?since={{$node['Cron'].lastrun}}",
  "auth_header": "X-API-Key: {{$env.JPCITE_API_KEY}}",
  "client_tag": "n8n-mon-2026",
  "notify_channel": "#grant-watch"
}
```

## 実行 (curl / Python / TypeScript)
### curl
```bash
curl -H "X-API-Key: $JPCITE_API_KEY" -H "X-Client-Tag: n8n-mon-2026" \
  "https://api.jpcite.com/v1/programs/new?since=2026-05-04&prefecture=東京都"

curl -X POST -H "Content-Type: application/json" \
  -d '{"text":"新規補助金 3 件: ..."}' \
  "$SLACK_WEBHOOK_URL"
```
### Python
```python
import os, requests
r = requests.get("https://api.jpcite.com/v1/programs/new",
    headers={"X-API-Key": os.environ["JPCITE_API_KEY"], "X-Client-Tag": "n8n-mon-2026"},
    params={"since": "2026-05-04", "prefecture": "東京都"})
new_programs = r.json().get("new_programs", [])
print(f"{len(new_programs)} 件の新規公示")
```
### TypeScript
```ts
// n8n / Zapier ノード設定 (TS 側コード不要)
// HTTP Request ノード:
// Method: GET, URL: https://api.jpcite.com/v1/programs/new?since={{$node['Cron'].json.lastrun}}
// Auth: Header Auth, Name: X-API-Key, Value: {{$env.JPCITE_API_KEY}}
```

## 出力例 (artifact)
```json
{
  "fetched_at": "2026-05-11T09:00:00Z",
  "source_url": "https://www.chusho.meti.go.jp/...",
  "since": "2026-05-04T00:00:00+09:00",
  "new_programs": [
    {"program_id": "meti-mono-2026-r5", "name": "ものづくり補助金 第18次", "deadline": "2026-06-30", "tier": "S"},
    {"program_id": "tokyo-dx-r6", "name": "東京都 DX 推進補助金", "deadline": "2026-07-15", "tier": "A"}
  ],
  "trigger": "n8n cron 0 9 * * 1",
  "client_tag": "n8n-mon-2026",
  "known_gaps": ["municipal feed 7-14d lag", "n8n/Zapier 最小 cron 間隔依存"]
}
```

## known gaps
- n8n / Zapier / Make の cron 最小間隔に依存 (free tier では 15 分間隔、有料 plan で 1 分間隔)
- Make は料金プランで月実行回数上限あり
- 自治体補助金は週次差分のみ補完、即時公示 watch には RSS recipe (r29) と併用推奨
- Webhook 受信側の rate-limit (Slack 1 msg/s/channel) に注意
- n8n self-host (Docker) は ¥0、有料 plan は月 ¥2,500+

## 関連 tool
- `search_programs` (キーワード + 業種 + 地域 + tier)
- `list_programs_new` (since 指定の差分取得、cron 用)
- `get_corp_360` (法人 360 度ビュー、顧客 sweep)
- `list_adoptions` (採択履歴)
- `get_enforcement` (行政処分配信)

## 関連 recipe
- [r23-slack-bot](../r23-slack-bot/index.md) — Slack bot 配信、所内チャンネル fan-out
- [r26-enforcement-rss-slack](../r26-enforcement-rss-slack/index.md) — 行政処分 RSS、リスク監視
- [r29-municipal-grant-monitor](../r29-municipal-grant-monitor/index.md) — 市町村独自補助金モニター

## billable_units 試算
- 1 req 1 unit × ¥3 = ¥3
- 週次 cron 4 回 + 月 1,000 req = ¥3,000 / 月、税込 ¥3,300
- 日次 cron 20 営業日 + 月 5,000 req = ¥15,000 / 月、税込 ¥16,500
- 初回 workflow 構築は 30 分 ¥0、運用継続コストのみ従量

## 商業利用条件
- PDL v1.0 + CC-BY-4.0
- 配信時は jpcite 出典 (`source_url`) 明記
- 社内 channel 配信 OK、外部配信 (SaaS 経由) は jpcite 出典明記の上で可
- n8n / Zapier / Make の各利用規約も併読

## 業法 fence
- 自動配信は事実情報のみ、申請助言は資格者経由 (税理士法 §52 / 行政書士法 §1)
- 利用者の業務範囲を超える助言を出力しない (Webhook → LLM 経由で生成する場合)
- 業法 fence — 配信は scaffold + 一次 URL まで、個別判断は資格者
- 景表法 §5 — `tier` / `subsidy_rate` は推定値、保証ではない旨を配信文末に注記推奨
