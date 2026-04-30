# Amendment Alerts

制度時系列の記録のうち **確定日付フィールド (`effective_from` / `effective_until`) が NULL でない部分集合** に対する schema-level 差分を Webhook + Email で配信する best-effort 通知。

- **subscription は無料** (¥3/req に追加課金しない)
- 認証 API key 必須、self-serve
- 網羅性は保証しない (下記カバレッジ参照)

## カバレッジ (2026-04-29 時点)

| 列 | 値が入っている行 | 比率 | alert への寄与 |
|----|------|------|----------------|
| `effective_from` | 140 / 14,596 | 約 0.96% | `important` 判定の入力 |
| `effective_until` | 4 / 14,596 | 約 0.027% | `critical` 判定 (制度終了) の入力 |
| `eligibility_hash` | 14,596 / 14,596 | 100% (v1/v2 で値が変化しない既知制約により現状 dormant) | (現状 dormant) |

**全 14,596 行を網羅した historical diff tracking は提供していない。** 「全制度改正を漏れなく検知したい」目的で本機能だけに依存しないこと。一次資料 (e-Gov 法令、各省庁告示、自治体公報) の自前監視を併用。本機能は polling 削減用の補助通知。

## Severity 判定 (deterministic、ML なし)

- `critical` — `effective_until` が新規設定 (制度終了) — 現状 4 行のみ
- `important` — `amount_max_yen` / `subsidy_rate_max` / `target_set_json` / `effective_from` のいずれかが変化 — 現状 140 行台
- `info` — 上記以外 (出典再取得・cosmetic 修正)

`eligibility_hash` 起因の critical 判定はコード上残存するが、v1/v2 間ハッシュ固定の既知制約で現状 dormant。upstream 改修後に有効化される。

## エンドポイント

すべて `X-API-Key` 必須。匿名は 401。

### POST `/v1/me/alerts/subscribe`

```bash
curl -X POST https://api.jpcite.com/v1/me/alerts/subscribe \
  -H "X-API-Key: am_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "filter_type": "law_id",
    "filter_value": "law_345AC0000000050",
    "min_severity": "critical",
    "webhook_url": "https://hooks.example.com/autonomath",
    "email": "ops@example.com"
  }'
```

| field | type | required | description |
|-------|------|----------|-------------|
| `filter_type` | enum | yes | `tool` / `law_id` / `program_id` / `industry_jsic` / `all` |
| `filter_value` | string | conditional | `filter_type != 'all'` で必須 |
| `min_severity` | enum | no (default `important`) | `critical` / `important` / `info` |
| `webhook_url` | string | conditional | HTTPS のみ、internal IP block。`webhook_url` か `email` のどちらか必須 |
| `email` | email | conditional | 同上 |

#### Webhook URL の制限

- `https://` のみ。`http://` / scheme 無し / その他は 400
- `127.0.0.1` / `10.*` / `172.16-31.*` / `192.168.*` / `::1` / `fc00::/7` / `169.254.*` は 400
- cron 配信時に DNS rebind 再検査 (host を resolve、private IP に落ちると skip)

#### Response (201)

```json
{
  "id": 42,
  "filter_type": "law_id",
  "filter_value": "law_345AC0000000050",
  "min_severity": "critical",
  "webhook_url": "https://hooks.example.com/autonomath",
  "email": "ops@example.com",
  "active": true,
  "created_at": "2026-04-25T05:52:04+00:00",
  "updated_at": "2026-04-25T05:52:04+00:00",
  "last_triggered": null
}
```

### GET `/v1/me/alerts/subscriptions`

active な subscription のみ返す (`active=0` 除外)。

```bash
curl https://api.jpcite.com/v1/me/alerts/subscriptions \
  -H "X-API-Key: am_xxx"
```

### DELETE `/v1/me/alerts/subscriptions/{id}`

soft-delete (`active = 0`)、row は audit 用に残る。

```bash
curl -X DELETE https://api.jpcite.com/v1/me/alerts/subscriptions/42 \
  -H "X-API-Key: am_xxx"
```

`{"ok": true, "id": 42}`。他人の id 指定は **404** (id 列挙不可)。

## Webhook payload

```json
{
  "schema": "autonomath.amendment.v1",
  "ts": "2026-04-25T05:52:04+00:00",
  "subscription_id": 42,
  "snapshot_id": 12345,
  "entity_id": "program:test:001",
  "version_seq": 2,
  "observed_at": "2026-04-25T00:00:00+00:00",
  "effective_from": null,
  "effective_until": "2026-12-31",
  "amount_max_yen": 1000000,
  "subsidy_rate_max": null,
  "source_url": "https://www.example.go.jp/...",
  "record_kind": "program",
  "law_id": "law_345AC0000000050",
  "law_refs": [],
  "industries": [],
  "tools": [],
  "severity": "critical"
}
```

- 配信 timeout: 30s (connect 10s)
- リトライ: 5xx / network error で **1 回**。4xx は再送しない
- Rate limit: 同一 webhook_url で 60 req/分 (超過時 cron 内 sleep)

## Email

`webhook_url` と `email` 両設定時、Webhook の成否に関わらず両方送る (人と機械は別 consumer)。Postmark template alias は `amendment-alert`。

## 関連

- [webhooks.md](./webhooks.md) — ¥3/req 課金の構造化イベント outbound webhook (alerts とは別系統)
- [dashboard_guide.md](./dashboard_guide.md) — UI からの操作
