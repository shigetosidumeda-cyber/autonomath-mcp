# Amendment Alerts

> **要約 (summary):** 法令改正 / 制度新設 / 行政処分 などを Webhook + Email で proactive 通知。subscription は **無料** (¥3/req に追加課金しない)、認証 API key 必須、Self-serve。

## 概要 (Overview)

AutonoMath は `am_amendment_snapshot` (autonomath.db, 14,596 rows) で日々の制度改正を追跡している。Amendment alerts はこの差分を Webhook / Email で配信し、顧客が `/v1/laws` や `/v1/programs` を毎日 polling せずに済むようにする。

- **Subscription は無料** — `project_autonomath_business_model` の通り ¥3/req は immutable。alert fan-out は retention 目的の運営コストとして扱う。
- **配信頻度** — 毎日 1 回 cron (`scripts/cron/amendment_alert.py`)。差分 (observed_at >= 24h 前) を見て該当 subscription にだけ送る。
- **Severity 判定** (deterministic、ML なし):
  - `critical` — `effective_until` が新規設定された (制度終了) / `eligibility_hash` が変わった
  - `important` — `amount_max_yen` / `subsidy_rate_max` / `target_set_json` のいずれかが変わった
  - `info` — 上記以外 (出典再取得・cosmetic な修正)

## エンドポイント

すべて `X-API-Key` ヘッダ必須。匿名 (no API key) アクセスは 401 が返る。

### POST `/v1/me/alerts/subscribe`

```bash
curl -X POST https://api.autonomath.ai/v1/me/alerts/subscribe \
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

#### Body

| field | type | required | description |
|-------|------|----------|-------------|
| `filter_type` | enum | yes | `tool` / `law_id` / `program_id` / `industry_jsic` / `all` |
| `filter_value` | string | conditional | `filter_type != 'all'` のときは必須 |
| `min_severity` | enum | no (default: `important`) | `critical` / `important` / `info` |
| `webhook_url` | string | conditional | HTTPS only、internal IP block。`webhook_url` か `email` の少なくとも一方が必須 |
| `email` | email | conditional | `webhook_url` または `email` のいずれかが必須 |

#### Webhook URL の制限

- `https://` のみ。`http://`、scheme なし、その他は 400。
- `127.0.0.1`、`10.*`、`172.16-31.*`、`192.168.*`、`::1`、`fc00::/7`、`169.254.*` は 400。
- Cron 配信時に **DNS rebind 再検査** (host を resolve して private IP に落ちると skip)。

#### レスポンス (201)

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

自分の active な subscription を返す (`active=0` は除外)。

```bash
curl https://api.autonomath.ai/v1/me/alerts/subscriptions \
  -H "X-API-Key: am_xxx"
```

返却は上記の `SubscriptionResponse` の配列。

### DELETE `/v1/me/alerts/subscriptions/{id}`

Soft-delete (`active = 0`)。row は audit 用に残る。

```bash
curl -X DELETE https://api.autonomath.ai/v1/me/alerts/subscriptions/42 \
  -H "X-API-Key: am_xxx"
```

`{"ok": true, "id": 42}` が返る。他人の id を指定しても **404** (id 列挙不可)。

## Webhook payload

POST body の例:

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

- 配信タイムアウト: **30s** (connect 10s)。
- リトライ: **5xx / network error で 1 回**。それ以外 (4xx) は再送しない。
- Rate limit: **同一 webhook_url で 60 req/分**。超えると cron 内で sleep して順次配信。

## Email

`webhook_url` と `email` が両方設定されていれば、Webhook の成否に関わらず両方送る (人と機械は別の consumer)。Postmark template alias は `amendment-alert`。

## Cron 運用

```bash
# Daily run (cron / fly.io schedule から呼ぶ)
.venv/bin/python scripts/cron/amendment_alert.py

# Dry-run (DB は読むが Webhook / Email は送らない)
.venv/bin/python scripts/cron/amendment_alert.py --dry-run

# 過去差分を再走 (since はオプション、default = 24h 前)
.venv/bin/python scripts/cron/amendment_alert.py --since 2026-04-20T00:00:00+00:00
```

Cron が出すサマリー (stdout、JSON 1 行):

```json
{
  "ran_at": "2026-04-25T05:52:04+00:00",
  "since": "2026-04-24T05:52:04+00:00",
  "amendments_scanned": 23,
  "subscriptions_active": 17,
  "subscriptions_fired": 4,
  "webhook_fires": 3,
  "email_fires": 4,
  "dry_run": false
}
```

## マイグレーション

`scripts/migrations/038_alert_subscriptions.sql` で `alert_subscriptions` table と 2 indexes を作る。

```bash
sqlite3 data/jpintel.db < scripts/migrations/038_alert_subscriptions.sql
```

`scripts/migrate.py` 経由でも適用可能 (idempotent)。
