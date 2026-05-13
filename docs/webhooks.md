# Customer Webhooks

Customer Webhooks は、制度追加、制度改正、行政処分、税制更新などの構造化イベントを、指定した HTTPS URL に POST する機能です。

成功した配信だけが **1 delivery = ¥3 税別**として課金されます。失敗した配信、再送、テスト配信は課金されません。

> jpcite は公開情報の集約 API です。Webhook payload は税務助言・法律相談・申請代行ではありません。

## 概要

| 項目 | 値 |
|---|---|
| 登録時の認証 | `X-API-Key: jc_...` または `Authorization: Bearer jc_...` |
| 配信先 | `https://` の URL のみ |
| 署名 | `X-Jpcite-Signature: hmac-sha256=<hex>` |
| User-Agent | `jpcite-webhook/1.0` |
| Content-Type | `application/json; charset=utf-8` |
| 課金 | HTTP 2xx の配信成功のみ |
| 失敗時 | 課金なし。一定回数だけ再送 |
| 自動停止 | 連続失敗が続いた場合は配信を停止 |

## Event types

| event_type | 内容 |
|---|---|
| `program.created` | 新しく確認された制度 |
| `program.amended` | 制度内容の重要な変更 |
| `enforcement.added` | 行政処分・返還命令などの公開事例 |
| `tax_ruleset.amended` | 税制ルールの変更 |
| `invoice_registrant.matched` | 適格請求書発行事業者の照合結果 |

## 登録

```bash
curl -X POST https://api.jpcite.com/v1/me/webhooks \
  -H "X-API-Key: jc_..." \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://hooks.example.com/jpcite",
    "event_types": ["program.created", "program.amended", "enforcement.added"]
  }'
```

### Response

```json
{
  "id": 7,
  "url": "https://hooks.example.com/jpcite",
  "event_types": ["program.created", "program.amended", "enforcement.added"],
  "status": "active",
  "failure_count": 0,
  "last_delivery_at": null,
  "created_at": "2026-05-01T00:00:00+09:00",
  "secret_hmac": "<webhook_signing_secret>",
  "secret_last4": "Cdef"
}
```

`secret_hmac` は登録時のレスポンスでだけ表示されます。受信側で署名検証に使うため、必ず保存してください。紛失した場合は Webhook を作り直してください。

## 一覧

```bash
curl https://api.jpcite.com/v1/me/webhooks \
  -H "X-API-Key: jc_..."
```

## 削除

```bash
curl -X DELETE https://api.jpcite.com/v1/me/webhooks/7 \
  -H "X-API-Key: jc_..."
```

## テスト配信

```bash
curl -X POST https://api.jpcite.com/v1/me/webhooks/7/test \
  -H "X-API-Key: jc_..."
```

テスト配信は無料です。受信 URL、署名検証、レスポンスコードの確認に使ってください。

## 配信ログ

```bash
curl 'https://api.jpcite.com/v1/me/webhooks/7/deliveries?limit=10' \
  -H "X-API-Key: jc_..."
```

直近の配信結果を返します。

## Payload

すべての payload は次の形です。

```json
{
  "event_type": "program.amended",
  "timestamp": "2026-05-01T00:00:00+09:00",
  "data": {
    "unified_id": "UNI-1111111111",
    "name": "ものづくり補助金",
    "diffs": [
      {
        "field": "application_period",
        "before": "2026-04-01〜2026-06-30",
        "after": "2026-04-01〜2026-09-30"
      }
    ],
    "source_url": "<公式公募要領URL>",
    "evidence_packet_endpoint": "/v1/evidence/packets/program/UNI-1111111111"
  }
}
```

## 署名検証

受信側では、raw request body と `secret_hmac` から HMAC-SHA256 を計算し、`X-Jpcite-Signature` と比較してください。

### Header

```http
X-Jpcite-Signature: hmac-sha256=<64 hex>
X-Jpcite-Event: <event_type>
User-Agent: jpcite-webhook/1.0
Content-Type: application/json; charset=utf-8
```

既存連携との互換性のため、配信には旧ヘッダ名も含まれる場合があります。新規実装では `X-Jpcite-*` を使用してください。

### Python

```python
import hashlib
import hmac
from fastapi import FastAPI, HTTPException, Request

WEBHOOK_SECRET = "<webhook_signing_secret>"
app = FastAPI()


@app.post("/jpcite-webhook")
async def receive(request: Request):
    body = await request.body()
    provided = request.headers.get("X-Jpcite-Signature", "")
    expected = "hmac-sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid signature")
    return {"ok": True}
```

## 配信先 URL の条件

- `https://` のみ登録できます。
- ローカルネットワーク、ループバック、リンクローカル IP は登録できません。
- 受信側は 30 秒以内に 2xx を返してください。
- 4xx は設定ミスとして扱い、再送対象外になることがあります。

## アラートとの違い

[Amendment Alerts](./alerts_guide.md) は、制度改正をメールまたは Webhook で通知する無料の補助機能です。Customer Webhooks は、構造化イベントを自社システムへ継続配信する有料機能です。
