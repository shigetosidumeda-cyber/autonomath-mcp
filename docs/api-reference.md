<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "APIReference",
  "headline": "税務会計AI REST API Reference (112 endpoints)",
  "description": "税務会計AI REST API の全 112 endpoint 仕様。programs / exclusions / meta / billing / dashboard / laws / loans / court-decisions / bids / 行政処分 / 採択事例 / invoice 適格事業者 / tax_rulesets / V1+メタデータ+静的データセット 拡張を含む。",
  "datePublished": "2026-04-01",
  "dateModified": "2026-04-26",
  "inLanguage": "ja",
  "author": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "url": "https://zeimu-kaikei.ai/about.html"
  },
  "publisher": {
    "@type": "Organization",
    "name": "Bookyou株式会社",
    "logo": {
      "@type": "ImageObject",
      "url": "https://zeimu-kaikei.ai/og/default.png"
    }
  },
  "mainEntityOfPage": {
    "@type": "WebPage",
    "@id": "https://zeimu-kaikei.ai/docs/api-reference/"
  }
}
</script>

# API Reference

> **要約 (summary):** REST API の全 112 endpoint 仕様。programs / exclusions / meta / billing / dashboard / 各種データセット (laws / loans / court-decisions / bids / 行政処分 / 採択事例 / invoice 適格事業者 / tax_rulesets) / 税務会計AI V1+メタデータ+静的データセット 拡張 / 内部ユーティリティ (alerts / advisors / widget / privacy) を含む。各 endpoint について params, response, 認証要否, rate limit, curl 例を記載。最上部の [目次](#目次-endpoint-catalogue) で全体一覧。

## ベース URL

```
https://api.zeimu-kaikei.ai
```

## 目次 (Endpoint catalogue)

全 112 endpoint。OpenAPI spec (`docs/openapi/v1.json`) と完全一致。★ = 本ページに詳細あり、それ以外は OpenAPI から自動展開した最小ドキュメント (本ページ後半に展開済み)。

- **Programs** (4)
  - `POST /v1/programs/batch` ★
  - `POST /v1/programs/prescreen`
  - `GET /v1/programs/search` ★
  - `GET /v1/programs/{unified_id}` ★
- **Exclusions** (2)
  - `POST /v1/exclusions/check` ★
  - `GET /v1/exclusions/rules` ★
- **Meta** (5)
  - `GET /healthz` ★
  - `GET /readyz`
  - `GET /v1/meta` ★
  - `GET /v1/meta/freshness`
  - `GET /v1/ping` ★
- **Billing** (5)
  - `POST /v1/billing/checkout` ★
  - `POST /v1/billing/keys/from-checkout` ★
  - `POST /v1/billing/portal` ★
  - `POST /v1/billing/refund_request`
  - `POST /v1/billing/webhook` ★
- **Feedback** (1)
  - `POST /v1/feedback` ★
- **Account & API Keys (`/v1/me`)** (12)
  - `GET /v1/me`
  - `POST /v1/me/billing-portal`
  - `GET /v1/me/billing_history`
  - `POST /v1/me/cap`
  - `GET /v1/me/dashboard`
  - `POST /v1/me/rotate-key`
  - `GET /v1/me/tool_recommendation`
  - `GET /v1/me/usage`
  - `GET /v1/me/usage_by_tool`
  - `POST /v1/session`
  - `POST /v1/session/logout`
  - `GET /v1/usage`
- **Alerts (`/v1/me/alerts`)** (3)
  - `POST /v1/me/alerts/subscribe`
  - `GET /v1/me/alerts/subscriptions`
  - `DELETE /v1/me/alerts/subscriptions/{sub_id}`
- **Session & Device** (3)
  - `POST /v1/device/authorize`
  - `POST /v1/device/complete`
  - `POST /v1/device/token`
- **Subscribers (Email)** (5)
  - `GET /v1/email/unsubscribe`
  - `POST /v1/email/unsubscribe`
  - `POST /v1/email/webhook`
  - `POST /v1/subscribers`
  - `GET /v1/subscribers/unsubscribe`
- **Compliance Newsletter** (5)
  - `POST /v1/compliance/stripe-checkout`
  - `POST /v1/compliance/stripe-webhook`
  - `POST /v1/compliance/subscribe`
  - `POST /v1/compliance/unsubscribe/{unsubscribe_token}`
  - `GET /v1/compliance/verify/{verification_token}`
- **Public Stats (Transparency)** (5)
  - `GET /v1/stats/confidence`
  - `GET /v1/stats/coverage`
  - `GET /v1/stats/data_quality`
  - `GET /v1/stats/freshness`
  - `GET /v1/stats/usage`
- **Testimonials** (3)
  - `POST /v1/me/testimonials`
  - `DELETE /v1/me/testimonials/{testimonial_id}`
  - `GET /v1/testimonials`
- **Advisors** (6)
  - `GET /v1/advisors/match`
  - `POST /v1/advisors/report-conversion`
  - `POST /v1/advisors/signup`
  - `POST /v1/advisors/track`
  - `POST /v1/advisors/verify-houjin/{advisor_id}`
  - `GET /v1/advisors/{advisor_id}/dashboard-data`
- **Widget** (5)
  - `GET /v1/widget/enum_values`
  - `GET /v1/widget/search`
  - `POST /v1/widget/signup`
  - `POST /v1/widget/stripe-webhook`
  - `GET /v1/widget/{key_id}/usage`
- **APPI Privacy Requests** (2)
  - `POST /v1/privacy/deletion_request`
  - `POST /v1/privacy/disclosure_request`
- **Calendar** (1)
  - `GET /v1/calendar/deadlines`
- **Case Studies** (2)
  - `GET /v1/case-studies/search`
  - `GET /v1/case-studies/{case_id}`
- **Loan Programs** (2)
  - `GET /v1/loan-programs/search`
  - `GET /v1/loan-programs/{loan_id}`
- **Enforcement Cases** (2)
  - `GET /v1/enforcement-cases/search`
  - `GET /v1/enforcement-cases/{case_id}`
- **Invoice Registrants** (2)
  - `GET /v1/invoice_registrants/search`
  - `GET /v1/invoice_registrants/{invoice_registration_number}`
- **Laws** (3)
  - `GET /v1/laws/search`
  - `GET /v1/laws/{unified_id}`
  - `GET /v1/laws/{unified_id}/related-programs`
- **Court Decisions** (3)
  - `POST /v1/court-decisions/by-statute`
  - `GET /v1/court-decisions/search`
  - `GET /v1/court-decisions/{unified_id}`
- **Tax Rulesets** (3)
  - `POST /v1/tax_rulesets/evaluate`
  - `GET /v1/tax_rulesets/search`
  - `GET /v1/tax_rulesets/{unified_id}`
- **Bids** (2)
  - `GET /v1/bids/search`
  - `GET /v1/bids/{unified_id}`
- **AutonoMath: Programs (Active / Related / Stats / GX)** (6)
  - `GET /v1/am/acceptance_stats`
  - `GET /v1/am/active_at`
  - `GET /v1/am/gx_programs`
  - `GET /v1/am/open_programs`
  - `GET /v1/am/programs/active_v2`
  - `GET /v1/am/related/{program_id}`
- **AutonoMath: Intent / Reason / Enums** (3)
  - `GET /v1/am/enums/{enum_name}`
  - `GET /v1/am/intent`
  - `GET /v1/am/reason`
- **AutonoMath: Tax Incentives & Certifications** (3)
  - `GET /v1/am/certifications`
  - `GET /v1/am/tax_incentives`
  - `GET /v1/am/tax_rule`
- **AutonoMath: Loans & Mutual Insurance** (2)
  - `GET /v1/am/loans`
  - `GET /v1/am/mutual_plans`
- **AutonoMath: Laws & Enforcement** (3)
  - `GET /v1/am/by_law`
  - `GET /v1/am/enforcement`
  - `GET /v1/am/law_article`
- **AutonoMath: Annotations / Validation / Provenance** (4)
  - `GET /v1/am/annotations/{entity_id}`
  - `GET /v1/am/provenance/fact/{fact_id}`
  - `GET /v1/am/provenance/{entity_id}`
  - `POST /v1/am/validate`
- **AutonoMath: Static Resources & Example Profiles** (4)
  - `GET /v1/am/example_profiles`
  - `GET /v1/am/example_profiles/{profile_id}`
  - `GET /v1/am/static`
  - `GET /v1/am/static/{resource_id}`
- **AutonoMath: Health** (1)
  - `GET /v1/am/health/deep`


## バージョニングポリシー (Versioning policy)

エンドポイントは 2 種類に分かれる。契約の強さが異なるので、統合時に意識する。

**`/v1/*` — 安定契約 (stable contract):**
- `/v1/programs/*`, `/v1/exclusions`, `/v1/billing/*` など、`/v1/` prefix を持つ全エンドポイント
- response schema の破壊的変更はしない
- マイナー改訂は **追加のみ** (additive): 新しい任意フィールド、新しい optional query parameter、新しいエンドポイントの追加
- 破壊的変更が必要になった場合は `/v2/*` を新設し、`/v1/*` は最低 6 ヶ月並走させてから deprecate
- deprecation は response の `Sunset` / `Deprecation` header と docs 更新で 90 日以上前に告知

**`/healthz`, `/meta`, `/v1` prefix を持たない utility 系 — ライフサイクル扱い (lifecycle, unversioned):**
- `/healthz` は liveness probe のみで、schema は空 object に変わる可能性あり
- `/meta` は aggregate stats (total_programs, last_updated 等) を返すが、field 追加・削除・意味変更が発生しうる
- `/v1/billing/webhook` は Stripe 側の event schema に追従する (Stripe 仕様に引きずられる)
- これらの shape 変更は **30 日前に docs/api-reference.md と changelog で告知** するが、`/v2` 昇格は行わない

統合する client 側の注意: `/v1/*` 以外のレスポンスを business logic の入力に使わない。監視・運用系 (dashboard, health check) に限定する。

## OpenAPI spec

機械可読な契約は下記で配布する:

- **`GET /v1/openapi.json`** — live server が吐く spec (正本)
- **`GET /openapi.json`** — `/v1/openapi.json` へ **`308 Permanent Redirect`**。SDK 生成 client の旧 path からの移行期間のみの互換 alias
- **`docs/openapi/v1.json`** — repo に committed された snapshot (CI で `scripts/export_openapi.py` が regenerate)

admin 系 (`/v1/admin/*`) は `include_in_schema=False` で除外。preview 系 (`/v1/legal/*`, `/v1/accounting/*`, `/v1/calendar/*`) は default export には入らず、`scripts/export_openapi.py --include-preview` で roadmap 込みの spec を別途生成できる。

## 認証 (Authentication)

すべての認証付きエンドポイントは下記いずれかのヘッダーで API key を渡す:

```
X-API-Key: am_xxxxxxxxxxxxxxxx
Authorization: Bearer am_xxxxxxxxxxxxxxxx
```

**API key を送らない場合は匿名扱い** (50 req/月 per IP, 一部エンドポイントは利用可)。key が無効 / 取り消し済みの場合は `401 Unauthorized` を返す。

### 匿名呼び出しの IP レート制限 (Anonymous per-IP limit)

認証ヘッダー (`X-API-Key` / `Authorization: Bearer`) を付けない呼び出しは、IP アドレス単位で **1 ヶ月 50 req / IPv4 (/32) / IPv6 (/64)** に制限される。これは discoverability 系エンドポイント (`/meta`, `/v1/ping`, `/v1/programs/*`, `/v1/exclusions/*`, `/v1/feedback`) にのみ適用され、`/healthz`, `/v1/billing/webhook`, `/v1/subscribers/unsubscribe`, dashboard 系 (`/v1/me/*`, `/v1/session`) はカウントしない。

認証済み呼び出し (有効な API key 付き) はこの IP 制限を完全にバイパスし、metered 課金 (¥3/req 税別) だけが適用される。

上限超過時:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 604800
Content-Type: application/json

{"detail": "anon rate limit exceeded", "limit": 50, "resets_at": "2026-05-01T00:00:00+09:00"}
```

リセットは **JST 月初 00:00** (sliding window ではなく暦月)。`Retry-After` は翌月 1 日 00:00 (JST) までの秒数。IP は raw のまま保存されず、`HMAC-SHA256(ip, api_key_salt)` で hash 化される。

## Rate limit

| 区分 | 上限 | 計測 |
|------|-------------|------|
| 匿名 (anonymous) | 50 req/月 per IP | JST 月初 00:00 リセット、IPv4 /32, IPv6 /64 |
| 認証済み (Paid) | metered (Stripe 従量) | 上限なし、¥3/req 税別 (税込 ¥3.30) で請求 |

**注:** 価格と計測方法の最新値は [pricing.md](./pricing.md) を参照。

匿名上限超過時は `429 Too Many Requests`, body に `{"detail": "anon rate limit exceeded", "limit": 50}`。レスポンスに `Retry-After: <seconds to JST 月初>` header を含む。Paid は cap なし (スパイクでも 429 は返らない)。

---

## Programs

### `GET /v1/programs/search`

自由記述 + 構造化フィルタで制度を検索。

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `q` | string | no | 自由記述検索。3 文字以上で FTS5 trigram、2 文字以下は substring 一致 |
| `tier` | string (repeat) | no | `S` / `A` / `B` / `C` / `X`。複数指定で OR |
| `prefecture` | string | no | 都道府県名 (完全一致, 例: `青森県`) |
| `authority_level` | string | no | 正本 (英語): `national` / `prefecture` / `municipality` / `financial`。日本語別名 (`国` / `都道府県` / `市区町村` / `公庫`) も API 側で正規化して受け付ける |
| `funding_purpose` | string (repeat) | no | 資金用途 (例: `設備投資`) |
| `target_type` | string (repeat) | no | 対象者種別 (例: `認定新規就農者`) |
| `amount_min` | number | no | 助成上限の下限 (万円) |
| `amount_max` | number | no | 助成上限の上限 (万円) |
| `include_excluded` | bool | no | `true` で公開保留中の制度も含める (default `false`) |
| `limit` | int | no | 1〜100 (default 20) |
| `offset` | int | no | ページング (default 0) |
| `fields` | enum | no | `minimal` / `default` / `full`。レスポンスサイズ切替 (default `default`) |

**`fields` 選択肢:**

| 値 | `results[]` の中身 | 目安サイズ (1 row) | 用途 |
|----|-------------------|--------------------|------|
| `minimal` | `unified_id` / `primary_name` / `tier` / `prefecture` / `authority_name` / `amount_max_man_yen` / `official_url` の 7 キーのみ | ~150-300 B | リスト表示、クイックフィルタ、MCP tool の中間結果 |
| `default` (省略時) | `Program` 全フィールド (今までと完全互換) | ~500-800 B | 通常の統合 |
| `full` | `Program` + `enriched` (A-J 全次元) + `source_mentions` + lineage (`source_url` / `source_fetched_at` / `source_checksum`)。`enriched` / `source_mentions` は null でもキーが必ず存在 | ~3-50 KB (enriched 次第) | 単一制度の深い読み込み、エージェントのリサーチ |

`minimal` / `full` は追加扱い。`default` のスキーマは破壊的変更せずに維持する。

**Response (`SearchResponse`):**

```json
{
  "total": 153,
  "limit": 20,
  "offset": 0,
  "results": [
    {
      "unified_id": "string",
      "primary_name": "string",
      "aliases": ["string"],
      "authority_level": "national",
      "authority_name": "経済産業省",
      "prefecture": null,
      "municipality": null,
      "program_kind": "補助金",
      "official_url": "https://...",
      "amount_max_man_yen": 450,
      "amount_min_man_yen": 30,
      "subsidy_rate": 0.5,
      "trust_level": "high",
      "tier": "A",
      "coverage_score": 0.82,
      "gap_to_tier_s": ["J_statistics"],
      "a_to_j_coverage": {"A_basics": true, "B_target": true},
      "excluded": false,
      "exclusion_reason": null,
      "crop_categories": [],
      "equipment_category": null,
      "target_types": ["中小企業"],
      "funding_purpose": ["設備投資"],
      "amount_band": "100-500",
      "application_window": {"start": "2026-04-01", "end": "2026-06-30"}
    }
  ]
}
```

**Response example at `fields=minimal`:**

```json
{
  "total": 153,
  "limit": 20,
  "offset": 0,
  "results": [
    {
      "unified_id": "UNI-keiei-kaishi-shikin",
      "primary_name": "経営開始資金",
      "tier": "S",
      "prefecture": null,
      "authority_name": "農林水産省",
      "amount_max_man_yen": 1500,
      "official_url": "https://www.maff.go.jp/j/new_farmer/..."
    }
  ]
}
```

**Response example at `fields=full`:** `default` と同じ `results[i]` に加え、各 row に `enriched` (A-J 次元) / `source_mentions` (list of `{url, fetched_at}`) / `source_url` / `source_fetched_at` / `source_checksum` が必ず入る (値が null でもキーは存在)。

**Example:**

```bash
# default shape
curl -H "X-API-Key: am_..." \
  "https://api.zeimu-kaikei.ai/v1/programs/search?q=IT導入&tier=S&tier=A&limit=5"

# minimal — list rendering / quick filter
curl -H "X-API-Key: am_..." \
  "https://api.zeimu-kaikei.ai/v1/programs/search?q=IT導入&limit=20&fields=minimal"
```

**ソート:** FTS を使った場合は `rank` 順、それ以外は tier (S→A→B→C→X) → primary_name。

---

### `GET /v1/programs/{unified_id}`

単一制度の詳細取得。`enriched` (A-J 次元の詳細) と `source_mentions` を含む。

**認証:** 任意

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `unified_id` | string | yes | 制度 ID |

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `fields` | enum | no | `minimal` / `default` / `full`。レスポンスサイズ切替 (default `default`) |

**`fields` 選択肢 (`/v1/programs/{unified_id}`):**

| 値 | 中身 | 備考 |
|----|------|------|
| `minimal` | 7-key whitelist (`unified_id` / `primary_name` / `tier` / `prefecture` / `authority_name` / `amount_max_man_yen` / `official_url`) | 詳細画面では通常使わないが、埋め込み UI の軽量表示に |
| `default` (省略時) | `ProgramDetail` (Program + `enriched` + `source_mentions` + lineage) — 従来と完全互換 | 通常の統合 |
| `full` | 同上。ただし `enriched` / `source_mentions` / lineage 3 キーは null でも必ず key が存在する契約に揃う | 「null = 調査済で空」「key なし = 旧サーバー」を区別する必要がある AI agent 向け |

**Response (`ProgramDetail`):** `SearchResponse.results[]` と同じ構造 + 以下:

```json
{
  "...Program fields...": "...",
  "enriched": {
    "A_basics": {"...": "..."},
    "B_target": {"...": "..."},
    "J_statistics": null
  },
  "source_mentions": [
    {"url": "https://...", "fetched_at": "2026-04-15T10:00:00Z", "confidence": 0.9}
  ]
}
```

**Example:**

```bash
# default (current behavior, unchanged)
curl -H "X-API-Key: am_..." \
  "https://api.zeimu-kaikei.ai/v1/programs/keiei-kaishi-shikin"

# minimal — just the headline fields
curl -H "X-API-Key: am_..." \
  "https://api.zeimu-kaikei.ai/v1/programs/keiei-kaishi-shikin?fields=minimal"

# full — enriched / source_mentions / lineage keys guaranteed present
curl -H "X-API-Key: am_..." \
  "https://api.zeimu-kaikei.ai/v1/programs/keiei-kaishi-shikin?fields=full"
```

**エラー:** 存在しない ID は `404 Not Found`。

---

### `POST /v1/programs/batch`

最大 50 件の `unified_id` をまとめて解決する。`GET /v1/programs/{unified_id}` を N 回叩く代わりに 1 リクエストで済ませる用途 (agent が `search_programs` の 20 件候補を全件 enrich したい等)。

**認証:** 任意 (未認証は匿名扱い)

**Request body (`BatchGetProgramsRequest`):**

```json
{"unified_ids": ["UNI-keiei-kaishi-shikin", "UNI-koyo-shuno-shikin", "UNI-test-a-1"]}
```

| field | type | required | description |
|-------|------|----------|-------------|
| `unified_ids` | string[] | yes | 1〜50 件の制度 ID。重複は自動 dedupe (最初の出現順を保持) |

**バリデーション:**

- `unified_ids` が空配列 → `422 Unprocessable Entity`
- 50 件超 → `422 Unprocessable Entity`
- `unified_ids` の cap は 50 件 (paging は提供しない。50 超の caller は client 側で chunk する)

**Response (`BatchGetProgramsResponse`):**

```json
{
  "results": [
    {
      "unified_id": "UNI-keiei-kaishi-shikin",
      "primary_name": "経営開始資金",
      "tier": "S",
      "enriched": {"A_basics": {"...": "..."}},
      "source_mentions": [{"url": "https://...", "fetched_at": "2026-04-15T..."}],
      "source_url": "https://...",
      "source_fetched_at": "2026-04-22T...",
      "source_checksum": "638865704e10041c",
      "...": "..."
    }
  ],
  "not_found": ["UNI-typo-1"]
}
```

| field | type | description |
|-------|------|-------------|
| `results` | `ProgramDetail[]` | 各要素は `GET /v1/programs/{id}?fields=full` と同じ shape。`enriched` / `source_mentions` / lineage 3 キーは `null` でも必ず存在。**dedupe 後の入力 `unified_ids` 順を保存** |
| `not_found` | string[] | DB に該当行がなかった ID。部分成功扱いなので 404 ではなく 200 で `not_found[]` に入る |

**重要な契約:**

- **順序保証:** `results[i].unified_id` は dedupe 後の `unified_ids[i]` と一致する。
- **部分成功:** 50 件のうち 3 件が存在しなくても 200 が返り、3 件は `not_found[]` に入る。全件無しでも `{"results": [], "not_found": [...]}` で 200。
- **例外は 500:** `not_found` は「DB に存在しない」ケースだけ。JSON decode 失敗等の例外は batch 全体が `500` で落ちる (部分成功を暗黙に隠さない方針)。
- **paging なし:** 50-cap がそのまま paging。50 超の ID リストは client 側で `chunk(ids, 50)` してループする。

**Rate limit:** 現在は batch 全体で 1 request 扱い (匿名: 50/月 per IP のうち 1 消費、paid: metered で 1 req 分 ¥3/req (税込 ¥3.30) を usage report)。将来的に N 件 × N 単位の課金に移行予定 (launch 後、`src/jpintel_mcp/api/programs.py` の `batch_get_programs` TODO 参照)。

**Example:**

```bash
curl -X POST https://api.zeimu-kaikei.ai/v1/programs/batch \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"unified_ids":["UNI-keiei-kaishi-shikin","UNI-koyo-shuno-shikin"]}'
```

```python
# SDK パターン: search -> batch で 20 件 enrich
import httpx

with httpx.Client(
    base_url="https://api.zeimu-kaikei.ai",
    headers={"X-API-Key": "am_..."},
) as client:
    search = client.get(
        "/v1/programs/search",
        params={"q": "IT導入", "fields": "minimal", "limit": 20},
    ).json()
    ids = [row["unified_id"] for row in search["results"]]
    detail = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ids},
    ).json()
    for row in detail["results"]:
        print(row["unified_id"], row["primary_name"], row.get("enriched"))
    if detail["not_found"]:
        print("missing:", detail["not_found"])
```

---

## Exclusions

制度の排他ルール関連。概念は [exclusions.md](./exclusions.md)。

### `GET /v1/exclusions/rules`

排他ルール全件を返す (現在 181 件: hand-seeded 35 + 要綱 PDF からの heuristic 抽出 146)。

> **注意:** 146 件の `excl-ext-*` ルールは要綱 PDF からの rule-based heuristic 抽出で、人手レビュー済みではあるが取りこぼし / 誤検出の可能性が残る。 また hand-seeded 35 件 + heuristic 146 件いずれも、 ヒットしなかった (`hits: []`) ことは「併用して安全」を保証しない。 確定的な exclusion 判定は `source_urls` の一次資料を人手で確認すること。

**認証:** 任意

**Response (`list[ExclusionRule]`):**

```json
[
  {
    "rule_id": "agri-001",
    "kind": "mutex",
    "severity": "absolute",
    "program_a": "keiei-kaishi-shikin",
    "program_b": "koyo-shuno-shikin",
    "program_b_group": [],
    "description": "経営開始資金と雇用就農資金は同時受給不可",
    "source_notes": "MAFF 要綱 第3条",
    "source_urls": ["https://www.maff.go.jp/..."],
    "extra": {}
  }
]
```

**フィールド:**

| field | type | description |
|-------|------|-------------|
| `rule_id` | string | ルール一意 ID |
| `kind` | string | `mutex` / `prerequisite` / `conditional_reduction` など |
| `severity` | string \| null | `absolute` / `conditional` など |
| `program_a` | string \| null | 片側の制度 ID |
| `program_b` | string \| null | もう片側の制度 ID (または group を使用) |
| `program_b_group` | string[] | 複数制度が相手の場合のグループ |
| `description` | string \| null | 人間可読な説明 |
| `source_notes` | string \| null | 出典の簡易メモ |
| `source_urls` | string[] | 一次資料 URL |
| `extra` | object | 追加メタ |

---

### `POST /v1/exclusions/check`

候補制度セットに対して排他ルールが triggered するか判定する。

**認証:** 任意

**Request body (`ExclusionCheckRequest`):**

```json
{
  "program_ids": ["keiei-kaishi-shikin", "koyo-shuno-shikin"]
}
```

| field | type | required | description |
|-------|------|----------|-------------|
| `program_ids` | string[] | yes (1 件以上) | 制度 ID 配列。重複は自動 dedup |

**Response (`ExclusionCheckResponse`):**

```json
{
  "program_ids": ["keiei-kaishi-shikin", "koyo-shuno-shikin"],
  "hits": [
    {
      "rule_id": "agri-001",
      "kind": "mutex",
      "severity": "absolute",
      "programs_involved": ["keiei-kaishi-shikin", "koyo-shuno-shikin"],
      "description": "同時受給不可",
      "source_urls": ["https://www.maff.go.jp/..."]
    }
  ],
  "checked_rules": 35
}
```

**判定ロジック:**

- `kind == "mutex"` は 2 件以上 selected に含まれると hit
- `kind == "prerequisite"` は 1 件でも含まれば hit (順序違反候補としてレポート)

> **限界 (重要):** ルール母集団は hand-seeded 35 + 要綱 PDF heuristic 抽出 146 = 181 件。 `hits: []` は「未登録の組合せ」を含むため「併用して安全」を意味しない。 実申請前に必ず `source_urls` の一次資料を人手で確認すること。

**エラー:** `program_ids` が空なら `400 Bad Request`。

**Example:**

```bash
curl -X POST -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"program_ids":["keiei-kaishi-shikin","koyo-shuno-shikin"]}' \
  https://api.zeimu-kaikei.ai/v1/exclusions/check
```

---

## Meta

### `GET /v1/meta`

データセット全体の統計。ダッシュボード表示や health check 用途。

**認証:** 任意

**Response (`Meta`):**

```json
{
  "total_programs": 13578,
  "tier_counts": {"S": 1, "A": 543, "B": 59, "C": 10944, "X": 2031},
  "prefecture_counts": {"青森県": 42, "_none": 4311, "...": "..."},
  "exclusion_rules_count": 181,
  "last_ingested_at": "2026-04-25T17:25:00Z",
  "data_as_of": "2026-04-25",
  "data_lineage": {
    "last_fetched_at": "2026-04-25T17:25:00Z",
    "unique_checksums": 12873
  }
}
```

- `total_programs` は `programs` 全件 (tier S/A/B/C 11,684 + 公開保留 2,788 = 14,472)
- `tier_counts` は tier 別件数。**公開保留中の制度は search では常に除外**
- `prefecture_counts` の `_none` は prefecture=null (全国制度または未ラベル) のバケット
- `exclusion_rules_count` は `exclusion_rules` 全件 (181: hand-seeded 35 + 要綱 PDF 抽出 146)
- `last_ingested_at` は DB の最終 ingest 時刻, `data_as_of` は元データの基準日
- `data_lineage.last_fetched_at` は `programs.source_fetched_at` の最大値、`unique_checksums` は `source_checksum` のユニーク数 (列が存在する時のみ)
- 採択事例 / 融資 / 行政処分 / 法令 等の周辺データセット件数は本エンドポイントの返却対象外 (それぞれ専用エンドポイント側で取得)

**Example:**

```bash
curl https://api.zeimu-kaikei.ai/v1/meta
```

**Legacy alias (deprecated):** `GET /meta` は `/v1/meta` へ **`308 Permanent Redirect`** する。既存の client は stop する前に `/v1/` prefix へ書き換えること。legacy path は lifecycle 系 (unversioned) 扱いで、将来のメジャーバージョンで削除の可能性あり。

---

### `GET /healthz`

Liveness probe。DB 接続のみ確認。

**認証:** 不要

**Response:**

```json
{"status": "ok"}
```

---

### `GET /v1/ping`

認証付き probe。`/healthz` は liveness (DB ping のみ) で key 検証をしないため、
「今この key で API に届くか + tier は何か」を 1 本で確認したい時に使う。

**認証:** 任意 (未認証は free 扱い)

**Response:**

```json
{
  "ok": true,
  "authenticated": true,
  "tier": "paid",
  "server_time_utc": "2026-04-23T14:00:00Z",
  "server_version": "0.1.0",
  "rate_limit_remaining": null
}
```

| field | type | description |
|-------|------|-------------|
| `ok` | bool | 常に `true` (到達できた時点で) |
| `authenticated` | bool | 有効な key が提示されたか |
| `tier` | string | `free` / `paid` |
| `server_time_utc` | string | サーバー時刻 (UTC, `YYYY-MM-DDTHH:MM:SSZ`) |
| `server_version` | string | 税務会計AI version |
| `rate_limit_remaining` | int \| null | 本日の残り呼び出し数。`paid` (metered) は `null` (hard cap なし) |

**使用量への影響:** **`/v1/ping` は認証付き呼び出しのみ usage_events にカウントされる**
(heartbeat で無限に叩かれる濫用を抑止するため)。未認証呼び出しはカウントしない
(per-IP の記録を持たないため)。頻繁に heartbeat したい用途では `/healthz` を推奨。

**匿名時の `rate_limit_remaining`:** 未認証時は匿名クォータの上限値そのものが返る
(per-IP 使用量を記録していないため、正確な残量を返せない)。

**Example:**

```bash
curl -H "X-API-Key: am_..." https://api.zeimu-kaikei.ai/v1/ping
```

---

## Billing

Stripe 経由のサブスクリプション管理。詳細フローは [getting-started.md](./getting-started.md#2-api-key-を取得する-get-an-api-key)。

### `POST /v1/billing/checkout`

Stripe Checkout セッションを作成して URL を返す。

**認証:** 不要

**Request body:**

| field | type | required | description |
|-------|------|----------|-------------|
| `success_url` | string | yes | 決済後のリダイレクト先 (session_id を受け取るページ) |
| `cancel_url` | string | yes | キャンセル時のリダイレクト先 |
| `customer_email` | string | no | Stripe に事前に渡すメールアドレス |

tier フィールドは存在しない (pure metered、Price は 1 本: `STRIPE_PRICE_PER_REQUEST` 環境変数で指定)。

**Response:**

```json
{"url": "https://checkout.stripe.com/...", "session_id": "cs_live_..."}
```

**エラー:** `STRIPE_PRICE_PER_REQUEST` 未設定時は `400 price not configured`。Stripe ライブラリ自体が初期化できない場合は `503`。

---

### `POST /v1/billing/portal`

Stripe Customer Portal URL を返す (サブスク変更・キャンセル・カード変更用)。

**認証:** 不要 (customer_id を body に渡す)

**Request body:**

```json
{"customer_id": "cus_...", "return_url": "https://your-app.example.com/account"}
```

**Response:**

```json
{"url": "https://billing.stripe.com/..."}
```

---

### `POST /v1/billing/keys/from-checkout`

Checkout 成功後に API key を発行する。1 session につき 1 回のみ。

**認証:** 不要 (Stripe session 検証で認証)

**Request body:**

```json
{"session_id": "cs_live_..."}
```

**Response:**

```json
{"api_key": "am_...", "tier": "metered", "customer_id": "cus_..."}
```

`tier` is a server-side key category label (`anonymous` / `metered` / `admin`) used for internal accounting and logging — **not a pricing SKU**. Clients should ignore it; pricing is fixed at ¥3/req metered (税込 ¥3.30) for any non-anonymous key.

**エラー:**

- `402 Payment Required` — session が paid になっていない
- `409 Conflict` — 同 subscription で既に key 発行済み (rotation は `/v1/billing/portal` 経由)

---

### `POST /v1/billing/webhook`

Stripe webhook 受け口。以下のイベントを処理:

- `customer.subscription.created` — 初回サブスク時に API key を自動発行 (主経路)
- `invoice.paid` — safety net として同じく key 発行 (subscription.created を取りこぼした場合)
- `customer.subscription.updated` — 状態同期
- `customer.subscription.deleted` — key の revoke (匿名クォータに戻る)
- `invoice.payment_failed` — 支払い失敗の記録

**認証:** Stripe 署名 (`stripe-signature` header) で検証

**Response:** `{"status": "received"}`

エンドユーザーが直接叩くものではない。

---

## Feedback

### `POST /v1/feedback`

開発者向けの feedback 受け口。変なレスポンスを見つけた時・命名案がある時に、
GitHub issue を開く前に 1 POST で送れる軽量窓口。

**認証:** 任意 (未認証でも OK)。key を付ければ `customer_id` + `tier` が紐付く。

**Request body (`FeedbackRequest`):**

```json
{
  "message": "search で 認定新規就農者 が Hit しない件",
  "rating": 3,
  "endpoint": "/v1/programs/search",
  "request_id": "abcd1234"
}
```

| field | type | required | description |
|-------|------|----------|-------------|
| `message` | string | yes | 1〜4000 文字。自由記述 |
| `rating` | int | no | 1〜5 (満足度) |
| `endpoint` | string | no | 関連エンドポイント (例: `/v1/programs/search`) |
| `request_id` | string | no | `x-request-id` header の値など |

**Response (`FeedbackResponse`):**

```json
{"received": true, "feedback_id": 42}
```

**Rate limit:** 1 日あたり **10 件** per API key (認証時) または per IP hash (未認証時)。
超過時は `429 Too Many Requests`。

**保存される情報:**

- `message`, `rating`, `endpoint`, `request_id` (上記入力)
- 認証時: `key_hash`, `customer_id`, `tier`
- `ip_hash` (raw IP は保存しない / HMAC-SHA256 with salt)
- `created_at` (UTC ISO)

**Example:**

```bash
curl -X POST https://api.zeimu-kaikei.ai/v1/feedback \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"message":"公開保留判定の理由が見えづらい","rating":4}'
```

---

## エラー形式 (Error format)

FastAPI 標準:

```json
{"detail": "エラー理由"}
```

| code | 意味 |
|------|------|
| 400 | リクエスト不正 (params / body) |
| 401 | 認証失敗 / revoked key |
| 402 | Stripe 決済未完了 |
| 404 | リソース無し |
| 409 | 重複操作 (key 発行済み等) |
| 429 | rate limit 超過 |
| 503 | Stripe 未設定など運用外状態 |

---

## カテゴリ別エンドポイント (Auto-generated from OpenAPI)

下記は OpenAPI spec (`docs/openapi/v1.json`) から machine-generated した残り 99 endpoint。`scripts/export_openapi.py` が re-export した時点の正本に基づくので、本ページ前半の 13 endpoint と異なり手動加筆の解説は薄め (request/response の shape, curl 例のみ) — 詳細は OpenAPI spec、もしくは [mcp-tools.md](./mcp-tools.md) の同名 MCP tool を参照。

> **凡例:**
> - **認証** 列の "任意 (未認証は匿名扱い)" は 50 req/月 per IP の anonymous quota を消費する。**必須** は 401/403 を返す (Bearer / X-API-Key 必須)。
> - **Response** の `"..."` は array/object の省略表記。完全 schema は OpenAPI spec を参照。
> - **36協定** template (`/v1/am/templates/saburoku_kyotei*`) は `AUTONOMATH_36_KYOTEI_ENABLED=true` の launch gate 配下。default では OpenAPI から消え、`mcp.list_tools()` でも返らない。

---

## Programs (additional)

### `POST /v1/programs/prescreen`

Rank programs by fit to a caller business profile.

This is the "judgment" complement to `/v1/programs/search`'s "discovery".
See `src/jpintel_mcp/api/prescreen.py` module docstring for scope.

**認証:** 任意 (未認証は匿名扱い)

**Request body (`PrescreenRequest`):**

```json
{
  "company_url": "string",
  "declared_certifications": [
    "..."
  ],
  "employee_count": 0,
  "founded_year": 0,
  "houjin_bangou": "string",
  "industry_jsic": "string",
  "is_sole_proprietor": true,
  "limit": 10,
  "...": "..."
}
```

**Response 200 (`PrescreenResponse`):**

```json
{
  "limit": 0,
  "profile_echo": {},
  "results": [
    "..."
  ],
  "total_considered": 0
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/programs/prescreen" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"company_url": "string", "declared_certifications": ["..."], "employee_count": 0, "founded_year": 0, "houjin_bangou": "string", "industry_jsic": "string", "is_sole_proprietor": true, "limit": 10, "...": "..."}'
```

---

## Meta (additional)

### `GET /readyz`

Readyz

**認証:** 不要

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/readyz"
```

---

### `GET /v1/meta/freshness`

Meta Freshness

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `limit` | integer | no | — |
| `sort_by` | string | no | — |
| `tier` | string | no | — |

**Response 200 (`MetaFreshnessResponse`):**

```json
{
  "generated_at": "string",
  "median_fetched_at": "string",
  "pct_over_180d": 0.0,
  "pct_within_30d": 0.0,
  "top_rows": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/meta/freshness?limit=50" \
  -H "X-API-Key: am_..."
```

---

## Billing (additional)

### `POST /v1/billing/refund_request`

Stripe で課金された ¥3/req メータリング分の返金を顧客が請求する ためのエンドポイント。運営側で 14 日以内に手動審査を行います。 このエンドポイントは受付番号の発行と通知のみで、自動的な返金や API キー失効は行いません。既に課金済みの分も審査完了までそのまま 残ります。

**認証:** 任意 (manual review)

**Request body (`RefundRequest`):**

```json
{
  "amount_yen": 0,
  "customer_id": "string",
  "reason": "string",
  "requester_email": "user@example.com"
}
```

**Response 201 (`RefundResponse`):**

```json
{
  "contact": "info@bookyou.net",
  "expected_response_within_days": 14,
  "note": "返金は手動審査となります。既に課金済みの ¥3/req メータリング分は 自動取消しされません — 審査完了後、運営から個別にご連絡します。",
  "received_at": "string",
  "request_id": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/billing/refund_request" \
  -H "Content-Type: application/json" \
  -d '{"amount_yen": 0, "customer_id": "string", "reason": "string", "requester_email": "user@example.com"}'
```

---

## Account & API Keys (`/v1/me`)

### `GET /v1/me`

Get Me

**認証:** **必須** (Bearer / X-API-Key)

**Response 200 (`MeResponse`):**

```json
{
  "created_at": "string",
  "customer_id": "string",
  "key_hash_prefix": "string",
  "subscription_cancel_at_period_end": true,
  "subscription_current_period_end": "string",
  "subscription_status": "string",
  "tier": "string"
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/me" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/me/billing-portal`

Billing Portal

**認証:** **必須** (Bearer / X-API-Key)

**Response 200 (`BillingPortalResponse`):**

```json
{
  "url": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/me/billing-portal" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/me/billing_history`

Most-recent Stripe invoices for the calling key's customer.

Uses a 5-minute in-process cache keyed by `customer_id`. Empty list when
Stripe is unconfigured or the customer has no invoices yet — this is not
an error, just a cold-start state.

**認証:** **必須** (Bearer / X-API-Key)

**Response 200 (`BillingHistoryResponse`):**

```json
{
  "cached_at": "string",
  "customer_id": "string",
  "invoices": [
    "..."
  ]
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/me/billing_history" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/me/cap`

Set the customer's self-serve monthly spend cap (P3-W).

Authenticated via require_key (X-API-Key header or Authorization: Bearer).
Anonymous callers (no key) cannot set a cap because the anonymous tier is
already gated by the 50 req/月 free quota — there is nothing to cap.

The unit price stays ¥3/req (immutable per
project_autonomath_business_model). `monthly_cap_yen` is purely a client
budget control: at cap-reached the middleware returns 503 with
`cap_reached: true` and Stripe usage is NOT recorded for the rejected
request, so the cap is hard.

**認証:** **必須** (Bearer / X-API-Key)

**Request body (`CapRequest`):**

```json
{
  "monthly_cap_yen": 0
}
```

**Response 200 (`CapResponse`):**

```json
{
  "monthly_cap_yen": 0,
  "ok": true
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/me/cap" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"monthly_cap_yen": 0}'
```

---

### `GET /v1/me/dashboard`

30-day usage summary for the calling key.

Bearer-authenticated. The series is filled with zeros for days with no
usage so the UI can render a contiguous bar chart without client-side
gap-filling.

**認証:** **必須** (Bearer / X-API-Key)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `days` | integer | no | — |

**Response 200 (`DashboardSummary`):**

```json
{
  "cap_remaining_yen": 0,
  "current_period_end": "string",
  "days": 0,
  "key_hash_prefix": "string",
  "last_30_amount_yen": 0,
  "last_30_calls": 0,
  "last_7_calls": 0,
  "month_to_date_amount_yen": 0,
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/me/dashboard?days=30" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/me/rotate-key`

Revoke the current key and issue a new one in a single atomic txn.

P0 fixes from audit a4298e454aab2aa43:
  - P0-1: BEGIN IMMEDIATE / COMMIT around the revoke + insert. Without
    this the connection runs in autocommit (db.session.connect uses
    isolation_level=None), so a crash between the UPDATE and the INSERT
    leaves the customer with neither a working old key nor a new key.
    BEGIN IMMEDIATE acquires the writer lock up-front, which also serves
    as the lock for the concurrent-rotation race (only one writer at
    a time; the loser gets SQLITE_BUSY and bubbles up as 5xx).
  - P0-3: carry forward `monthly_cap_yen` so the customer's spend cap
    is not silently reset to NULL (unlimited) on rotation. Also migrate
    any `alert_subscriptions` rows from old key_hash to new — otherwise
    the customer's amendment alerts go silent on rotation.
  - Bonus: re-issue the session cookie bound to the NEW key_hash so the
    dashboard stays logged in. With P0-2 in place, the OLD cookie now
    401s on next /v1/me, so without this the user gets bounced to
    /login the moment they rotate.

**認証:** **必須** (Bearer / X-API-Key)

**Response 200 (`RotateKeyResponse`):**

```json
{
  "api_key": "string",
  "tier": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/me/rotate-key" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/me/tool_recommendation`

Map a free-text intent to ranked tool candidates.

Pure keyword scoring — no LLM call (memory: feedback_autonomath_no_api_use).
The caller is expected to be an LLM agent; we return signal, the caller
composes the next request.

**認証:** **必須** (Bearer / X-API-Key)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `intent` | string | yes | — |
| `limit` | integer | no | — |

**Response 200 (`ToolRecommendationResponse`):**

```json
{
  "fallback_used": true,
  "intent": "string",
  "tools": [
    "..."
  ]
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/me/tool_recommendation" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/me/usage`

Get Me Usage

**認証:** **必須** (Bearer / X-API-Key)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `days` | integer | no | — |

**Response 200:**

```json
[
  {
    "calls": 0,
    "date": "string"
  }
]
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/me/usage?days=30" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/me/usage_by_tool`

Top N endpoints by call count over the requested window.

**認証:** **必須** (Bearer / X-API-Key)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `days` | integer | no | — |
| `limit` | integer | no | — |

**Response 200 (`ToolUsageResponse`):**

```json
{
  "days": 0,
  "top": [
    "..."
  ],
  "total_amount_yen": 0,
  "total_calls": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/me/usage_by_tool?days=30" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/session`

Create Session

**認証:** 任意 (未認証は匿名扱い)

**Request body (`SessionRequest`):**

```json
{
  "api_key": "string"
}
```

**Response 200 (`SessionResponse`):**

```json
{
  "key_hash_prefix": "string",
  "tier": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/session" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"api_key": "string"}'
```

---

### `POST /v1/session/logout`

Logout

**認証:** 任意 (未認証は匿名扱い)

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/session/logout" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/usage`

Probe the caller's current quota state without consuming a slot.

The handler is *not* attached to ``AnonIpLimitDep`` so anonymous
callers can call it freely — the whole point of the tool is to
avoid burning the bucket while checking it.

**認証:** 任意 (未認証は匿名扱い)

**Response 200 (`UsageStatus`):**

```json
{
  "limit": 0,
  "note": "string",
  "remaining": 0,
  "reset_at": "string",
  "reset_timezone": "string",
  "tier": "string",
  "upgrade_url": "string",
  "used": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/usage" \
  -H "X-API-Key: am_..."
```

---

## Alerts (`/v1/me/alerts`)

### `POST /v1/me/alerts/subscribe`

Create a new alert subscription on the calling key.

At least one delivery channel is required: webhook_url OR email. A
subscription with neither is meaningless (the cron has nowhere to send).

`filter_value` is required for every filter_type EXCEPT 'all'. For 'all'
it is silently ignored (we set NULL on disk for clarity).

**認証:** **必須** (Bearer / X-API-Key)

**Request body (`jpintel_mcp__api__alerts__SubscribeRequest`):**

```json
{
  "email": "user@example.com",
  "filter_type": "tool",
  "filter_value": "string",
  "min_severity": "critical",
  "webhook_url": "string"
}
```

**Response 201 (`SubscriptionResponse`):**

```json
{
  "active": true,
  "created_at": "string",
  "email": "string",
  "filter_type": "string",
  "filter_value": "string",
  "id": 0,
  "last_triggered": "string",
  "min_severity": "string",
  "...": "..."
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/me/alerts/subscribe" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "filter_type": "tool", "filter_value": "string", "min_severity": "critical", "webhook_url": "string"}'
```

---

### `GET /v1/me/alerts/subscriptions`

List the calling key's active subscriptions.

Inactive (deactivated) rows are NOT returned by default — they are kept
on disk for audit but are noise on the read path. There is no
`?include_inactive=true` flag in MVP; the customer who wants to inspect
history can hit the DB directly via support.

**認証:** **必須** (Bearer / X-API-Key)

**Response 200:**

```json
[
  {
    "active": true,
    "created_at": "string",
    "email": "...",
    "filter_type": "string",
    "filter_value": "...",
    "id": 0,
    "last_triggered": "...",
    "min_severity": "string",
    "...": "..."
  }
]
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/me/alerts/subscriptions" \
  -H "X-API-Key: am_..."
```

---

### `DELETE /v1/me/alerts/subscriptions/{sub_id}`

Deactivate (soft-delete) the subscription.

The row stays on disk with active=0 so audit trails remain intact. A
re-subscribe creates a fresh row rather than reviving the old one — this
keeps `created_at` semantically honest.

404 when the id does not belong to this key OR when it is already
inactive (so callers cannot probe the id-space of other keys).

**認証:** **必須** (Bearer / X-API-Key)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `sub_id` | integer | yes | — |

**Response 200 (`DeactivateResponse`):**

```json
{
  "id": 0,
  "ok": true
}
```

**Example:**

```bash
curl -X DELETE "https://api.zeimu-kaikei.ai/v1/me/alerts/subscriptions/<sub_id>" \
  -H "X-API-Key: am_..."
```

---

## Session & Device

### `POST /v1/device/authorize`

Mint a fresh (device_code, user_code) pair (RFC 8628 §3.1).

**認証:** 任意 (未認証は匿名扱い)

**Request body (`AuthorizeRequest`):**

```json
{
  "client_id": "autonomath-mcp",
  "scope": "string"
}
```

**Response 200 (`AuthorizeResponse`):**

```json
{
  "device_code": "string",
  "expires_in": 0,
  "interval": 0,
  "user_code": "string",
  "verification_uri": "string",
  "verification_uri_complete": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/device/authorize" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"client_id": "autonomath-mcp", "scope": "string"}'
```

---

### `POST /v1/device/complete`

Called by /go after Stripe Checkout succeeds.

1. Verifies the Stripe session is paid (or metered — no_payment_required).
2. Marks device_code activated.
3. Issues an api_keys row prefixed 'am_device_' and links it.
4. Stashes the raw key in the in-process pickup map so the MCP's
   next /token poll picks it up.

**認証:** 任意 (未認証は匿名扱い)

**Request body (`CompleteRequest`):**

```json
{
  "stripe_checkout_session_id": "string",
  "user_code": "string"
}
```

**Response 200 (`CompleteResponse`):**

```json
{
  "ok": true
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/device/complete" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"stripe_checkout_session_id": "string", "user_code": "string"}'
```

---

### `POST /v1/device/token`

Device-flow poll endpoint (RFC 8628 §3.4).

Success → {access_token, token_type, scope} + 200.
Pending → authorization_pending (400).
Polling too fast → slow_down (400).
Expired → expired_token (400).
Denied → access_denied (400).
Invalid grant_type / device_code → invalid_grant (400).

**認証:** 任意 (未認証は匿名扱い)

**Request body (`TokenRequest`):**

```json
{
  "client_id": "autonomath-mcp",
  "device_code": "string",
  "grant_type": "string"
}
```

**Response 200 (`TokenSuccess`):**

```json
{
  "access_token": "string",
  "scope": "string",
  "token_type": "Bearer"
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/device/token" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"client_id": "autonomath-mcp", "device_code": "string", "grant_type": "string"}'
```

---

## Subscribers (Email)

### `GET /v1/email/unsubscribe`

HTML variant — clicked from a footer link.

Mail clients and corporate scanners pre-fetch GET links to scan for
malware. To keep that from auto-unsubscribing, we ONLY honour the
GET when the token verifies AND the user explicitly hits the page.
Token verification is the same HMAC check as POST so a bot-fetch with
a stolen-but-real token would still unsubscribe — that's by design;
a real token implies real user intent.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `email` | string | yes | — |
| `token` | string | yes | — |

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/email/unsubscribe" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/email/unsubscribe`

Idempotent self-serve master-list opt-out.

On invalid token we DO NOT raise 401 — that would let an attacker
enumerate which addresses are valid. We return the success shape
with a fixed timestamp instead. The internal write is silently
skipped.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `email` | string | yes | — |
| `token` | string | yes | — |
| `reason` | string | null | no | — |

**Response 200 (`UnsubscribeResponse`):**

```json
{
  "at": "string",
  "unsubscribed": true
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/email/unsubscribe" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/email/webhook`

Postmark Webhook

**認証:** Stripe / Postmark 署名検証 (header)

**Response 200:**

```json
{}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/email/webhook"
```

---

### `POST /v1/subscribers`

Subscribe

**認証:** 任意 (未認証は匿名扱い)

**Request body (`jpintel_mcp__api__subscribers__SubscribeRequest`):**

```json
{
  "email": "user@example.com",
  "source": "string"
}
```

**Response 201 (`jpintel_mcp__api__subscribers__SubscribeResponse`):**

```json
{
  "subscribed": true
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/subscribers" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "source": "string"}'
```

---

### `GET /v1/subscribers/unsubscribe`

Unsubscribe

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `token` | string | yes | — |
| `email` | string | yes | — |

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/subscribers/unsubscribe" \
  -H "X-API-Key: am_..."
```

---

## Compliance Newsletter

### `POST /v1/compliance/stripe-checkout`

Create a Stripe Checkout Session for a verified paid subscriber.

Requires the subscriber row to already exist and be verified. The
session's `client_reference_id` is the subscriber_id so the webhook
can tie the Stripe subscription back to our row.

**認証:** 任意 (未認証は匿名扱い)

**Request body (`jpintel_mcp__api__compliance__CheckoutRequest`):**

```json
{
  "cancel_url": "https://zeimu-kaikei.ai/alerts.html?status=canceled",
  "subscriber_id": 0,
  "success_url": "https://zeimu-kaikei.ai/alerts.html?status=ok"
}
```

**Response 200 (`jpintel_mcp__api__compliance__CheckoutResponse`):**

```json
{
  "session_id": "string",
  "url": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/compliance/stripe-checkout" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"cancel_url": "https://zeimu-kaikei.ai/alerts.html?status=canceled", "subscriber_id": 0, "success_url": "https://zeimu-kaikei.ai/alerts.html?status=ok"}'
```

---

### `POST /v1/compliance/stripe-webhook`

Handle customer.subscription.created/.deleted for the alert product.

On `created` we persist stripe_customer_id / stripe_subscription_id +
flip plan to 'paid' if it wasn't already.
On `deleted` we mark canceled_at (same effect as a customer clicking
the unsubscribe link — Stripe Customer Portal cancel path).

**認証:** Stripe / Postmark 署名検証 (header)

**Response 200:**

```json
{}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/compliance/stripe-webhook"
```

---

### `POST /v1/compliance/subscribe`

Create a new pending subscription + send verification email.

Flow:
    1. Insert row with `verification_token` set, `verified_at=NULL`.
    2. Send verification email (async best-effort via Postmark).
    3. If plan='paid', return `next_step='checkout'` + a placeholder
       response — the caller should then POST /stripe-checkout.
       (The caller must verify FIRST; the verify GET redirects to
       the checkout for paid plans — see below.)
    4. If plan='free', return `next_step='verify'`.

Duplicate email behaviour: we return the SAME response shape whether
this is a fresh signup or an already-existing email — no enumeration
leak. A second subscribe with the same email re-sends the verification
mail (an attacker cannot see `verified_at` from the endpoint; worst
case they can DoS our Postmark budget, which the anon rate limit
covers).

**認証:** 任意 (未認証は匿名扱い)

**Request body (`jpintel_mcp__api__compliance__SubscribeRequest`):**

```json
{
  "areas_of_interest": [
    "string"
  ],
  "email": "user@example.com",
  "houjin_bangou": "string",
  "industry_codes": [
    "string"
  ],
  "plan": "free",
  "prefecture": "string",
  "source_lang": "ja"
}
```

**Response 201 (`jpintel_mcp__api__compliance__SubscribeResponse`):**

```json
{
  "checkout_url": "string",
  "next_step": "verify",
  "subscriber_id": 0
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/compliance/subscribe" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"areas_of_interest": ["string"], "email": "user@example.com", "houjin_bangou": "string", "industry_codes": ["string"], "plan": "free", "prefecture": "string", "source_lang": "ja"}'
```

---

### `POST /v1/compliance/unsubscribe/{unsubscribe_token}`

Cancel the subscription.

- For `plan='paid'`: also cancels the Stripe subscription (best-effort;
  if Stripe is down we still mark canceled_at locally so no more
  emails go out).
- For `plan='free'`: just marks `canceled_at`.
Returns HTML so the static unsubscribe landing page can call this
via fetch + show the body.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `unsubscribe_token` | string | yes | — |

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/compliance/unsubscribe/<unsubscribe_token>" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/compliance/verify/{verification_token}`

Mark a subscriber as verified. Renders a minimal HTML page.

A valid token flips `verified_at = now()` and clears
`verification_token`. Idempotent — a second click shows the same
success page (we look up by email after the clear, so the row is
still findable by unsubscribe_token but not by verification_token).

For paid subscribers, the page nudges the user to the Stripe checkout
page (link to `/alerts.html#checkout`).

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `verification_token` | string | yes | — |

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/compliance/verify/<verification_token>" \
  -H "X-API-Key: am_..."
```

---

## Public Stats (Transparency)

### `GET /v1/stats/confidence`

Live Bayesian Discovery + Use posteriors per tool, last 30 days.

**認証:** 任意 (未認証は匿名扱い)

**Response 200 (`ConfidenceResponse`):**

```json
{
  "generated_at": "string",
  "overall": {},
  "per_tool": [
    "..."
  ],
  "since": "string",
  "until": "string",
  "window_days": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/stats/confidence" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/stats/coverage`

Stats Coverage

**認証:** 任意 (未認証は匿名扱い)

**Response 200 (`CoverageResponse`):**

```json
{
  "bids": 0,
  "case_studies": 0,
  "court_decisions": 0,
  "enforcement_cases": 0,
  "exclusion_rules": 0,
  "generated_at": "string",
  "invoice_registrants": 0,
  "laws_jpintel": 0,
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/stats/coverage" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/stats/data_quality`

Stats Data Quality

**認証:** 任意 (未認証は匿名扱い)

**Response 200 (`DataQualityResponse`):**

```json
{
  "cross_source_agreement": {},
  "fact_count_total": 0,
  "field_kind_breakdown": {},
  "freshness_buckets": {},
  "generated_at": "string",
  "label_histogram": {},
  "license_breakdown": {},
  "mean_score": 0.0,
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/stats/data_quality" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/stats/freshness`

Stats Freshness

**認証:** 任意 (未認証は匿名扱い)

**Response 200 (`FreshnessResponse`):**

```json
{
  "generated_at": "string",
  "sources": {}
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/stats/freshness" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/stats/usage`

Stats Usage

**認証:** 任意 (未認証は匿名扱い)

**Response 200 (`UsageResponse`):**

```json
{
  "daily": [
    "..."
  ],
  "generated_at": "string",
  "since": "string",
  "total": 0,
  "until": "string",
  "window_days": 30
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/stats/usage" \
  -H "X-API-Key: am_..."
```

---

## Testimonials

### `POST /v1/me/testimonials`

Submit Testimonial

**認証:** **必須** (Bearer / X-API-Key)

**Request body (`TestimonialSubmit`):**

```json
{
  "audience": "税理士",
  "linkedin_url": "string",
  "name": "string",
  "organization": "string",
  "text": "string"
}
```

**Response 201 (`TestimonialSubmitResponse`):**

```json
{
  "pending_review": true,
  "received": true,
  "testimonial_id": 0
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/me/testimonials" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"audience": "税理士", "linkedin_url": "string", "name": "string", "organization": "string", "text": "string"}'
```

---

### `DELETE /v1/me/testimonials/{testimonial_id}`

Delete My Testimonial

**認証:** **必須** (Bearer / X-API-Key)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `testimonial_id` | integer | yes | — |

**Response 204:** No Content

**Example:**

```bash
curl -X DELETE "https://api.zeimu-kaikei.ai/v1/me/testimonials/<testimonial_id>" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/testimonials`

List Testimonials

**認証:** 任意 (未認証は匿名扱い)

**Response 200 (`TestimonialListResponse`):**

```json
{
  "rows": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/testimonials" \
  -H "X-API-Key: am_..."
```

---

## Advisors

### `GET /v1/advisors/match`

Top ``limit`` advisors matching the supplied filters.

Intentionally doesn't go through the digest whitelist (ctx.log_usage
is called with no params): advisor match responses are not a retention
signal, and the params (esp. prefecture) carry enough geographic info
that hashing them into a digest starts to smell PII-adjacent.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `prefecture` | string | null | no | 都道府県. Accepts canonical, short, or romaji. |
| `specialty` | string | null | no | — |
| `industry` | string | null | no | — |
| `limit` | integer | no | — |

**Response 200 (`MatchResponse`):**

```json
{
  "ranking": {},
  "results": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/advisors/match" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/advisors/report-conversion`

Advisor marks a referral as converted. Commission computed + queued.

Authentication model: authentication is provided by possession of the
``referral_token`` (treat as a bearer secret for that single referral)
combined with the advisor later being able to verify via Stripe Connect.
A stronger model would require the advisor's API key — deferred to the
dashboard login flow.

**認証:** 任意 (未認証は匿名扱い)

**Request body (`ReportConversionRequest`):**

```json
{
  "conversion_value_yen": 0,
  "evidence_url": "https://...",
  "referral_token": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/advisors/report-conversion" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"conversion_value_yen": 0, "evidence_url": "https://...", "referral_token": "string"}'
```

---

### `POST /v1/advisors/signup`

Create an unverified advisor profile + return Stripe Connect onboarding URL.

Self-serve, no API key required (prospective advisors don't have one
yet). verified_at stays NULL until both:
  (a) /verify-houjin/{id} succeeds against invoice_registrants, AND
  (b) Stripe Connect account.updated webhook reports capabilities.transfers=active.

For advisors seeded from the 中小企業庁 認定支援機関 public list,
scripts/seed_advisors.py sets verified_at directly at seed time — this
handler path is for self-serve signups only.

**認証:** 任意 (未認証は匿名扱い)

**Request body (`SignupRequest`):**

```json
{
  "address": "string",
  "agreed_to_terms": true,
  "city": "string",
  "commission_model": "flat",
  "commission_rate_pct": 5,
  "commission_yen_per_intro": 3000,
  "contact_email": "user@example.com",
  "contact_phone": "string",
  "...": "..."
}
```

**Response 200 (`SignupResponse`):**

```json
{
  "advisor_id": 0,
  "next_step": "stripe_connect",
  "stripe_connect_onboarding_url": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/advisors/signup" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"address": "string", "agreed_to_terms": true, "city": "string", "commission_model": "flat", "commission_rate_pct": 5, "commission_yen_per_intro": 3000, "contact_email": "user@example.com", "contact_phone": "string", "...": "..."}'
```

---

### `POST /v1/advisors/track`

Record a referral click and mint a single-use redirect token.

The returned ``redirect_url`` is ``advisor.contact_url`` with
``?ref=<token>`` appended, or a fallback to an in-domain contact page
when the advisor didn't supply one. 5% or ¥3,000 commission (model
dependent) is resolved at conversion time, not click time.

**認証:** 任意 (未認証は匿名扱い)

**Request body (`TrackRequest`):**

```json
{
  "advisor_id": 0,
  "source_program_id": "string",
  "source_query_hash": "string"
}
```

**Response 200 (`TrackResponse`):**

```json
{
  "redirect_url": "string",
  "token": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/advisors/track" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"advisor_id": 0, "source_program_id": "string", "source_query_hash": "string"}'
```

---

### `POST /v1/advisors/verify-houjin/{advisor_id}`

Confirm the advisor's 法人番号 exists in invoice_registrants (migration 019).

Provisional verification: sets advisors.verified_at to the current
timestamp when the 法人番号 is found. Full verification still waits
on Stripe Connect webhook reporting capabilities.transfers=active —
query_matching_advisors() filters on verified_at alone today, so this
provisional gate is the public-visibility switch.

For 認定支援機関 rows seeded from the 中小企業庁 public list,
seed_advisors.py sets verified_at directly and this endpoint is a
no-op idempotent success.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `advisor_id` | integer | yes | — |

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/advisors/verify-houjin/<advisor_id>" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/advisors/{advisor_id}/dashboard-data`

Self-serve dashboard backing data: referrals + earnings summary.

Authentication: intentionally light today — the dashboard HTML is
expected to be reached via the Stripe Connect Express portal return
URL (or via magic-link email). Adding API-key auth here would block
the simplest flow where the advisor arrives from Stripe's own
dashboard. If this becomes abused, add a signed HMAC
``?token=...`` in the URL and verify here.

**認証:** **必須** (Bearer / X-API-Key)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `advisor_id` | integer | yes | — |

**Response 200 (`AdvisorDashboardResponse`):**

```json
{
  "advisor": {},
  "referrals": [
    "..."
  ],
  "summary": {
    "clicks": "...",
    "conversions": "...",
    "paid_yen": "...",
    "unpaid_yen": "..."
  }
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/advisors/<advisor_id>/dashboard-data" \
  -H "X-API-Key: am_..."
```

---

## Widget

### `GET /v1/widget/enum_values`

Return filter enum vocab for widget dropdowns — prefectures, industries,
authority_levels, and a short target_types list drawn from programs.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `key` | string | null | no | — |

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/widget/enum_values" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/widget/search`

Search programs restricted to the widget surface.

Proxies to the existing `/v1/programs/search` logic via direct function
import — there is no internal HTTP hop so the widget path stays under
the tight latency budget (TTFB matters on a 3rd-party's site).

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `key` | string | null | no | widget key; wgt_live_... |
| `q` | string | null | no | — |
| `prefecture` | string | null | no | — |
| `authority_level` | string | null | no | — |
| `industry` | string | null | no | — |
| `target` | string[] | null | no | — |
| `funding_purpose` | string[] | null | no | — |
| `limit` | integer | no | — |

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/widget/search" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/widget/signup`

Create a Stripe Checkout session for the widget plan.

The actual `widget_keys` row is provisioned later, in the
`checkout.session.completed` webhook handler. The Checkout session
carries `metadata.autonomath_product = 'widget'` so our webhook
knows to look up widget-specific price ids and persist to widget_keys
(not api_keys).

**認証:** 任意 (未認証は匿名扱い)

**Request body (`WidgetSignupRequest`):**

```json
{
  "cancel_url": "string",
  "email": "user@example.com",
  "label": "string",
  "origins": [
    "string"
  ],
  "plan": "business",
  "success_url": "string"
}
```

**Response 200 (`WidgetSignupResponse`):**

```json
{
  "checkout_url": "string",
  "session_id": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/widget/signup" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"cancel_url": "string", "email": "user@example.com", "label": "string", "origins": ["string"], "plan": "business", "success_url": "string"}'
```

---

### `POST /v1/widget/stripe-webhook`

Handle widget-product Stripe events.

Key lifecycle events:
  checkout.session.completed        -> provision widget_keys row
  customer.subscription.deleted     -> disabled_at = now()
  invoice.payment_failed            -> disabled_at = now() (widget is
    not dunning-tolerant like the main API — a widget on a public
    site stays disabled through dunning rather than billing overage
    nobody will ever pay for).

**認証:** Stripe / Postmark 署名検証 (header)

**Response 200:**

```json
{}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/widget/stripe-webhook"
```

---

### `GET /v1/widget/{key_id}/usage`

Owner-visible usage for their widget key. Bearer admin required.

Sparse on purpose: the dashboard consumes this via a scheduled fetch
so we return stable, JSON-first fields. A full dashboard UI is a
later ticket — this stub is enough for "how many reqs this month?".

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `key_id` | string | yes | — |

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/widget/<key_id>/usage" \
  -H "X-API-Key: am_..."
```

---

## APPI Privacy Requests

### `POST /v1/privacy/deletion_request`

個人情報の保護に関する法律 第33条 に基づく削除請求を受付けます。 このエンドポイントは受付番号の発行と運営宛通知のみを行い、 実際の削除は 30 日以内に運営側で本人確認の上で別途対応します (§33-3 法定上限)。 個人情報そのものはこのレスポンスでは返却・ 操作しません。

**認証:** 任意 (未認証は匿名扱い)

**Request body (`DeletionRequest`):**

```json
{
  "deletion_reason": "string",
  "identity_verification_method": "drivers_license",
  "requester_email": "user@example.com",
  "requester_legal_name": "string",
  "target_data_categories": [
    "representative"
  ],
  "target_houjin_bangou": "string"
}
```

**Response 201 (`DeletionResponse`):**

```json
{
  "contact": "info@bookyou.net",
  "expected_response_within_days": 30,
  "received_at": "string",
  "request_id": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/privacy/deletion_request" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"deletion_reason": "string", "identity_verification_method": "drivers_license", "requester_email": "user@example.com", "requester_legal_name": "string", "target_data_categories": ["representative"], "target_houjin_bangou": "string"}'
```

---

### `POST /v1/privacy/disclosure_request`

個人情報の保護に関する法律 第31条 に基づく開示請求を受付けます。 このエンドポイントは受付番号の発行と運営宛通知のみを行い、 実際の開示は 14 日以内に運営側で本人確認の上で別途対応します。 個人情報そのものはこのレスポンスでは返却しません。

**認証:** 任意 (未認証は匿名扱い)

**Request body (`DisclosureRequest`):**

```json
{
  "identity_verification_method": "drivers_license",
  "requester_email": "user@example.com",
  "requester_legal_name": "string",
  "target_houjin_bangou": "string"
}
```

**Response 201 (`DisclosureResponse`):**

```json
{
  "contact": "info@bookyou.net",
  "expected_response_within_days": 14,
  "received_at": "string",
  "request_id": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/privacy/disclosure_request" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"identity_verification_method": "drivers_license", "requester_email": "user@example.com", "requester_legal_name": "string", "target_houjin_bangou": "string"}'
```

---

## Calendar

### `GET /v1/calendar/deadlines`

List upcoming submission deadlines.

Answers "what's due in the next 30 days for 東京 SMBs?" in one call so
callers don't stitch together N search_programs requests. Programs
without a structured end_date are silently excluded — they are not
"no deadline", they are "we couldn't extract one" and need case-by-case
lookup via get_program.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `within_days` | integer | no | Only return programs whose end_date falls between today and today + within_days (inclusive). Default 30. |
| `prefecture` | string | null | no | Prefecture filter. Canonical kanji ('東京都'), short ('東京'), romaji ('Tokyo'), or '全国' / 'national'. Nationwide programs and prefecture-unassigned rows are always included. |
| `authority_level` | string | null | no | Authority level filter. Canonical EN: national / prefecture / municipality / financial. Also accepts JP (国 / 都道府県 / 市区町村). |
| `tier` | string[] | null | no | Repeat to OR across tiers (e.g. tier=S&tier=A). |
| `limit` | integer | no | — |

**Response 200 (`DeadlinesResponse`):**

```json
{
  "as_of": "string",
  "results": [
    "..."
  ],
  "total": 0,
  "within_days": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/calendar/deadlines?within_days=30" \
  -H "X-API-Key: am_..."
```

---

## Case Studies

### `GET /v1/case-studies/search`

Search 採択事例 case studies.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `q` | string | null | no | Free-text search over company_name + case_title + case_summary + source_excerpt. Backed by FTS5 trigram (case_studies_fts) for queries of length >= 2; falls back to LIKE for single-char or 0-result short-ASCII queries. |
| `prefecture` | string | null | no | — |
| `industry_jsic` | string | null | no | JSIC industry code prefix (e.g. 'A' for 農林水産業, '05' for 食料品製造業). |
| `houjin_bangou` | string | null | no | 13-digit 法人番号 exact match. NOTE: only ~19% of case studies carry 法人番号 (427 / 2,286 rows) — most 採択 announcements publish 社名 only. Prefer `q=<company_name>` for substring search when the 法人番号 is unknown. |
| `program_used` | string | null | no | Match rows whose programs_used_json list contains this program name or unified_id substring. |
| `min_subsidy_yen` | integer | null | no | Lower bound on total_subsidy_received_yen (JPY). WARNING: only 4 / 2,286 rows (<1%) carry an amount — ministries publish 採択 without 交付額. Filtering here silently drops ~99% of matches. |
| `max_subsidy_yen` | integer | null | no | Upper bound on total_subsidy_received_yen (JPY). Same <1% sparsity as min_subsidy_yen — avoid unless the user explicitly asked for a ceiling. |
| `min_employees` | integer | null | no | — |
| `max_employees` | integer | null | no | — |
| `limit` | integer | no | — |
| `offset` | integer | no | — |

**Response 200 (`CaseStudySearchResponse`):**

```json
{
  "limit": 0,
  "offset": 0,
  "results": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/case-studies/search" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/case-studies/{case_id}`

Single case study lookup by `case_id`.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `case_id` | string | yes | — |

**Response 200 (`CaseStudy`):**

```json
{
  "capital_yen": 0,
  "case_id": "string",
  "case_summary": "string",
  "case_title": "string",
  "company_name": "string",
  "confidence": 0.0,
  "employees": 0,
  "fetched_at": "string",
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/case-studies/<case_id>" \
  -H "X-API-Key: am_..."
```

---

## Loan Programs

### `GET /v1/loan-programs/search`

Search loan programs with three-axis risk filters.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `q` | string | null | no | Free-text search over program_name + provider + target_conditions. |
| `provider` | string | null | no | — |
| `loan_type` | string | null | no | — |
| `collateral_required` | string | null | no | Risk axis 1 (物的担保). One of: required | not_required | negotiable | unknown. |
| `personal_guarantor_required` | string | null | no | Risk axis 2 (代表者/役員/家族保証). One of: required | not_required | negotiable | unknown. |
| `third_party_guarantor_required` | string | null | no | Risk axis 3 (第三者保証). One of: required | not_required | negotiable | unknown. |
| `min_amount_yen` | integer | null | no | — |
| `max_amount_yen` | integer | null | no | — |
| `max_interest_rate` | number | null | no | Upper bound on interest_rate_base_annual (e.g. 0.015 for 1.5%). |
| `min_loan_period_years` | integer | null | no | — |
| `limit` | integer | no | — |
| `offset` | integer | no | — |

**Response 200 (`LoanProgramSearchResponse`):**

```json
{
  "limit": 0,
  "offset": 0,
  "results": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/loan-programs/search" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/loan-programs/{loan_id}`

Get Loan Program

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `loan_id` | integer | yes | — |

**Response 200 (`LoanProgram`):**

```json
{
  "amount_max_yen": 0,
  "collateral_required": "required",
  "confidence": 0.0,
  "fetched_at": "string",
  "grace_period_years_max": 0,
  "id": 0,
  "interest_rate_base_annual": 0.0,
  "interest_rate_special_annual": 0.0,
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/loan-programs/<loan_id>" \
  -H "X-API-Key: am_..."
```

---

## Enforcement Cases

### `GET /v1/enforcement-cases/search`

Search enforcement cases for compliance / DD lookup.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `q` | string | null | no | Free-text search over program_name_hint + reason_excerpt + source_title (LIKE, case-insensitive). |
| `event_type` | string | null | no | — |
| `ministry` | string | null | no | — |
| `prefecture` | string | null | no | — |
| `legal_basis` | string | null | no | — |
| `program_name_hint` | string | null | no | — |
| `recipient_houjin_bangou` | string | null | no | 13-digit 法人番号 filter. NOTE: this column is 100% NULL across all 1,185 enforcement cases because 会計検査院 does not publish 法人番号. Filtering by this parameter will always return 0 rows. Use `q=<company_name>` or `q=<houjin_bangou_digits>` for substring search over source_title / reason_excerpt / program_name_hint instead. |
| `min_improper_grant_yen` | integer | null | no | — |
| `max_improper_grant_yen` | integer | null | no | — |
| `disclosed_from` | string | null | no | ISO date (YYYY-MM-DD) — inclusive lower bound on disclosed_date. |
| `disclosed_until` | string | null | no | ISO date (YYYY-MM-DD) — inclusive upper bound on disclosed_date. |
| `limit` | integer | no | — |
| `offset` | integer | no | — |

**Response 200 (`EnforcementCaseSearchResponse`):**

```json
{
  "limit": 0,
  "offset": 0,
  "results": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/enforcement-cases/search" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/enforcement-cases/{case_id}`

Get Enforcement Case

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `case_id` | string | yes | — |

**Response 200 (`EnforcementCase`):**

```json
{
  "amount_grant_paid_yen": 0,
  "amount_improper_grant_yen": 0,
  "amount_improper_project_cost_yen": 0,
  "amount_project_cost_yen": 0,
  "amount_yen": 0,
  "bureau": "string",
  "case_id": "string",
  "confidence": 0.0,
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/enforcement-cases/<case_id>" \
  -H "X-API-Key: am_..."
```

---

## Invoice Registrants

### `GET /v1/invoice_registrants/search`

Search 適格請求書発行事業者 by name / 法人番号 / location / status.

This endpoint is lookup-only. Bulk-style queries (empty q + empty
filters paging through the full table) work but return exactly one
page at a time; the PDL v1.0 attribution is repeated on every page to
keep 出典明記 + 編集・加工注記 visible across paginated reads.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `q` | string | null | no | Prefix match on 事業者名 (normalized_name). Index-eligible LIKE — not FTS. Short queries (< 2 chars) are rejected to keep the match selective. |
| `houjin_bangou` | string | null | no | Exact 13-digit 法人番号 filter. Returns only rows where houjin_bangou matches (sole-proprietor rows excluded). |
| `kind` | string | null | no | corporate = 法人 (registrant_kind='corporation'); individual = 個人事業主 (registrant_kind='sole_proprietor'). Omit to include both plus 'other'. |
| `prefecture` | string | null | no | Prefecture name. Canonical = full-suffix kanji ('東京都'); short form ('東京') and romaji also accepted. |
| `registered_after` | string | null | no | ISO date (YYYY-MM-DD) — inclusive lower bound on registered_date. |
| `registered_before` | string | null | no | ISO date (YYYY-MM-DD) — inclusive upper bound on registered_date. |
| `active_only` | boolean | no | When true (default), excludes revoked (revoked_date IS NOT NULL) and expired (expired_date IS NOT NULL) rows. Flip to false for historical/audit research. |
| `limit` | integer | no | Page size. Default 50, hard cap 100. No wildcard bulk export — point consumers at NTA's own download URL for full snapshots. |
| `offset` | integer | no | — |

**Response 200 (`jpintel_mcp__api__invoice_registrants__SearchResponse`):**

```json
{
  "attribution": {
    "edited": "...",
    "license": "...",
    "notice": "...",
    "source": "...",
    "source_url": "..."
  },
  "limit": 0,
  "offset": 0,
  "results": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/invoice_registrants/search" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/invoice_registrants/{invoice_registration_number}`

Exact lookup by 適格請求書発行事業者登録番号 ('T' + 13 digits).

On miss we do NOT raise a bare 404. The 4M-row 適格事業者 population
only lands in our mirror at the post-launch monthly bulk refresh, so
a launch-week miss frequently means "your T-number is real, we just
haven't ingested it yet" — not "this T-number is invalid". The
enriched 404 body distinguishes the two cases for the caller and
points them at NTA's authoritative lookup as the immediate fallback.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `invoice_registration_number` | string | yes | — |

**Response 200 (`GetResponse`):**

```json
{
  "attribution": {
    "edited": "...",
    "license": "...",
    "notice": "...",
    "source": "...",
    "source_url": "..."
  },
  "result": {
    "address_normalized": "...",
    "confidence": "...",
    "expired_date": "...",
    "fetched_at": "...",
    "houjin_bangou": "...",
    "invoice_registration_number": "...",
    "last_updated_nta": "...",
    "normalized_name": "...",
    "...": "..."
  }
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/invoice_registrants/<invoice_registration_number>" \
  -H "X-API-Key: am_..."
```

---

## Laws

### `GET /v1/laws/search`

Search laws (statutes, ordinances, ministerial rules).

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `q` | string | null | no | Free-text search across law_title + law_short_title + law_number + summary (FTS5 with quoted-phrase workaround for 2+ character kanji compounds). Terms shorter than 3 characters fall through to LIKE to dodge trigram zero-match. |
| `law_type` | string | null | no | Filter by law_type. One of: constitution | act | cabinet_order | imperial_order | ministerial_ordinance | rule | notice | guideline. |
| `ministry` | string | null | no | Filter by 所管府省 (exact match). |
| `currently_effective_only` | boolean | no | When true (default), only `revision_status='current'` rows are returned. Flip to false to include 'superseded' rows. |
| `include_repealed` | boolean | no | When false (default), `revision_status='repealed'` rows are excluded. Flip to true for historical research. |
| `promulgated_from` | string | null | no | ISO date (YYYY-MM-DD) — inclusive lower bound on promulgated_date. |
| `promulgated_to` | string | null | no | ISO date (YYYY-MM-DD) — inclusive upper bound on promulgated_date. |
| `enforced_from` | string | null | no | ISO date (YYYY-MM-DD) — inclusive lower bound on enforced_date. |
| `enforced_to` | string | null | no | ISO date (YYYY-MM-DD) — inclusive upper bound on enforced_date. |
| `limit` | integer | no | — |
| `offset` | integer | no | — |

**Response 200 (`LawSearchResponse`):**

```json
{
  "limit": 0,
  "offset": 0,
  "results": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/laws/search" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/laws/{unified_id}`

Return a single law including summary, article_count, and lineage.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `unified_id` | string | yes | — |

**Response 200 (`Law`):**

```json
{
  "article_count": 0,
  "confidence": 0.95,
  "enforced_date": "string",
  "fetched_at": "string",
  "full_text_url": "string",
  "last_amended_date": "string",
  "law_number": "string",
  "law_short_title": "string",
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/laws/<unified_id>" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/laws/{unified_id}/related-programs`

Reverse lookup: which programs cite this law via program_law_refs.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `unified_id` | string | yes | — |

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `ref_kind` | string | null | no | Filter by citation kind. One of: authority | eligibility | exclusion | reference | penalty. Omit to return all kinds. |
| `limit` | integer | no | — |
| `offset` | integer | no | — |

**Response 200 (`RelatedProgramsResponse`):**

```json
{
  "law_unified_id": "string",
  "limit": 0,
  "offset": 0,
  "results": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/laws/<unified_id>/related-programs" \
  -H "X-API-Key: am_..."
```

---

## Court Decisions

### `POST /v1/court-decisions/by-statute`

Return court decisions citing a given LAW-<10 hex> statute.

TRACE endpoint: resolves the statute→ruling edge via
`related_law_ids_json`. When `article_citation` is supplied, we
additionally require the article string to appear in `key_ruling` or
`source_excerpt` — the ingest does not yet write a structured
(law_id, article) map, so this is a honest contains-check, not a
false-precision exact join. Callers should treat `article_citation`
narrowing as best-effort.

**認証:** 任意 (未認証は匿名扱い)

**Request body (`CourtDecisionByStatuteRequest`):**

```json
{
  "article_citation": "string",
  "law_id": "string",
  "limit": 20,
  "offset": 0
}
```

**Response 200 (`CourtDecisionSearchResponse`):**

```json
{
  "limit": 0,
  "offset": 0,
  "results": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/court-decisions/by-statute" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"article_citation": "string", "law_id": "string", "limit": 20, "offset": 0}'
```

---

### `GET /v1/court-decisions/search`

Search court decisions (判決 / 決定 / 命令).

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `q` | string | null | no | Free-text search across case_name + subject_area + key_ruling + impact_on_business (FTS5 with quoted-phrase workaround for 2+ character kanji compounds). |
| `court` | string | null | no | Filter by 裁判所名 (exact match, e.g. '最高裁判所第三小法廷'). |
| `court_level` | string | null | no | Filter by court tier. One of: supreme | high | district | summary | family. |
| `decision_type` | string | null | no | Filter by decision shape. One of: 判決 | 決定 | 命令. |
| `subject_area` | string | null | no | Filter by 分野 (substring LIKE — the column is free-text and varies by 判例集, so exact-match is too brittle). |
| `references_law_id` | string | null | no | Filter rows whose `related_law_ids_json` contains this LAW-<10 hex> unified_id. JSON-array substring LIKE — accurate because unified_ids are fixed-width and have a distinctive `LAW-` prefix. |
| `decided_from` | string | null | no | ISO date (YYYY-MM-DD) — inclusive lower bound on decision_date. |
| `decided_to` | string | null | no | ISO date (YYYY-MM-DD) — inclusive upper bound on decision_date. |
| `limit` | integer | no | — |
| `offset` | integer | no | — |

**Response 200 (`CourtDecisionSearchResponse`):**

```json
{
  "limit": 0,
  "offset": 0,
  "results": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/court-decisions/search" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/court-decisions/{unified_id}`

Return a single court decision with full source lineage.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `unified_id` | string | yes | — |

**Response 200 (`CourtDecision`):**

```json
{
  "case_name": "string",
  "case_number": "string",
  "confidence": 0.9,
  "court": "string",
  "court_level": "supreme",
  "decision_date": "string",
  "decision_type": "判決",
  "fetched_at": "string",
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/court-decisions/<unified_id>" \
  -H "X-API-Key: am_..."
```

---

## Tax Rulesets

### `POST /v1/tax_rulesets/evaluate`

Evaluate one or more rulesets against a caller business_profile.

Walks `eligibility_conditions_json` for each selected row and returns
per-ruleset `applicable` + matched / unmatched predicate lists. Never
interprets tax law — pure JSON predicate matching.

target_ruleset_ids omitted -> evaluates all CURRENT rulesets
(effective_until IS NULL OR effective_until >= today). Use /search with
effective_on + explicit ids list to evaluate historical snapshots.

**認証:** 任意 (未認証は匿名扱い)

**Request body (`EvaluateRequest`):**

```json
{
  "business_profile": {},
  "target_ruleset_ids": [
    "..."
  ]
}
```

**Response 200 (`EvaluateResponse`):**

```json
{
  "results": [
    "..."
  ]
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/tax_rulesets/evaluate" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"business_profile": {}, "target_ruleset_ids": ["..."]}'
```

---

### `GET /v1/tax_rulesets/search`

Search 税務判定ルールセット (tax_rulesets).

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `q` | string | null | no | Free-text search across ruleset_name + eligibility_conditions + calculation_formula (FTS5 with quoted-phrase workaround for 2+ character kanji compounds). Terms shorter than 3 characters fall through to LIKE to dodge trigram zero-match. |
| `tax_category` | string | null | no | Filter by tax_category. One of: consumption | corporate | income | property | local | inheritance. |
| `ruleset_kind` | string | null | no | Filter by ruleset_kind. One of: registration | credit | deduction | special_depreciation | exemption | preservation | other. |
| `effective_on` | string | null | no | ISO 8601 date (YYYY-MM-DD). Returns only rulesets whose effective_from <= date AND (effective_until IS NULL OR effective_until >= date). Use this to ask 'which rules applied on date X?' — critical around cliff dates (2026-09-30 / 2027-09-30 / 2029-09-30). |
| `limit` | integer | no | — |
| `offset` | integer | no | — |

**Response 200 (`TaxRulesetSearchResponse`):**

```json
{
  "limit": 0,
  "offset": 0,
  "results": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/tax_rulesets/search" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/tax_rulesets/{unified_id}`

Return a single 税務判定ルールセット by TAX-<10hex> id.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `unified_id` | string | yes | — |

**Response 200 (`TaxRulesetOut`):**

```json
{
  "authority": "string",
  "authority_url": "string",
  "calculation_formula": "string",
  "confidence": 0.0,
  "effective_from": "string",
  "effective_until": "string",
  "eligibility_conditions": "string",
  "eligibility_conditions_json": null,
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/tax_rulesets/<unified_id>" \
  -H "X-API-Key: am_..."
```

---

## Bids

### `GET /v1/bids/search`

Search bids (入札案件). FTS match when `q` is given, else most recently
published first.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `q` | string | null | no | Free-text search across bid_title + bid_description + procuring_entity + winner_name (FTS5 with quoted-phrase workaround for 2+ character kanji compounds). Terms shorter than 3 characters will not match — trigram tokenizer limitation; use a longer phrase or the structured filters instead. |
| `bid_kind` | string | null | no | Filter by bid_kind. One of: open | selective | negotiated | kobo_subsidy. |
| `procuring_houjin_bangou` | string | null | no | Exact 13-digit 法人番号 of the procuring entity. |
| `winner_houjin_bangou` | string | null | no | Exact 13-digit 法人番号 of the落札者. |
| `program_id_hint` | string | null | no | Exact programs.unified_id (UNI-* / TAX-* / LAW-* etc.) — returns bids linked to that program via ingest matchers. |
| `min_amount` | integer | null | no | Inclusive lower bound on awarded_amount_yen (JPY). Rows with NULL awarded_amount_yen are excluded from the filtered set when this is set. |
| `max_amount` | integer | null | no | Inclusive upper bound on awarded_amount_yen (JPY). Rows with NULL awarded_amount_yen are excluded from the filtered set when this is set. |
| `deadline_after` | string | null | no | ISO date (YYYY-MM-DD) — inclusive lower bound on bid_deadline. Useful for 'still-open' queries. |
| `limit` | integer | no | — |
| `offset` | integer | no | — |

**Response 200 (`BidsSearchResponse`):**

```json
{
  "limit": 0,
  "offset": 0,
  "results": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/bids/search" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/bids/{unified_id}`

Return a single 入札案件 by BID-<10 hex> unified_id.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `unified_id` | string | yes | — |

**Response 200 (`BidOut`):**

```json
{
  "announcement_date": "string",
  "awarded_amount_yen": 0,
  "bid_deadline": "string",
  "bid_description": "string",
  "bid_kind": "open",
  "bid_title": "string",
  "budget_ceiling_yen": 0,
  "classification_code": "string",
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/bids/<unified_id>" \
  -H "X-API-Key: am_..."
```

---

## 税務会計AI: Programs (Active / Related / Stats / GX)

### `GET /v1/am/acceptance_stats`

採択率 / 採択事例 statistics from am_entities (supersedes cross-DB acceptance_stats_tool).

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `program_name` | string | null | no | — |
| `year` | integer | null | no | — |
| `region` | string | null | no | — |
| `industry` | string | null | no | — |
| `limit` | integer | no | — |
| `offset` | integer | no | — |

**Response 200 (`AMSearchResponse`):**

```json
{
  "error": {},
  "limit": 0,
  "meta": {},
  "offset": 0,
  "results": [
    {}
  ],
  "retrieval_note": "string",
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/acceptance_stats" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/active_at`

Point-in-time snapshot: programs whose effective window covered a given date.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `date` | string | yes | ISO YYYY-MM-DD |
| `region` | string | null | no | — |
| `industry` | string | null | no | — |
| `size` | string | null | no | — |
| `limit` | integer | no | — |

**Response 200 (`AMActiveAtResponse`):**

```json
{
  "error": {},
  "limit": 0,
  "meta": {},
  "offset": 0,
  "pivot_date": "string",
  "results": [
    {}
  ],
  "retrieval_note": "string",
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/active_at" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/gx_programs`

GX / 脱炭素 / 再エネ / EV / ZEB-ZEH curated 補助金 programs.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `theme` | string | no | — |
| `company_size` | string | null | no | — |
| `region` | string | null | no | — |
| `limit` | integer | no | — |

**Response 200 (`AMSimpleSearchResponse`):**

```json
{
  "error": {},
  "results": [
    {}
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/gx_programs?theme=ghg_reduction" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/open_programs`

Currently-open (公募中) program rounds on a target date.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `on_date` | string | null | no | ISO YYYY-MM-DD. Default = today. |
| `region` | string | null | no | — |
| `industry` | string | null | no | — |
| `size` | string | null | no | — |
| `natural_query` | string | null | no | — |
| `limit` | integer | no | — |

**Response 200 (`AMOpenProgramsResponse`):**

```json
{
  "error": {},
  "limit": 0,
  "meta": {},
  "offset": 0,
  "pivot_date": "string",
  "results": [
    {}
  ],
  "retrieval_note": "string",
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/open_programs" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/programs/active_v2`

Three-axis active-at: effective window + application_open + application_close in one query.

Backed by view `programs_active_at_v2`. Returns programs that:
  - are effective on `as_of` (effective_from <= as_of < effective_until,
    with `effective_from_source` provenance hint), AND
  - have an application round whose open_date <= `application_open_by`
    (when provided), AND
  - have an application round whose close_date >= `application_close_by`
    (when provided), AND
  - match `prefecture` (when provided).

Caveat: `am_amendment_snapshot` (14,596 行) は schema-level snapshot で、
82.3% の行は historical diff hash が空。 `eligibility_hash` も全 (v1, v2)
ペアで uniform。 つまり改正の日付別追跡 (per-version eligibility drift) には
利用できない。 `effective_from` / `effective_until` が NULL でない 144 行のみ
時間軸として確定済み。 response には `_lifecycle_caveat` (structured dict —
`{"data_quality": "partial", "rows_with_complete_temporal_data": 144,
"total_rows": 14596, "note": "..."}`) が必ず添付されるので、caller はそれを
参照して time-series として誤読しないこと。同じ caveat は `/v1/am/by_law` /
`/v1/am/law_article` の amendment-touching response にも添付される。

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `as_of` | string | null | no | ISO YYYY-MM-DD. effective window pivot. Defaults to today (JST date as ISO). |
| `application_open_by` | string | null | no | Filter to rounds whose application_open_date <= this date. |
| `application_close_by` | string | null | no | Filter to rounds whose application_close_date >= this date (締切がこの日以降). |
| `prefecture` | string | null | no | Optional prefecture filter (e.g. '東京都'). |
| `limit` | integer | no | — |

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/programs/active_v2" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/related/{program_id}`

Graph walk over am_relation (prerequisite / compatible / incompatible / replaces / amends / related / references_law etc.).

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `program_id` | string | yes | — |

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `relation_types` | string[] | null | no | Filter edge types (prerequisite / compatible / incompatible / replaces / …). |
| `depth` | integer | no | — |
| `max_edges` | integer | no | — |

**Response 200 (`AMRelatedResponse`):**

```json
{
  "depth": 1,
  "error": {},
  "hint": "string",
  "nodes": [
    {}
  ],
  "relations": [
    {}
  ],
  "retry_with": {},
  "seed_id": "string",
  "seed_kind": "string",
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/related/<program_id>?relation_types=['string']" \
  -H "X-API-Key: am_..."
```

---

## 税務会計AI: Intent / Reason / Enums

### `GET /v1/am/enums/{enum_name}`

List canonical enum values + frequency for a given enum_name.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `enum_name` | string | yes | — |

**Response 200 (`AMEnumValuesResponse`):**

```json
{
  "description": "string",
  "enum_name": "string",
  "error": {},
  "frequency_map": {},
  "last_updated": "string",
  "values": [
    "string"
  ]
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/enums/<enum_name>" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/intent`

Route a natural-language query to the best-fit tool + extracted slots (query_rewrite layer).

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `query` | string | yes | — |

**Response 200 (`AMIntentResponse`):**

```json
{
  "all_scores": [
    {}
  ],
  "confidence": 0.0,
  "error": {},
  "intent_id": "string",
  "intent_name_ja": "string",
  "sample_queries": [
    "string"
  ]
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/intent" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/reason`

Return a citation-backed narrative answer (source_url + snippet per claim).

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `query` | string | yes | — |
| `persona` | string | null | no | — |

**Response 200 (`AMReasonResponse`):**

```json
{
  "answer_skeleton": "string",
  "confidence": 0.0,
  "db_bind_notes": [
    "..."
  ],
  "db_bind_ok": true,
  "error": {},
  "filters_extracted": {},
  "intent": "string",
  "intent_name_ja": "string",
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/reason" \
  -H "X-API-Key: am_..."
```

---

## 税務会計AI: Tax Incentives & Certifications

### `GET /v1/am/certifications`

認定・認証制度 (健康経営 / えるぼし / くるみん / SDGs / 経営革新 等) search.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `query` | string | null | no | — |
| `authority` | string | null | no | — |
| `size` | string | null | no | — |
| `industry` | string | null | no | — |
| `limit` | integer | no | — |
| `offset` | integer | no | — |

**Response 200 (`AMSearchResponse`):**

```json
{
  "error": {},
  "limit": 0,
  "meta": {},
  "offset": 0,
  "results": [
    {}
  ],
  "retrieval_note": "string",
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/certifications" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/tax_incentives`

税制特例 (特別償却 / 税額控除 / 繰越欠損金 / 非課税措置) search across ~285 rows.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `query` | string | null | no | — |
| `authority` | string | null | no | — |
| `industry` | string | null | no | — |
| `target_year` | integer | null | no | — |
| `target_entity` | string | null | no | — |
| `natural_query` | string | null | no | — |
| `limit` | integer | no | — |
| `offset` | integer | no | — |

**Response 200 (`AMSearchResponse`):**

```json
{
  "error": {},
  "limit": 0,
  "meta": {},
  "offset": 0,
  "results": [
    {}
  ],
  "retrieval_note": "string",
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/tax_incentives" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/tax_rule`

Single tax measure lookup against am_tax_rule with root_law + rate + applicability window.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `measure_name_or_id` | string | yes | — |
| `rule_type` | string | null | no | — |
| `as_of` | string | null | no | ISO YYYY-MM-DD (default today) |

**Response 200 (`AMTaxRuleResponse`):**

```json
{
  "error": {},
  "results": [
    {}
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/tax_rule" \
  -H "X-API-Key: am_..."
```

---

## 税務会計AI: Loans & Mutual Insurance

### `GET /v1/am/loans`

am_loan_product query — 公庫 / 商工中金 / 自治体制度融資 with 3-axis guarantor filter.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `loan_kind` | string | null | no | — |
| `no_collateral` | boolean | no | — |
| `no_personal_guarantor` | boolean | no | — |
| `no_third_party_guarantor` | boolean | no | — |
| `max_amount_yen` | integer | null | no | — |
| `min_amount_yen` | integer | null | no | — |
| `lender_entity_id` | string | null | no | — |
| `name_query` | string | null | no | — |
| `limit` | integer | no | — |

**Response 200 (`AMLoanSearchResponse`):**

```json
{
  "error": {},
  "limit": 10,
  "offset": 0,
  "result_count": 0,
  "results": [
    {}
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/loans?loan_kind=ippan" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/mutual_plans`

共済 / 年金 / 労災 cross-search (小規模企業共済 / iDeCo+ / DB / DC / 労災特別加入).

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `plan_kind` | string | null | no | — |
| `premium_monthly_yen` | integer | null | no | — |
| `tax_deduction_type` | string | null | no | — |
| `provider_entity_id` | string | null | no | — |
| `name_query` | string | null | no | — |
| `limit` | integer | no | — |

**Response 200 (`AMLoanSearchResponse`):**

```json
{
  "error": {},
  "limit": 10,
  "offset": 0,
  "result_count": 0,
  "results": [
    {}
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/mutual_plans?plan_kind=retirement_mutual" \
  -H "X-API-Key: am_..."
```

---

## 税務会計AI: Laws & Enforcement

### `GET /v1/am/by_law`

Programs / tax rules / certifications linked to a specific law (fuzzy name match).

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `law_name` | string | yes | — |
| `article` | string | null | no | — |
| `amendment_date` | string | null | no | — |
| `limit` | integer | no | — |
| `offset` | integer | no | — |

**Response 200 (`AMByLawResponse`):**

```json
{
  "error": {},
  "law_aliases_tried": [
    "string"
  ],
  "limit": 0,
  "meta": {},
  "offset": 0,
  "results": [
    {}
  ],
  "retrieval_note": "string",
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/by_law" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/enforcement`

Is this entity currently barred from 補助金 / 助成金 (行政処分 排除期間 check)?

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `houjin_bangou` | string | null | no | — |
| `target_name` | string | null | no | — |
| `as_of_date` | string | no | — |

**Response 200 (`AMEnforcementCheckResponse`):**

```json
{
  "active_exclusions": [
    {}
  ],
  "all_count": 0,
  "currently_excluded": false,
  "error": {},
  "found": false,
  "queried": {},
  "recent_history": [
    {}
  ]
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/enforcement" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/law_article`

Exact 条文 lookup: '租税特別措置法' + '41の19' → full article text + amendment history.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `law_name_or_canonical_id` | string | yes | — |
| `article_number` | string | yes | — |

**Response 200 (`AMLawArticleResponse`):**

```json
{
  "article_id": "string",
  "article_number": "string",
  "article_number_sort": 0,
  "effective_from": "string",
  "effective_until": "string",
  "error": {},
  "found": false,
  "last_amended": "string",
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/law_article" \
  -H "X-API-Key: am_..."
```

---

## 税務会計AI: Annotations / Validation / Provenance

### `GET /v1/am/annotations/{entity_id}`

am_entity_annotation 逆引き — examiner feedback / quality score / ML 推論 等を 1 コール (16,474 行).

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `entity_id` | string | yes | am_entities.canonical_id (TEXT) |

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `kinds` | string[] | null | no | Filter on annotation kind (examiner_warning / examiner_correction / quality_score / validation_failure / ml_inference / manual_note). Repeat the param to OR-combine. |
| `include_internal` | boolean | no | Include visibility='internal' rows (default False = public only). 'private' is never returned. |
| `include_superseded` | boolean | no | Include superseded / expired annotations (default False = currently-live only). |
| `limit` | integer | no | — |

**Response 200 (`AMAnnotationsResponse`):**

```json
{
  "entity_id": "string",
  "error": {},
  "filters": {},
  "limit": 0,
  "meta": {},
  "offset": 0,
  "results": [
    {}
  ],
  "retrieval_note": "string",
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/annotations/<entity_id>?kinds=['string']" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/provenance/fact/{fact_id}`

am_entity_facts.source_id → am_source 1 件 (NULL なら entity-level am_entity_source の候補 list に fallback).

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `fact_id` | integer | yes | am_entity_facts.id (INTEGER PK) |

**Response 200 (`AMProvenanceResponse`):**

```json
{
  "error": {},
  "limit": 0,
  "meta": {},
  "offset": 0,
  "results": [
    {}
  ],
  "retrieval_note": "string",
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/provenance/fact/<fact_id>" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/provenance/{entity_id}`

am_entity_source × am_source 一括返却 — 出典 URL / license / role / fetched_at + license_summary を 1 コール (migration 049, 99.17% license filled).

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `entity_id` | string | yes | am_entities.canonical_id (TEXT) |

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `include_facts` | boolean | no | If True, also return per-fact provenance via am_entity_facts.source_id (NULL on legacy rows pre-2026-04-25 — those facts are skipped). Default False = entity-level sources only. |
| `fact_limit` | integer | no | Max facts when include_facts=True (default 200). |

**Response 200 (`AMProvenanceResponse`):**

```json
{
  "error": {},
  "limit": 0,
  "meta": {},
  "offset": 0,
  "results": [
    {}
  ],
  "retrieval_note": "string",
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/provenance/<entity_id>?include_facts=false" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/am/validate`

汎用 intake 検証 — am_validation_rule の active 述語を applicant_data に対して評価し
rule 単位の passed/failed/deferred を返す (deferred = jpintel 内で評価できない外部依存述語).

**認証:** 任意 (未認証は匿名扱い)

**Request body (`Body_rest_validate_v1_am_validate_post`):**

```json
{
  "applicant_data": {},
  "entity_id": "string",
  "scope": "intake"
}
```

**Response 200 (`AMValidateResponse`):**

```json
{
  "applicant_hash": "string",
  "entity_id": "string",
  "error": {},
  "results": [
    {}
  ],
  "scope": "intake",
  "summary": {},
  "total": 0
}
```

**Example:**

```bash
curl -X POST "https://api.zeimu-kaikei.ai/v1/am/validate" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"applicant_data": {}, "entity_id": "string", "scope": "intake"}'
```

---

## 税務会計AI: Static Resources & Example Profiles

### `GET /v1/am/example_profiles`

List 5 canonical client-intake example payloads (PII-clean).

**認証:** 任意 (未認証は匿名扱い)

**Response 200 (`ExampleProfileList`):**

```json
{
  "results": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/example_profiles" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/example_profiles/{profile_id}`

Return one canonical client profile JSON as a complete-payload example.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `profile_id` | string | yes | Profile id; see /v1/am/example_profiles. |

**Response 200 (`ExampleProfileDetail`):**

```json
{
  "id": "string",
  "profile": {}
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/example_profiles/<profile_id>" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/static`

List 8 curated 税務会計AI taxonomies (seido / glossary / money_types / obligations / dealbreakers / sector_combos / crop_library / exclusion_rules).

**認証:** 任意 (未認証は匿名扱い)

**Response 200 (`StaticResourceList`):**

```json
{
  "results": [
    "..."
  ],
  "total": 0
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/static" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/static/{resource_id}`

Load one taxonomy/lookup file. Returns full JSON content + license.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `resource_id` | string | yes | Resource id; see /v1/am/static for the catalog. |

**Response 200 (`StaticResourceDetail`):**

```json
{
  "content": {},
  "id": "string",
  "license": "string"
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/static/<resource_id>" \
  -H "X-API-Key: am_..."
```

---

## 税務会計AI: Health

### `GET /v1/am/health/deep`

10-check aggregate health (db + freshness + license + provenance + bundle + WAL).

Unbilled, unlogged, no anonymous-IP rate limit — heartbeat surface for
uptime monitors. Returns ``status`` ∈ {ok, degraded, unhealthy}.

Responses are cached for 30 seconds; pass ``?force=true`` to bypass for
debugging or post-deploy verification.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `force` | boolean | no | — |

**Response 200 (`DeepHealthResponse`):**

```json
{
  "checks": {},
  "generated_at": "string",
  "status": "string"
}
```

**Example:**

```bash
curl -X GET "https://api.zeimu-kaikei.ai/v1/am/health/deep?force=false" \
  -H "X-API-Key: am_..."
```

---

## Admin (internal)

運営者向けの funnel / cohort / error endpoint 群 (`/v1/admin/*`) は**非公開**。別 key (`ADMIN_API_KEY`) で認証し、OpenAPI export (`docs/openapi/v1.json`, SDK 生成) には含めない (`include_in_schema=False`)。SLA / versioning policy の対象外で、`/v1/*` 安定契約の一部では**ない**。

仕様: 内部 `docs/_internal/admin_api.md` 参照 (non-public、repo-only)。

---

## Gated endpoints (off by default)

下記は **default では mount されないか、OpenAPI から除外** される endpoint。launch gate / preview flag が立っているサーバーでのみ叩ける。`/v1/*` 安定契約の一部では**ない** (preview は contract 公開、saburoku は legal review pending)。

### `GET /v1/am/templates/saburoku_kyotei/metadata` *(gated)*

36協定 template の必須フィールド・alias・authority・license metadata を返す。

- **Gate**: `AUTONOMATH_36_KYOTEI_ENABLED=true` (default `false`)
- **Disabled**: HTTP 503 (`{"error": "feature_disabled"}`)
- **Response**: `template_id`, `obligation`, `authority`, `license`, `quality_grade`, `method`, `uses_llm`, `required_fields[]`, `_disclaimer`
- **Detail**: `docs/_internal/saburoku_kyotei_gate_decision_2026-04-25.md` 参照

### `POST /v1/am/templates/saburoku_kyotei` *(gated)*

36協定 (時間外労働・休日労働協定届) を deterministic substitution で render する。LLM は使わない。

- **Gate**: 同上
- **Body**: `dict[str, Any]` — canonical / Japanese alias の必須フィールド map (`/metadata` で取得)
- **Disabled**: HTTP 503 / **Missing required**: HTTP 422 / **OK**: `rendered_text` + meta + `_disclaimer`
- **注意**: 出力は **draft** であり、社労士確認が必須 (`_disclaimer` 強制同梱)。

---

## Preview / roadmap endpoints (off by default)

下記は **`enable_preview_endpoints=true` (env: `ENABLE_PREVIEW_ENDPOINTS`)** でのみ mount される future-contract surface。実装前に SDK generator / partner が future shape を確認できるよう、**HTTP 501 + `{"detail": "endpoint under development", "eta": "<date>"}`** を返す scaffold。OpenAPI に含めるには `scripts/export_openapi.py --include-preview` を使う。

### `GET /v1/legal/items` *(preview)*

法令条文の canonical lookup (将来 shape)。

- **Query**: `law` (法令名 / 必須), `article` (条文番号 / 必須), `subject` (任意 filter)
- **Response (future `LegalItemResponse`)**: `law_name`, `law_number`, `article_number`, `article_text`, `revision_date`, `source_url`, `fetched_at`
- **Status**: 現状 501 (target W6, ETA 2026-05-27)

### `POST /v1/accounting/invoice-validate` *(preview)*

適格請求書発行事業者登録番号 (T + 13桁) の validation (将来 shape)。

- **Body**: `{"invoice_number": "T1234567890123"}`
- **Response (future `InvoiceValidateResponse`)**: `invoice_number`, `is_registered`, `registration_date`, `company_name`, `company_kana`, `address`, `last_synced`
- **Status**: 現状 501 (target W7, ETA 2026-06-10)
- **Note**: 実装後は `/v1/invoice_registrants/{invoice_registration_number}` (live) と統合予定。

---

## 関連

- [mcp-tools.md](./mcp-tools.md) — 同じ機能を MCP tool として叩く
- [exclusions.md](./exclusions.md) — 排他ルールの概念
- [pricing.md](./pricing.md) — tier 別制限
- `docs/_internal/admin_api.md` — 内部用 admin endpoint (non-public、repo-only)
- [サンプル集](./examples.md) — 8 本の runnable サンプル (Python 4 + TypeScript 4, 各ファイル 50-150 行)
