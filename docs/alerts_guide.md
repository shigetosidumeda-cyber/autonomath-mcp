# Amendment Alerts

制度改正アラートは、jpcite が追跡している制度・法令・税制情報に重要な変更が見つかったとき、メールまたは Webhook で通知する機能です。

- アラート登録は無料です。
- 通知先にはメール、Webhook、またはその両方を指定できます。
- すべての制度改正を漏れなく検知する保証はありません。重要な申請や判断では、一次資料や担当窓口も確認してください。

## 通知される内容

| severity | 例 |
|---|---|
| `critical` | 制度終了、重要な適用期間変更、利用可否に直結する変更 |
| `important` | 補助上限、対象者、対象経費、申請期間などの変更 |
| `info` | 出典更新、表記変更、軽微な整理 |

## 登録

```bash
curl -X POST https://api.jpcite.com/v1/me/alerts/subscribe \
  -H "X-API-Key: jc_..." \
  -H "Content-Type: application/json" \
  -d '{
    "filter_type": "program_id",
    "filter_value": "UNI-1111111111",
    "min_severity": "important",
    "webhook_url": "https://hooks.example.com/jpcite-alerts",
    "email": "alerts@example.com"
  }'
```

| field | type | required | description |
|---|---|---:|---|
| `filter_type` | string | yes | `tool` / `law_id` / `program_id` / `industry_jsic` / `all` |
| `filter_value` | string | conditional | `filter_type` が `all` 以外の場合に必須 |
| `min_severity` | string | no | `critical` / `important` / `info` |
| `webhook_url` | string | conditional | HTTPS のみ。`webhook_url` か `email` のどちらか必須 |
| `email` | string | conditional | 通知先メールアドレス |

## 一覧

```bash
curl https://api.jpcite.com/v1/me/alerts/subscriptions \
  -H "X-API-Key: jc_..."
```

## 削除

```bash
curl -X DELETE https://api.jpcite.com/v1/me/alerts/subscriptions/42 \
  -H "X-API-Key: jc_..."
```

## Webhook payload

```json
{
  "schema": "jpcite.amendment.v1",
  "ts": "2026-05-01T00:00:00+09:00",
  "subscription_id": 42,
  "record_id": "UNI-1111111111",
  "record_kind": "program",
  "severity": "important",
  "field_name": "application_period",
  "source_url": "<公式公募要領URL>",
  "observed_at": "2026-05-01T00:00:00+09:00"
}
```

## Webhook URL の条件

- `https://` の URL のみ登録できます。
- ローカルネットワーク、ループバック、リンクローカル IP は登録できません。
- 配信に失敗した場合、一定回数だけ再試行します。

## 注意事項

制度改正アラートは、調査の起点として使う補助通知です。通知が来ないことは、改正が存在しないことの保証ではありません。最終確認は一次資料で行ってください。

## 関連

- [webhooks.md](./webhooks.md) — 構造化イベントの Webhook
- [dashboard_guide.md](./dashboard_guide.md) — ダッシュボードでの操作
