# Customer Webhooks

> **要約 (summary):** 自分の API でホストする URL に、 制度・行政処分・税制改正・適格事業者 等の構造化イベントを 署名検証 付きで POST する outbound webhook 機能。`/v1/me/webhooks` で自己完結登録、 配信は `¥3/req` 課金 (Stripe usage records)。 5 連続失敗で自動 disable (runaway billing 防止)。
>
> 本サービスは公開情報の集約 API であり、 税務助言・法律相談ではありません (§52)。 配信される payload は政府一次資料と公開データに基づく機械集約結果であり、 個別事案の助言には使用しないでください。

## 目次

- [概要](#概要)
- [Event types カタログ](#event-types-カタログ)
- [Endpoint 一覧](#endpoint-一覧)
- [Payload schemas](#payload-schemas)
- [署名検証](#署名検証)
- [Retry policy](#retry-policy)
- [Auto-disable](#auto-disable)
- [Best practices](#best-practices)

## 概要

| 項目 | 値 |
|------|----|
| 認証 (登録時) | `X-API-Key: am_xxx` または `Authorization: Bearer am_xxx` |
| 認証 (受信側) | 署名検証 (SHA256) (`X-Zeimu-Signature` ヘッダ) |
| Transport | `https://` のみ (RFC1918 / loopback / link-local IP は 400) |
| User-Agent | `zeimu-kaikei-webhook/1.0` |
| Content-Type | `application/json; charset=utf-8` |
| 課金 | 1 successful delivery (HTTP 2xx) = `¥3/req` (税込 ¥3.30) |
| 失敗時 | 課金しない、 retry 3 回 (60s / 5m / 30m) |
| Auto-disable | 連続 5 失敗で `status='disabled'` |
| 最大 webhook 数 | 1 API key につき 10 件 (active) |

`alert_subscriptions` (法令改正アラート、 `/v1/me/alerts/*`) とは別系統です。 alert は **無料 / 制度時系列 snapshot fan-out のみ**、 customer_webhooks は **¥3/req 課金 / 構造化プロダクトイベント全般** を扱います。

## Event types カタログ

| event_type | 発火条件 | source table | 備考 |
|------------|---------|--------------|------|
| `program.created` | `programs.updated_at >= since` AND `excluded=0` AND `tier IN ('S','A','B','C')` | `programs` | 新規搭載・再有効化された制度 |
| `program.amended` | 制度改正履歴 の detected_at >= since | 制度改正履歴 (autonomath.db) | 補助金額・対象・適用期間等 schema-level 変更 |
| `enforcement.added` | `enforcement_cases.fetched_at >= since` | `enforcement_cases` | 新規行政処分 (補助金返還命令・指名停止等) |
| `tax_ruleset.amended` | `tax_rulesets.effective_from >= since OR effective_until >= since` | `tax_rulesets` | 税制改正・施行日確定 |
| `invoice_registrant.matched` | (matcher pipeline 未実装、 schema 上は予約) | `invoice_registrants` | 顧客 watchlist との照合一致 (将来) |

`since` の默认 lookback は 24h (`--window-minutes 1440`)。 cron は `scripts/cron/dispatch_webhooks.py` で 1 日 1 回回す前提。

## Endpoint 一覧

すべて `X-API-Key` (or `Authorization: Bearer`) 必須。匿名 (no API key) は **401**。

### POST `/v1/me/webhooks` — 登録

```bash
curl -X POST https://api.zeimu-kaikei.ai/v1/me/webhooks \
  -H "X-API-Key: am_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://hooks.example.com/zeimu-kaikei",
    "event_types": ["program.created", "program.amended", "enforcement.added"]
  }'
```

#### Body

| field | type | required | description |
|-------|------|----------|-------------|
| `url` | string | yes | HTTPS のみ。max 2048 文字。internal IP block。 |
| `event_types` | string[] | yes | 上記カタログから 1+ 個。 unknown は 422。 |

#### Response (201 Created)

```json
{
  "id": 7,
  "url": "https://hooks.example.com/zeimu-kaikei",
  "event_types": ["program.created", "program.amended", "enforcement.added"],
  "status": "active",
  "failure_count": 0,
  "last_delivery_at": null,
  "created_at": "2026-04-29T05:12:34+00:00",
  "secret_hmac": "whsec_AbCdEf0123456789...0123456789AbCdEf",
  "secret_last4": "Cdef"
}
```

> **重要:** `secret_hmac` フィールドは **このレスポンスでしか取得できません**。 紛失した場合は DELETE → 再登録で新しい secret を発行してください。 GET `/v1/me/webhooks` では `secret_last4` のみ返します。

### GET `/v1/me/webhooks` — 一覧

```bash
curl https://api.zeimu-kaikei.ai/v1/me/webhooks \
  -H "X-API-Key: am_xxx"
```

active + disabled 両方を newest-first で返します。 `secret_hmac` は常に `null` (`secret_last4` のみ閲覧可能)。

### DELETE `/v1/me/webhooks/{id}` — 削除

```bash
curl -X DELETE https://api.zeimu-kaikei.ai/v1/me/webhooks/7 \
  -H "X-API-Key: am_xxx"
```

soft-delete (`status='disabled'`、 `disabled_reason='deleted_by_customer'`)。 row は audit 用に残ります。 他人の id を指定しても **404** (id 列挙不可)。

### POST `/v1/me/webhooks/{id}/test` — テスト配信

```bash
curl -X POST https://api.zeimu-kaikei.ai/v1/me/webhooks/7/test \
  -H "X-API-Key: am_xxx"
```

合成 payload (`event_type=test.ping`) を即時 POST します。 **無料** (¥3/req に課金しない)、`failure_count` には影響しません。 5 req/min/webhook の rate limit があります。

#### Response

```json
{
  "ok": true,
  "status_code": 200,
  "error": null,
  "signature": "hmac-sha256=8a2f...",
  "sent_at": "2026-04-29T05:13:01+00:00"
}
```

### GET `/v1/me/webhooks/{id}/deliveries` — 直近配信ログ

```bash
curl 'https://api.zeimu-kaikei.ai/v1/me/webhooks/7/deliveries?limit=10' \
  -H "X-API-Key: am_xxx"
```

`webhook_deliveries` の最新 N 件 (default 10、 max 100) を返します。 dashboard の "Recent deliveries" ペインがこれを使います。

## Payload schemas

すべての payload は以下の構造を共有します。

```json
{
  "event_type": "<event_type>",
  "timestamp": "<ISO-8601 UTC>",
  "data": { ... event-specific ... }
}
```

### `program.created`

```json
{
  "event_type": "program.created",
  "timestamp": "2026-04-29T05:12:34+00:00",
  "data": {
    "unified_id": "P-12345",
    "name": "ものづくり補助金 (一般型)",
    "summary": null,
    "source_url": "https://www.chusho.meti.go.jp/...",
    "prefecture": "全国",
    "program_kind": "subsidy",
    "tier": "A"
  }
}
```

### `program.amended`

```json
{
  "event_type": "program.amended",
  "timestamp": "2026-04-29T05:12:34+00:00",
  "data": {
    "unified_id": "P-12345",
    "name": null,
    "diffs": [
      { "field": "amount_max_yen", "before": "10000000", "after": "15000000" },
      { "field": "program.application_period", "before": "2026-04-01〜2026-06-30", "after": "2026-04-01〜2026-09-30" }
    ],
    "source_url": "https://www.chusho.meti.go.jp/..."
  }
}
```

### `enforcement.added`

```json
{
  "event_type": "enforcement.added",
  "timestamp": "2026-04-29T05:12:34+00:00",
  "data": {
    "case_id": "ENF-2026-04-0123",
    "event_kind": "grant_refund",
    "recipient_name": "○○株式会社",
    "recipient_houjin_bangou": "1010001234567",
    "prefecture": "東京都",
    "ministry": "経済産業省",
    "amount_yen": 5000000,
    "reason_excerpt": "事業実態がないにもかかわらず...",
    "source_url": "https://www.meti.go.jp/...",
    "disclosed_date": "2026-04-25"
  }
}
```

### `tax_ruleset.amended`

```json
{
  "event_type": "tax_ruleset.amended",
  "timestamp": "2026-04-29T05:12:34+00:00",
  "data": {
    "unified_id": "TR-1234",
    "name": "中小企業投資促進税制 (令和8年度改正)",
    "tax_category": "corporate_tax",
    "ruleset_kind": "tax_credit",
    "effective_from": "2026-04-01",
    "effective_until": "2028-03-31",
    "related_law_ids": ["law_345AC0000000034"]
  }
}
```

### `invoice_registrant.matched`

(matcher pipeline 実装まで予約。 schema は forward-compatible。)

## 署名検証

### Header 形式

```
X-Zeimu-Signature: hmac-sha256=<64 hex>
X-Zeimu-Event: <event_type>
User-Agent: zeimu-kaikei-webhook/1.0
Content-Type: application/json; charset=utf-8
```

### 検証アルゴリズム

1. Raw request body bytes を取得 (パース前)。
2. Webhook 登録時に発行された `secret_hmac` を key として SHA256 署名を計算。
3. `hex(hmac)` を **constant-time 比較** (`hmac.compare_digest` / `crypto.timingSafeEqual` 等) で `X-Zeimu-Signature` の `hmac-sha256=` 以降と比較。
4. 一致しなければ即 401 で reject。 一致したら通常処理。

### Python 実装例

```python
import hmac, hashlib
from fastapi import FastAPI, Request, HTTPException

WEBHOOK_SECRET = "whsec_..."  # POST /v1/me/webhooks のレスポンスから取得

app = FastAPI()


@app.post("/zeimu-kaikei-webhook")
async def receive(request: Request):
    body = await request.body()
    sig_header = request.headers.get("X-Zeimu-Signature", "")
    expected = "hmac-sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig_header, expected):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = await request.json()
    event_type = payload["event_type"]
    # ... your handler ...
    return {"ok": True}
```

### Node.js 実装例

```javascript
import crypto from 'node:crypto';
import express from 'express';

const WEBHOOK_SECRET = 'whsec_...';
const app = express();

// raw body required for signature verification
app.use(express.raw({ type: 'application/json' }));

app.post('/zeimu-kaikei-webhook', (req, res) => {
  const body = req.body; // Buffer
  const sigHeader = req.get('X-Zeimu-Signature') || '';
  const expected =
    'hmac-sha256=' +
    crypto.createHmac('sha256', WEBHOOK_SECRET).update(body).digest('hex');
  const a = Buffer.from(sigHeader);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
    return res.status(401).send('invalid signature');
  }
  const payload = JSON.parse(body.toString('utf8'));
  // ... your handler ...
  res.json({ ok: true });
});

app.listen(3000);
```

### Go 実装例

```go
package main

import (
    "crypto/hmac"
    "crypto/sha256"
    "encoding/hex"
    "io"
    "net/http"
)

const webhookSecret = "whsec_..."

func handler(w http.ResponseWriter, r *http.Request) {
    body, _ := io.ReadAll(r.Body)
    sigHeader := r.Header.Get("X-Zeimu-Signature")
    mac := hmac.New(sha256.New, []byte(webhookSecret))
    mac.Write(body)
    expected := "hmac-sha256=" + hex.EncodeToString(mac.Sum(nil))
    if !hmac.Equal([]byte(sigHeader), []byte(expected)) {
        http.Error(w, "invalid signature", http.StatusUnauthorized)
        return
    }
    // ... your handler ...
    w.WriteHeader(http.StatusOK)
}

func main() {
    http.HandleFunc("/zeimu-kaikei-webhook", handler)
    http.ListenAndServe(":3000", nil)
}
```

## Retry policy

1 つの `(webhook, event)` ペアにつき:

| 試行 | 待機時間 |
|------|---------|
| 初回 | 0s (即時) |
| 再試行 1 | +60s |
| 再試行 2 | +5min |
| 再試行 3 | +30min |

合計 **最大 4 回**。 次の挙動を持ちます:

- HTTP 2xx → 1 回成功で終了。 1 unit 課金。 `failure_count` リセット (0)。
- HTTP 5xx / timeout / network error → 上記スケジュールで retry。
- HTTP 4xx (408 / 429 を除く) → **retry しない** (customer 側の永続エラーと判定)。
- 4 回試行後すべて失敗 → `webhook_deliveries` に最終 attempt 記録。 親 webhook の `failure_count` を +1。

`webhook_deliveries.UNIQUE(webhook_id, event_type, event_id)` により、 cron 再実行時に成功済みイベントを重複配信することはありません (再送安全)。

## Auto-disable

`failure_count >= 5` で webhook の `status='disabled'`、 `disabled_reason='5 consecutive failures: <last_error>'` がセットされます。 dispatcher はそれ以降のイベントを送りません (runaway billing 防止)。

email が `email_schedule` に登録されている場合、 `bg_task_queue` 経由で auto-disable 通知メールが送信されます (`webhook_disabled_email` kind)。

再有効化 = `DELETE /v1/me/webhooks/{id}` → 新しい URL/secret で **再登録**。 `failure_count` を直接リセットする API はありません (endpoint 健全性を確認した上で再登録するのが安全)。

## Best practices

1. **署名検証を必ず実装する。** 検証なしで payload を信用するとリプレイ攻撃 + spoofing が可能。
2. **handler を 再送安全 にする。** dispatcher 側で dedup していますが、 ネットワーク再送が発生した場合に同じ payload が複数回届く可能性があります。 `event_id` (data 内の unified_id 等) を key にローカル dedup する。
3. **handler は `200 OK` を 5 秒以内に返す。** 重い処理 (DB 書き込み・ML inference 等) は queue に投げて非同期化。 タイムアウト (10s) に引っかかると retry が走り、 重複処理リスクと配信遅延が増えます。
4. **Body は raw bytes でパース前に署名検証する。** JSON パース後に再シリアライズすると key の順序が変わって signature が一致しなくなります。
5. **secret は環境変数 / シークレットマネージャーで管理。** Git にコミットしない。
6. **テスト配信 (`POST /v1/me/webhooks/{id}/test`) で endpoint の死活確認をしてから本番イベント発火を待つ。**
7. **`status='disabled'` 復旧手順をオペレーションとして文書化する。** Slack 等への通知連携を組んでおくと、 5 回連続失敗で気付ける。
8. **失敗 payload の retry 上限 (3 回) を念頭に。** 受信側システムのダウンタイムが 30 分超だと最後の retry も失敗してイベントが永久ロストします。 重要イベントは Polling (`/v1/programs/recent` 等) と併用するのが安全です。

## 参考

- 実装ソース: [`src/jpintel_mcp/api/customer_webhooks.py`](https://github.com/shigetosidumeda-cyber/jpintel-mcp/blob/main/src/jpintel_mcp/api/customer_webhooks.py)
- Dispatcher cron: [`scripts/cron/dispatch_webhooks.py`](https://github.com/shigetosidumeda-cyber/jpintel-mcp/blob/main/scripts/cron/dispatch_webhooks.py)
- Schema: [`scripts/migrations/080_customer_webhooks.sql`](https://github.com/shigetosidumeda-cyber/jpintel-mcp/blob/main/scripts/migrations/080_customer_webhooks.sql)
- 関連 (FREE 系): [Amendment Alerts](alerts_guide.md)
- §52 Disclaimer: 本サービスは公開情報の集約 API であり、 税務助言・法律相談ではありません。 個別事案は税理士・弁護士・社労士にご相談ください。
