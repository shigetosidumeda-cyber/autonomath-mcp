---
title: "Zapier zap template — jpcite triggered automation"
slug: "zapier-jpcite-integration"
audience: "no-code ops / SMB owner"
intent: "zapier_automation"
related_tools: ["search_programs", "check_invoice_status", "enforcement.rss"]
billable_units_per_run: 3
date_created: "2026-05-11"
license: "PDL v1.0 / CC-BY-4.0"
---

# Zapier zap template — jpcite triggered automation

ノーコードで jpcite を 100+ SaaS に繋ぐ Zapier zap テンプレ集。Slack 通知 / Google Sheets 追記 / Gmail 送信 / Salesforce 更新 等の代表 5 パターン。

## 想定 user

- エンジニアを抱えていない中小企業オーナー / 営業マネージャー
- 月 ¥2,000-5,000 の Zapier プランで自動化を組みたい
- jpcite ¥3/req × Zapier task ¥30/task = 合計 ¥33/run でも回したい

## zap #1: 新着 S 級補助金 → Slack 通知

**Trigger**: Schedule by Zapier (daily 09:00 JST)
**Action 1**: Webhooks by Zapier — GET https://api.jpcite.com/v1/programs/search?tier=S&since=24h
  - Headers: `X-API-Key: {{JPCITE_API_KEY}}`
**Action 2**: Filter by Zapier — `results.count > 0`
**Action 3**: Looping by Zapier — iterate over `results[]`
**Action 4**: Slack — Send Channel Message
  - Channel: `#corp-grants`
  - Message: `🆕 新着 S 級補助金: *{{name}}* (期限 {{application_deadline}}) — <{{source_url}}|出典>`

billable: 制度数 req (avg 2-5/日) ≈ ¥10-15/日

## zap #2: 適格事業者抹消 → Google Sheets ログ

**Trigger**: RSS by Zapier — https://api.jpcite.com/v1/invoice/revoked.rss
**Action 1**: Filter — `title contains "抹消"`
**Action 2**: Webhooks — GET https://api.jpcite.com/v1/invoice/{{T番号抽出}}
**Action 3**: Google Sheets — Create Spreadsheet Row
  - Spreadsheet: 適格事業者 抹消ログ
  - Row: T番号 / 法人名 / 抹消日 / 理由 / source_url

billable: RSS は無料、Webhook は 1 req/件 = ¥3/件

## zap #3: 自社業界の補助金マッチ → Email

**Trigger**: Schedule (weekly 月曜 08:00 JST)
**Action 1**: Code by Zapier (Python) —
  ```python
  import urllib.request, json
  url = "https://api.jpcite.com/v1/programs/match?jsic=E&pref=27&top_n=5"
  req = urllib.request.Request(url, headers={"X-API-Key": input_data["api_key"]})
  data = json.loads(urllib.request.urlopen(req).read())
  output = {"hits": "\n".join(
      f"・{p['name']} (tier {p['tier']}) → {p['source_url']}" for p in data["results"]
  )}
  ```
**Action 2**: Gmail — Send Email
  - To: 自社代表 + 顧問税理士
  - Subject: 今週の補助金 (JSIC E / 大阪府)
  - Body: `{{hits}}`

billable: 1 req/週 × ¥3 = ¥12/月

## zap #4: 法令改正 watch → Salesforce Lead 自動作成

**Trigger**: Webhook (jpcite saved_search webhook out)
**Action 1**: Filter — `amendment.severity > 7`
**Action 2**: Salesforce — Create Lead
  - Company: `{{affected_industry}}`
  - Status: 法令改正 alert
  - Description: `{{amendment.summary}} — affected_programs: {{affected_program_ids}}`

billable: webhook out は anonymous OK、Salesforce 連携のみ

## zap #5: 採択公表 → Twitter 投稿 (社外 PR 用)

**Trigger**: Schedule (毎月 1 日)
**Action 1**: Webhook — GET https://api.jpcite.com/v1/adoptions/recent?months=1&tier=S
**Action 2**: Formatter — 採択件数を 280 文字以内に整形
**Action 3**: Twitter — Create Tweet
  - Content: `先月のものづくり補助金 採択: {{count}} 件 (前月比 {{diff}})。jpcite で日次集計→ https://jpcite.com/dashboard`

billable: 1 req/月 × ¥3 = ¥3/月

## デプロイ手順

1. [Zapier](https://zapier.com) で空 zap 作成
2. Trigger / Action は上記表どおりに選択
3. `JPCITE_API_KEY` は Zapier の Built-in Account か Webhook の Header に
4. Test → Turn on → 日次運用開始

## known gaps

- Zapier 無料プランは月 100 task まで、jpcite cron と合わせて使用量管理
- jpcite anonymous は 3 req/日/IP、Zapier 経由は API key 必須
- Twitter API は 2026 年現在 read-only on free tier、有料化必要

## canonical source

- Zapier docs: <https://help.zapier.com/>
- jpcite REST API: <https://api.jpcite.com/docs>
- recipes/r22 n8n/zapier webhook: <https://jpcite.com/recipes/r22-n8n-zapier-webhook/>
