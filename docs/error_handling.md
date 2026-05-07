<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "headline": "jpcite Error Handling (20 closed-enum error codes)",
  "description": "jpcite API/MCP の 20 種類 closed-enum error code 一覧と envelope shape、リトライ可否、各 code の発生条件と対処方法。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-04-26",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "jpcite",
    "url": "https://jpcite.com/"
  },
  "publisher": {
    "@type": "Organization",
    "name": "jpcite",
    "logo": {
      "@type": "ImageObject",
      "url": "https://jpcite.com/og/default.png"
    }
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://jpcite.com/docs/error_handling/"
  }
}
</script>

# Error handling

REST API + MCP は **20 種類の closed-enum error code** を返す。すべての error response は同じ envelope、`error.code` は機械可読な列挙値。

## Error envelope

```json
{
  "error": {
    "code": "<closed-enum>",
    "user_message": "顧客向け 日本語 message",
    "user_message_en": "End-user English message",
    "request_id": "01KQ3XQ77RR7J8XWZ8C0YR2JN2",
    "severity": "hard | soft",
    "documentation": "https://jpcite.com/docs/error_handling#<code>",
    "path": "/v1/programs/search",
    "method": "GET"
  }
}
```

`severity`:
- `hard` — 入力 / auth / quota / db / route 系。 retry しても直らない。
- `soft` — 一時的 (db lock 等)。 retry 可。

---

## 20 error codes

### Input validation (4xx)

#### `missing_required_arg`
- HTTP: 422
- 必須 query/body param が欠落。 `error.field_errors[]` に欠落 path。
- 復旧: 必須 param を付与して再送。

#### `invalid_enum`
- HTTP: 422
- closed-enum param に未定義の value。 `expected: [...]` に許可値、 `unknown: [...]` に違反値。
- 復旧: `expected` から選び直す。

#### `invalid_date_format`
- HTTP: 422
- ISO 8601 (YYYY-MM-DD) を期待する param に違反 format。
- 復旧: `2026-04-26` 形式で再送。

#### `out_of_range`
- HTTP: 422
- 数値 / 日付 param が ge/le 範囲外。 `field`, `min`, `max` を surface。
- 復旧: 範囲内で再送。

#### `unknown_query_parameter`
- HTTP: 422
- endpoint 未定義の query param が含まれる。 `expected: [...]` 許可、 `unknown: [...]` 違反。
- 復旧: `expected` 内 param のみで再送。問題が続く場合は `request_id` を添えて問い合わせる。

### Data lookup (4xx)

#### `no_matching_records`
- HTTP: 200 (envelope の `error` field 経由)、 envelope `status: empty`
- query は valid だが該当 record 0 件。 詐欺 fence: 「制度が無い」 と顧客が誤解しないよう `suggested_actions` で broaden_query / try_alias を提示。
- 復旧: 検索条件 broaden、 alias 試行。

#### `ambiguous_query`
- HTTP: 422
- query string が 2 つ以上の record に等しく match (確定不能)。
- 復旧: 都道府県 / 業種 / 法人番号 等 disambiguator を追加。

#### `seed_not_found`
- HTTP: 404
- `related_programs(seed_id)` 等で指定 seed が graph に不在。
- 復旧: `seed_id` の表記揺れ確認、 `search_programs` で正規化。

### Auth + quota (4xx)

#### `auth_required`
- HTTP: 401
- 認証不要の endpoint で認証 header が必要なルートに当たった (e.g. `/v1/me`)。
- 復旧: `Authorization: Bearer <api_key>` を付与。

#### `auth_invalid`
- HTTP: 401
- API key が無効 (削除済 / rotate 済 / 未存在)。
- 復旧: `me/rotate-key` で再発行。

#### `rate_limit_exceeded`
- HTTP: 429
- anonymous 3 req/日 per IP cap、 もしくは authenticated per-key cap 到達。
- response header: `X-Anon-Quota-Remaining`, `X-Anon-Quota-Reset` (JST daily reset)、 `X-Anon-Upgrade-Url`。
- 復旧: anonymous → upgrade URL で sign up、 authenticated → `me/cap` で月次 cap 上げ。

#### `cap_reached`
- HTTP: 402
- monthly metered cap (customer 設定の上限) 到達。 課金保護のため 自動 stop。
- 復旧: `me/cap` で raise、 もしくは月次 reset 待ち。

### Routing (4xx)

#### `route_not_found`
- HTTP: 404
- endpoint path 未定義。 typo / 旧 SDK の v1.0 path と新 v0.3 path の不一致。
- 復旧: `https://api.jpcite.com/v1/openapi.json` で path 一覧確認。

#### `method_not_allowed`
- HTTP: 405
- endpoint は存在するが HTTP method 不一致 (e.g. POST 用 endpoint に GET)。
- 復旧: `Allow:` response header で許可 method 確認。

### Database / infrastructure (5xx)

#### `db_locked`
- HTTP: 503
- soft severity。一時的にデータ更新や読み取りが混み合っている状態。
- response header: `Retry-After`。
- 復旧: 5-30 秒後 retry。

#### `db_unavailable`
- HTTP: 503
- hard severity。データストアまたは関連サービスが利用できない状態。
- response header: `Retry-After: 300`。
- 復旧: 数分後に再試行。継続する場合は `request_id` を添えて問い合わせ。

#### `subsystem_unavailable`
- HTTP: 503
- hard severity。特定機能の前提サービスが利用できない状態。
- 復旧: 少し待って再試行。継続する場合は `request_id` を添えて問い合わせ。

#### `service_unavailable`
- HTTP: 503
- soft severity。 一時的 outage (Stripe Tax API 5xx / Postmark down 等)。
- 復旧: 数分後 retry。

### Bug / abnormal (5xx)

#### `internal`
- HTTP: 500
- 想定外のエラー。問い合わせ時は `request_id` を共有してください。

#### `internal_error`
- HTTP: 500
- `internal` と同等の互換コード。問い合わせ時は `request_id` を共有してください。

---

## Error response 取扱い指針 (LLM client / SDK)

1. **HTTP status を見る前に `error.code` を見る** — envelope は HTTP 200 でも `status: error` のことがある。
2. **`severity: hard` は再試行しない** — 入力 / auth 修正が必要。
3. **`severity: soft` は exponential backoff retry** (1s / 2s / 4s / 8s) で 最大 3 回。
4. **`request_id` を必ずログ** — 問い合わせ時の確認に使います。
5. **`documentation` URL は機械可読** — LLM client は `\#<code>` anchor で該当 section を fetch して self-recovery 可能。

---

## 例: anonymous quota exceeded full envelope

```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "user_message": "匿名利用枠 3 req/日 を超過しました。 API key を発行してください。",
    "user_message_en": "Anonymous daily limit (3 req) reached. Get an API key to continue.",
    "request_id": "01KQ3XQ77RR7J8XWZ8C0YR2JN2",
    "severity": "hard",
    "documentation": "https://jpcite.com/docs/error_handling#rate_limit_exceeded",
    "path": "/v1/programs/search",
    "method": "GET",
    "upgrade_url": "https://jpcite.com/upgrade.html?from=429",
    "cta_text_ja": "API key を発行して制限を解除",
    "cta_text_en": "Get an API key to remove the limit"
  }
}
```

response headers:
```
X-Anon-Quota-Remaining: 0
X-Anon-Quota-Reset: <next JST 00:00>
X-Anon-Upgrade-Url: https://jpcite.com/upgrade.html?from=429
Retry-After: <seconds-until-daily-reset>
```

---

## 関連

- API reference: [api-reference.md](api-reference.md)
- Pricing + anonymous free use: [pricing.md](pricing.md)
- SLA: [sla.md](sla.md)
- Privacy + APPI § 31/§ 33: [compliance/privacy_policy.md](compliance/privacy_policy.md)
- 不在の場合: 特商法ページの連絡先へお問い合わせください。
