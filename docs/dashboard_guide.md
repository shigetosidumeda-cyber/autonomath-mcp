# Self-serve dashboard guide

Customer self-serve dashboard at <https://zeimu-kaikei.ai/dashboard.html>. The page exposes four bearer-authenticated views on top of the existing cookie-session control plane:

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/me/dashboard` | 30-day usage summary (calls, ¥ amount, peak day, cap state) |
| `GET /v1/me/usage_by_tool` | Top 10 tools by call count + ¥ amount |
| `GET /v1/me/billing_history` | Stripe invoice list (5 minute in-process cache) |
| `GET /v1/me/tool_recommendation?intent=<query>` | intent → ranked tool candidates |

## Authentication

All four endpoints require an authenticated key via either:

```
X-API-Key: am_…
Authorization: Bearer am_…
```

Anonymous requests get `401 dashboard requires an authenticated API key`. Public calls to `/v1/programs/search` etc. continue to work anonymously under the 50 req/月 per-IP quota — the dashboard is the one place where anon fails closed.

## Dashboard summary

```bash
curl -s "https://zeimu-kaikei.ai/v1/me/dashboard?days=30" \
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

Notes:

- `series` is filled with zero-calls days so a 30-day chart renders without client-side gap-filling.
- `last_30_amount_yen = last_30_calls * unit_price_yen` (¥3, 税別).
- `cap_remaining_yen` is `null` when no cap is set (uncapped is the default).
- `month_to_date_calls` only counts metered + successful (status<400) rows — that is the same definition the cap middleware uses, so the dashboard cannot show a number larger than what the cap actually enforces.

## Tool usage breakdown

```bash
curl -s "https://zeimu-kaikei.ai/v1/me/usage_by_tool?days=30&limit=10" \
  -H "Authorization: Bearer $AM_KEY"
```

Returns the top N endpoints by call count over the requested window. `amount_yen` reflects the metered+success subset only (4xx/5xx do not bill, by design). `avg_latency_ms` is `null` today because `usage_events` does not yet persist latency.

## Billing history

```bash
curl -s "https://zeimu-kaikei.ai/v1/me/billing_history" \
  -H "Authorization: Bearer $AM_KEY"
```

Up to 24 most-recent Stripe invoices for the customer attached to the key. The result is cached in-process for 5 minutes (per customer\_id). When Stripe is unconfigured (e.g. dev environment), the response is `{"invoices": [], "customer_id": "cus_…"}` rather than 500.

The dashboard UI exposes CSV / JSON download buttons that snapshot the current response.

## Tool recommendation

```bash
curl -s "https://zeimu-kaikei.ai/v1/me/tool_recommendation?intent=設備投資の補助金&limit=5" \
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

Pure keyword scoring — no LLM call, deterministic for a given intent. When no keyword matches, `fallback_used` flips to `true` and the response carries the catalog tail (programs.search / laws.search / am.tax\_incentives.search) at confidence 0.2 so the caller can render a "browse all" UI instead of "best match".

This mirrors the existing `meta.alternative_intents` field that 税務会計AI 注記 attach when a search returns empty/sparse results, but returns concrete REST paths an SDK can call directly.

## Cap management

POST `/v1/me/cap` (実装は `src/jpintel_mcp/api/me.py`) を UI から叩く。numeric input + Save / Remove buttons:

```bash
# Set ¥10,000 monthly cap
curl -X POST "https://zeimu-kaikei.ai/v1/me/cap" \
  -H "Authorization: Bearer $AM_KEY" -H "Content-Type: application/json" \
  -d '{"monthly_cap_yen": 10000}'

# Remove the cap (uncap)
curl -X POST "https://zeimu-kaikei.ai/v1/me/cap" \
  -H "Authorization: Bearer $AM_KEY" -H "Content-Type: application/json" \
  -d '{"monthly_cap_yen": null}'
```

Once month-to-date metered spend reaches the cap, all data-plane requests return `503` with `cap_reached: true` until the next JST 月初 reset.

## 制度改正アラート

ダッシュボードは `/v1/me/alerts/*` をラップする UI セクション (`#dash2-alerts`) を提供する。詳細な API 仕様は [alerts_guide.md](alerts_guide.md) を参照、ここでは UI 側の挙動のみ記す。

| Endpoint | UI 操作 |
| --- | --- |
| `GET /v1/me/alerts/subscriptions` | ページ初期化時に呼ばれ、active な subscription を一覧表に描画 |
| `POST /v1/me/alerts/subscribe` | フォーム submit、バナーで成功/失敗 |
| `DELETE /v1/me/alerts/subscriptions/{id}` | 行ごとの「削除」ボタン (`window.confirm()` 経由で deactivate) |

### フォーム項目と検証

- **filter_type** — `tool` / `law_id` / `program_id` / `industry_jsic` / `all` から `<select>` で選択 (free-text 禁止、enum 統一)。
- **filter_value** — `filter_type='all'` 以外では必須。`law_345AC0000000050` のような 1 次キーをそのまま貼る想定。
- **min_severity** — `critical` / `important` / `info`。`important` がデフォルト (cron が同等以上を送る)。
- **webhook_url** — optional、HTTPS のみ。クライアント側で次を pre-validate してから POST する:
  - `https://` で始まるか
  - 2048 文字以内
  - RFC1918 / loopback / link-local / unique-local 等の internal IP literal を拒否 (`10.*`, `172.16-31.*`, `192.168.*`, `127.*`, `0.*`, `169.254.*`, `::1`, `fc00::/7`, `fd*:`, `fe80:`, `localhost`)
  - 内部 DNS 名 (例 `internal.corp`) は client では通り、サーバ cron が fire-time に再検証
- **email** — optional。`webhook_url` か `email` のどちらか 1 つ以上が必須 (両方空は 400)。

### 削除挙動

`削除` ボタンは `window.confirm()` で確認後 `DELETE /v1/me/alerts/subscriptions/{id}` を叩く。サーバは soft-delete (`active=0`) なので、再開したい場合は新規登録 (`POST /subscribe`) が必要。404 (既に削除済み) は UI 側で「既に削除されています」と表示し、テーブルを再フェッチする。

### バナー (toast)

`#dash2-alerts-banner` (`role="status"`, `aria-live="polite"`) に成功/失敗を表示。成功の場合 4 秒後に自動消滅、失敗は手動で次の操作までで残る (CSP 準拠の純 vanilla JS、setTimeout のみ)。

## Audience pitch

| Audience | Surface |
| --- | --- |
| Dev / Agent | API directly (curl, MCP, Python SDK) — dashboard is optional |
| SMB / 事業者 | LINE 受付窓口 → guided dialog (see [line.html](https://zeimu-kaikei.ai/line.html)) |
| 税理士 / 会計士 | Dashboard `tool_recommendation` for intent triage |
| 開発代理店 | Dashboard `usage_by_tool` for client billing breakdown |
| Compliance | Dashboard `billing_history` CSV export for 経理 |
| 法務 / 経営企画 | Dashboard `alerts` で制度改正を Webhook + Email 受信 (無料、追加課金なし) |
