# Amendment Alerts

> **要約 (summary):** 制度時系列 snapshot 内で **確定日付フィールド (`effective_from` / `effective_until`) が NULL でない部分集合** を対象に、 schema-level の差分を Webhook + Email で配信する best-effort 通知。subscription は **無料** (¥3/req に追加課金しない)、認証 API key 必須、Self-serve。網羅性の保証はない (下記カバレッジ参照)。

## 概要 (Overview)

税務会計AI は制度時系列 snapshot (14,596 行) を保持しており、 Amendment alerts はこの snapshot に対する schema-level な差分を Webhook / Email で配信する。日々の制度改正を **網羅的に** 追跡しているわけではなく、 確定日付フィールドの埋まっている一部 record にのみ alert を発火する仕組み。

### カバレッジ (現状の正直な実数、 2026-04-26 時点)

| 列 | 値が入っている行 | 比率 | alert への寄与 |
|----|------|------|----------------|
| `effective_from` | 140 / 14,596 | 約 0.96% | `important` 判定の入力 |
| `effective_until` | 4 / 14,596 | 約 0.027% | `critical` 判定 (制度終了) の入力 |
| `eligibility_hash` | 14,596 / 14,596 | 100% (ただし v1/v2 で値が変化しない既知の制約があり、 ハッシュ差分による critical 検知は現状ほぼ発火しない) | (現状 dormant) |

**この制約により、 全 14,596 行を網羅した historical diff tracking は提供していない。** 顧客が「全制度改正を漏れなく検知したい」目的で本機能だけに依存するのは不適切で、 一次資料 (e-Gov 法令、 各省庁告示、 自治体公報) の自前監視を併用すべき。 本機能は polling 削減用の補助通知である。

- **Subscription は無料** — `project_autonomath_business_model` の通り ¥3/req は immutable。alert fan-out は retention 目的の運営コストとして扱う。
- **配信頻度** — 毎日 1 回 cron (`scripts/cron/amendment_alert.py`)。差分 (observed_at >= 24h 前) を見て該当 subscription にだけ送る。
- **Severity 判定** (deterministic、ML なし、 入力データに値があるときのみ発火):
  - `critical` — `effective_until` が新規設定された (制度終了) — 現状 4 行のみ対象
  - `important` — `amount_max_yen` / `subsidy_rate_max` / `target_set_json` / `effective_from` のいずれかが変わった — 現状 140 行台が主な対象
  - `info` — 上記以外 (出典再取得・cosmetic な修正)
  - 補足: `eligibility_hash` の変化を契機とする critical 判定はコード上に残っているが、 v1/v2 間でハッシュが固定の既知制約があるため現状 dormant。 値が変動する upstream 改修後に有効化される。

## エンドポイント

すべて `X-API-Key` ヘッダ必須。匿名 (no API key) アクセスは 401 が返る。

### POST `/v1/me/alerts/subscribe`

```bash
curl -X POST https://api.zeimu-kaikei.ai/v1/me/alerts/subscribe \
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
curl https://api.zeimu-kaikei.ai/v1/me/alerts/subscriptions \
  -H "X-API-Key: am_xxx"
```

返却は上記の `SubscriptionResponse` の配列。

### DELETE `/v1/me/alerts/subscriptions/{id}`

Soft-delete (`active = 0`)。row は audit 用に残る。

```bash
curl -X DELETE https://api.zeimu-kaikei.ai/v1/me/alerts/subscriptions/42 \
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

`scripts/migrate.py` 経由でも適用可能 (再送安全)。
