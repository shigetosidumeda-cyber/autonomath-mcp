# Self-serve dashboard

顧客 self-serve ダッシュボード: <https://jpcite.com/dashboard.html>。 4 つの bearer-authenticated view を control plane の cookie session 上に提供。

| Endpoint | 用途 |
| --- | --- |
| `GET /v1/me/dashboard` | 30 日 usage summary (calls, ¥ 額, peak day, cap state) |
| `GET /v1/me/usage_by_tool` | tool 別 top 10 (call 数 / ¥ 額) |
| `GET /v1/me/billing_history` | Stripe invoice list (5 分 cache) |
| `GET /v1/me/tool_recommendation?intent=<query>` | intent → 候補 tool ランキング |

## 認証

すべて API key 必須:

```
X-API-Key: am_…
Authorization: Bearer am_…
```

匿名は `401 dashboard requires an authenticated API key`。`/v1/programs/search` 等の data 経路は引き続き匿名 50 req/月 で動く ([pricing.md](./pricing.md))。

## Dashboard summary

```bash
curl -s "https://jpcite.com/v1/me/dashboard?days=30" \
  -H "Authorization: Bearer $AM_KEY" | jq
```

```json
{
  "key_hash_prefix": "7fa2c9e1",
  "tier": "paid",
  "days": 30,
  "series": [{"date": "2026-03-26", "calls": 0}, ...],
  "today_calls": 24,
  "last_7_calls": 142,
  "last_30_calls": 612,
  "last_30_amount_yen": 1836,
  "peak_day": {"date": "2026-04-12", "calls": 52},
  "monthly_cap_yen": 10000,
  "month_to_date_calls": 612,
  "month_to_date_amount_yen": 1836,
  "cap_remaining_yen": 8164,
  "unit_price_yen": 3
}
```

- `series` は zero-calls 日も埋めて 30 日 chart を gap-fill 不要に
- `last_30_amount_yen = last_30_calls * 3` (税別)
- `cap_remaining_yen` は cap 未設定時 `null`
- `month_to_date_calls` は metered + success のみ (cap middleware の定義と同じ)

## Tool 別

```bash
curl -s "https://jpcite.com/v1/me/usage_by_tool?days=30&limit=10" \
  -H "Authorization: Bearer $AM_KEY"
```

`amount_yen` は metered + success サブセット (4xx/5xx は課金しない)。`avg_latency_ms` は今後 surface 予定 (`null` を返す)。

## 請求履歴

```bash
curl -s "https://jpcite.com/v1/me/billing_history" \
  -H "Authorization: Bearer $AM_KEY"
```

Stripe invoice 直近 24 件、5 分 in-process cache。Stripe 未設定環境では `{"invoices": [], "customer_id": "cus_…"}`。CSV / JSON download も UI 側にあり。

## Tool 推奨

```bash
curl -s "https://jpcite.com/v1/me/tool_recommendation?intent=設備投資の補助金&limit=5" \
  -H "Authorization: Bearer $AM_KEY"
```

```json
{
  "intent": "設備投資の補助金",
  "tools": [
    {
      "endpoint": "/v1/programs/search",
      "name": "programs.search",
      "why": "補助金 / 助成金 / 給付金 / 認定制度の網羅検索 (一致: 補助)",
      "confidence": 0.6
    }
  ],
  "fallback_used": false
}
```

純 keyword スコア、LLM 呼出なし、deterministic。keyword 一致がなければ `fallback_used: true` で catalog tail を confidence 0.2 で返す。

## Cap 管理

```bash
# ¥10,000 月次 cap 設定
curl -X POST "https://jpcite.com/v1/me/cap" \
  -H "Authorization: Bearer $AM_KEY" -H "Content-Type: application/json" \
  -d '{"monthly_cap_yen": 10000}'

# Cap 解除
curl -X POST "https://jpcite.com/v1/me/cap" \
  -H "Authorization: Bearer $AM_KEY" -H "Content-Type: application/json" \
  -d '{"monthly_cap_yen": null}'
```

Month-to-date metered spend が cap に達すると以降の data 経路は `503` (`cap_reached: true`) を返し、JST 月初リセットまで停止。

## 制度改正アラート

ダッシュボードは `/v1/me/alerts/*` のラッパー UI (`#dash2-alerts`) を持つ。仕様詳細は [alerts_guide.md](./alerts_guide.md)、ここは UI 側挙動のみ。

| Endpoint | UI 操作 |
| --- | --- |
| `GET /v1/me/alerts/subscriptions` | 初期化時に呼び subscription 一覧を描画 |
| `POST /v1/me/alerts/subscribe` | フォーム submit、結果 banner |
| `DELETE /v1/me/alerts/subscriptions/{id}` | 行削除 (window.confirm 経由で deactivate) |

### フォーム

- **filter_type:** `tool` / `law_id` / `program_id` / `industry_jsic` / `all` (free-text 禁止)
- **filter_value:** `filter_type='all'` 以外で必須。`law_345AC0000000050` のような 1 次キー
- **min_severity:** `critical` / `important` / `info` (default `important`)
- **webhook_url:** optional、HTTPS のみ。client 側 pre-validate:
  - `https://` で始まる、2048 文字以内
  - RFC1918 / loopback / link-local / unique-local の internal IP literal を拒否
  - 内部 DNS 名は client 側通過、サーバ cron が fire-time に再検証
- **email:** optional。`webhook_url` または `email` のどちらか必須

### 削除

`削除` は `window.confirm()` 後に `DELETE` を叩く。サーバは soft-delete (`active=0`)、再開時は新規登録。404 (既削除) は UI 側で「既に削除されています」と表示。

### Banner

`#dash2-alerts-banner` (`role="status"`、`aria-live="polite"`)。成功は 4 秒後自動消滅、失敗は次操作まで残る (純 vanilla JS、CSP 準拠)。
