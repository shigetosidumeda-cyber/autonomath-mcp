# Slack Daily KPI Digest (jpcite)

更新日: 2026-05-12 (Wave 26)

jpcite 顧客向け Slack incoming webhook 連携。jpcite のデータ更新 (補助金 / インボイス / 法令) を 1 日 1 回、顧客自身の Slack ワークスペースに配信する。

本ドキュメントは以下の対になる:

- 既存 cron: [`scripts/cron/send_daily_kpi_digest.py`](../../scripts/cron/send_daily_kpi_digest.py) (Wave 21、operator 向け mail digest)
- 新規 fanout: 顧客 token 別 Slack webhook 配信 (Wave 26)
- 受信側 Function: [`functions/webhook_router.ts`](../../functions/webhook_router.ts) (汎用 router、Slack / Discord / Teams 切替)

## 1. 構成図

```
jpcite cron (06:00 JST)
  └─ send_daily_kpi_digest.py (mail to info@bookyou.net)
      └─ dispatch_webhooks.py (Wave 21)
          └─ HTTPS POST → 顧客 Slack incoming webhook URL
              └─ Block Kit JSON
```

cron は既存のまま再利用する。新規追加は次の 2 点:

1. `dispatch_webhooks.py` の payload に **3 セクション** (補助金 / インボイス / 法令) を追加し Slack Block Kit 形式に固定。
2. 顧客側 webhook URL の登録 API (`POST /v1/me/webhooks`、既存) に `target=slack_digest` を許容、daily cron が走るときに `event_types=["digest.daily"]` の row を fanout 対象に含める。

## 2. 配信 payload (Block Kit)

```json
{
  "text": "jpcite daily digest 2026-05-12",
  "blocks": [
    { "type": "header", "text": { "type": "plain_text", "text": "jpcite daily digest" } },
    {
      "type": "section",
      "text": { "type": "mrkdwn", "text": "*補助金*\n• 新規 3 件 / 改正 1 件 / 終了予告 2 件\n<https://jpcite.com/programs/...|詳細>" }
    },
    {
      "type": "section",
      "text": { "type": "mrkdwn", "text": "*インボイス*\n• 登録事業者 12 件追加 / 取消 0 件\n<https://jpcite.com/invoice/...|詳細>" }
    },
    {
      "type": "section",
      "text": { "type": "mrkdwn", "text": "*法令*\n• 施行 1 件 (改正) / Pubcomment 2 件\n<https://jpcite.com/laws/...|詳細>" }
    },
    {
      "type": "context",
      "elements": [{ "type": "mrkdwn", "text": "jpcite · 出典: e-Gov / NTA / METI · §52 ご利用上の注意付き" }]
    }
  ]
}
```

3 セクション (補助金 / インボイス / 法令) は固定。空セクションでも省略せず「変化なし」と表示することで「dashboard 開かなくても安心して見送れる」状態を作る (`monitoring_digest` 設計と整合)。

## 3. 顧客側登録手順

### 3.1 Slack incoming webhook 取得

1. Slack workspace → Apps → "Incoming Webhooks" → "Add to Slack"
2. 配信したい channel を選択 → "Add Incoming WebHooks integration"
3. 表示された `https://hooks.slack.com/services/T.../B.../...` をコピー

### 3.2 jpcite 側登録

```bash
curl -X POST https://api.jpcite.com/v1/me/webhooks \
  -H "X-API-Key: $JPCITE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "https://hooks.slack.com/services/T.../B.../...",
    "event_types": ["digest.daily"],
    "format": "slack_blocks",
    "label": "ops-daily-digest"
  }'
```

レスポンスに 1 度だけ表示される `secret_hmac` を Slack 側で再利用する必要はない (Slack incoming webhook は URL 自体が秘匿)。jpcite 内部での HMAC 計算用に保存しておくと、後段で webhook router を経由したい場合に再利用できる。

### 3.3 配信時刻 / 課金

- 配信時刻: 毎日 21:00 UTC (06:00 JST) ±5 分。
- 課金: 配信 1 通 = 1 unit (¥3)。空セクション = 「変化なし」と表示するが課金は発生する (jpcite が裏で集計 + ingest している分の対価)。
- 失敗時: 5 回連続 5xx で webhook 自動 disable (`customer_webhooks.status='disabled'`)。再有効化は DELETE → 再登録。

## 4. ローカルで dry-run

```bash
JPINTEL_DB_PATH=/Users/shigetoumeda/jpcite/data/jpintel.db \
  python scripts/cron/send_daily_kpi_digest.py --dry-run --format slack_blocks
```

`--format slack_blocks` を指定すると Block Kit JSON を stdout に吐く。それを Slack の [Block Kit Builder](https://app.slack.com/block-kit-builder) に貼って表示を確認できる。

## 5. 統制と FAQ

- **Free 顧客 (anon 3/日)** には配信しない。`event_types=["digest.daily"]` の webhook 登録には paid key が必要 (一般的な metered surface と同じ)。
- **disclaimer** は context block に必ず付与 (`tax_rulesets._TAX_DISCLAIMER` 由来、§52)。
- **opt-out** は `DELETE /v1/me/webhooks/{id}` のみ。電話 / メール経由の解除依頼は受けない (`feedback_zero_touch_solo`)。
- 旧 brand (税務会計AI / AutonoMath) は payload に含めない。
