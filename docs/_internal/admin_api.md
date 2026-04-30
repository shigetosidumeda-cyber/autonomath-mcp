# Admin API (internal)

> **要約:** 運営者が funnel / cohort / error を自分で眺めるための内部 API。公開 `/v1/*` 契約の一部では**ない**。OpenAPI export には含まれない (`include_in_schema=False`)。launch 当日 (D+0) から観測できるようにしておく目的で先行実装。

対象ユーザは自分たち 1 名。terse でよい。

---

## 認証

| 項目 | 値 |
|---|---|
| Header | `X-API-Key: [set ADMIN_API_KEY env var]` |
| key source | `settings.admin_api_key` (env `ADMIN_API_KEY`) |
| key が未設定 | 全 endpoint が `503 "admin endpoints disabled"` を返す (安全側 default) |
| key 不一致 | `401` |

顧客 API key とは**分離**。`api_keys` テーブルを共有しない。Stripe / customer-id 連鎖に乗らない。

設定忘れ時は全 endpoint が 503 を返すので、本番 machine の環境変数に `ADMIN_API_KEY` を入れ忘れると自動的に封印される。

---

## `GET /v1/admin/funnel`

日次の funnel rollup を期間指定で取得。`funnel_daily` テーブル (`conversion_funnel.md` §2.3 のナイトリー cron が書く) を読むのみで、生 `usage_events` には触れない。

### Query params

| name | type | required | 説明 |
|---|---|---|---|
| `start` | `YYYY-MM-DD` | ✓ | 開始日 (含む) |
| `end` | `YYYY-MM-DD` | ✓ | 終了日 (含む)。`start <= end` |

### Response (抜粋)

```json
{
  "start": "2026-05-06",
  "end": "2026-05-08",
  "rows": [
    {
      "date": "2026-05-06",
      "visits": 500,
      "ctas": 60,
      "checkouts_started": 24,
      "checkouts_paid": 7,
      "keys_issued": 7,
      "first_api_calls": 5,
      "d7_retained": 0,
      "d30_retained": 0
    }
  ],
  "note": null
}
```

`funnel_daily` テーブルがまだ存在しない (migration 004 未適用) 場合は `rows=[]` + `note` に理由を返す (503 にはしない、観測系の availability > 正確さ)。

### curl

```bash
curl -sS "https://api.jpcite.com/v1/admin/funnel?start=2026-05-06&end=2026-05-20" \
  -H "X-API-Key: [set ADMIN_API_KEY env var]" | jq
```

---

## `GET /v1/admin/cohort`

特定 cohort (paying month 単位) の D+7/14/21/28 retention + churn breakdown を返す。

### Query params

| name | type | required | 説明 |
|---|---|---|---|
| `cohort_month` | `YYYY-MM` | ✓ | 支払開始月 |

### Response

```json
{
  "cohort_month": "2026-05",
  "active_d7": 42,
  "active_d14": 38,
  "active_d21": 33,
  "active_d28": 28,
  "churn_count": 4,
  "churn_reason_breakdown": {"price": 2, "no_use_case": 1, "bug": 1},
  "note": null
}
```

`cohort_retention` テーブル欠落 or 該当 cohort 行無し時は全カウント 0 + `note` 入り。

### curl

```bash
curl -sS "https://api.jpcite.com/v1/admin/cohort?cohort_month=2026-05" \
  -H "X-API-Key: [set ADMIN_API_KEY env var]" | jq
```

---

## `GET /v1/admin/top-errors`

直近 N 時間の `usage_events` から `status >= 400` の行を走査、endpoint × status で集計。上位 `limit` 件を返す。

### Query params

| name | type | default | 上限 | 説明 |
|---|---|---|---|---|
| `hours` | int | `24` | 720 (30 日) | 走査範囲 |
| `limit` | int | `20` | 200 | 返却件数 |

### Response

```json
{
  "hours": 24,
  "limit": 20,
  "errors": [
    {
      "endpoint": "programs.search",
      "status_code": 400,
      "error_class": "4xx",
      "count": 12,
      "sample_message": null,
      "first_seen": "2026-05-06T08:12:00+00:00",
      "last_seen": "2026-05-06T22:51:00+00:00"
    }
  ],
  "note": null
}
```

`sample_message` は現時点 null (生 `usage_events` にメッセージ列を持たせていないため)。専用 `errors` テーブルを後続追加する場合はそこから注入する。

### curl

```bash
curl -sS "https://api.jpcite.com/v1/admin/top-errors?hours=24&limit=20" \
  -H "X-API-Key: [set ADMIN_API_KEY env var]" | jq
```

---

## 運用メモ

- `include_in_schema=False` で `/openapi.json` と `docs/openapi/v1.json` から除外される。SDK generator にも現れない。
- この doc は `docs/api-reference.md` の末尾からリンクされるが、内容は api-reference には inline しない (「内部向け」という意図を強く保つため)。
- 将来 `funnel_daily` / `cohort_retention` migration が入ったら、このファイルの「欠落時の挙動」節は残すこと (rollup job 停止時の graceful degradation は本番でも起きうる)。
