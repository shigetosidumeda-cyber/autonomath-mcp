<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "APIReference",
  "headline": "jpcite REST API Reference (178 endpoints)",
  "description": "jpcite REST API の全 178 endpoint 仕様。programs / exclusions / meta / billing / dashboard / laws / loans / court-decisions / bids / 行政処分 / 採択事例 / invoice 適格事業者 / tax_rulesets / V1+メタデータ+静的データセット 拡張を含む。",
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
    "@id": "https://jpcite.com/docs/api-reference/"
  }
}
</script>

# API Reference

REST API 全 178 endpoint。programs / exclusions / meta / billing / dashboard / 各種データセット (laws / loans / court_decisions / bids / 行政処分 / 採択事例 / invoice / tax_rulesets) / agent・MCP 向け endpoint を含む。

## ベース URL

```
https://api.jpcite.com
```

## 目次 (Endpoint catalogue)

全 178 endpoint。OpenAPI spec (`docs/openapi/v1.json`) と完全一致。★ = 本ページに詳細あり、それ以外は OpenAPI から自動展開した最小ドキュメント (本ページ後半に展開済み)。

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
- **jpcite: Programs (Active / Related / Stats / GX)** (6)
  - `GET /v1/am/acceptance_stats`
  - `GET /v1/am/active_at`
  - `GET /v1/am/gx_programs`
  - `GET /v1/am/open_programs`
  - `GET /v1/am/programs/active_v2`
  - `GET /v1/am/related/{program_id}`
- **jpcite: Intent / Reason / Enums** (3)
  - `GET /v1/am/enums/{enum_name}`
  - `GET /v1/am/intent`
  - `GET /v1/am/reason`
- **jpcite: Tax Incentives & Certifications** (3)
  - `GET /v1/am/certifications`
  - `GET /v1/am/tax_incentives`
  - `GET /v1/am/tax_rule`
- **jpcite: Loans & Mutual Insurance** (2)
  - `GET /v1/am/loans`
  - `GET /v1/am/mutual_plans`
- **jpcite: Laws & Enforcement** (3)
  - `GET /v1/am/by_law`
  - `GET /v1/am/enforcement`
  - `GET /v1/am/law_article`
- **jpcite: Annotations / Validation / Provenance** (4)
  - `GET /v1/am/annotations/{entity_id}`
  - `GET /v1/am/provenance/fact/{fact_id}`
  - `GET /v1/am/provenance/{entity_id}`
  - `POST /v1/am/validate`
- **jpcite: Static Resources & Example Profiles** (4)
  - `GET /v1/am/example_profiles`
  - `GET /v1/am/example_profiles/{profile_id}`
  - `GET /v1/am/static`
  - `GET /v1/am/static/{resource_id}`
- **jpcite: Health** (1)
  - `GET /v1/am/health/deep`
- **Evidence & Source Manifests** (3)
  - `POST /v1/evidence/packets/query` ★
  - `GET /v1/evidence/packets/{subject_kind}/{subject_id}` ★
  - `GET /v1/source_manifest/{program_id}` ★


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

- **`GET /v1/openapi.json`** — live server が返す公開仕様
- **`GET /openapi.json`** — `/v1/openapi.json` へ **`308 Permanent Redirect`**。SDK 生成 client の旧 path からの移行期間のみの互換 alias
- **`docs/openapi/v1.json`** — repo に committed された snapshot (CI で `scripts/export_openapi.py` が regenerate)

admin 系 (`/v1/admin/*`) は `include_in_schema=False` で除外。preview 系 (`/v1/legal/*`, `/v1/accounting/*`, `/v1/calendar/*`) は default export には入らず、`scripts/export_openapi.py --include-preview` で roadmap 込みの spec を別途生成できる。

## Evidence Packet / Source Manifest

AI クライアントで回答文を作る前に、根拠だけを先に集めるための endpoint。jpcite は回答文を生成せず、出典 URL、取得時刻、content hash、provenance、互換性ルール判定、既知の欠落を構造化して返す。

| Endpoint | 用途 |
|---|---|
| `POST /v1/evidence/packets/query` | 複数レコードを検索条件からまとめ、AI に渡しやすい evidence packet を作る |
| `GET /v1/evidence/packets/{subject_kind}/{subject_id}` | `program` / `houjin` など単一対象の evidence packet を取得する |
| `GET /v1/source_manifest/{program_id}` | 制度単位の source chain、license、取得日時、検証状態を確認する |

レスポンスは `packet_id`、`corpus_snapshot_id`、`generated_at`、`records[]`、`source_url`、`source_fetched_at`、`source_checksum`、`license`、`quality.known_gaps[]` を含む。`quality.known_gaps[]` が空でない場合は、AI の回答側でも「どの根拠が未接続か」を明示すること。

トークン量・外部 LLM API 料金・追加検索回数への影響は workload-dependent。jpcite の課金対象は billable API/MCP call であり、外部 LLM 側の token / search / cache / tool cost は利用者のモデル設定に依存する。

## 認証

API key は次のいずれかで送る:

```
X-API-Key: am_xxxxxxxxxxxxxxxx
Authorization: Bearer am_xxxxxxxxxxxxxxxx
```

API key 不在は匿名扱い、無効 key は `401 Unauthorized`。

## Rate limit

| 区分 | 上限 |
|------|---|
| 匿名 (key 無し) | 3 req/日 per IP (IPv4 /32 / IPv6 /64)、JST 翌日 00:00 リセット |
| 認証済み (Paid) | ¥3/req metered (税込 ¥3.30)。予算上限や保護レート制限が適用される場合があります |

**¥3/req の対価 (コスト削減保証ではなく、データ統合の対価):** ¥3/req は LLM token 削減効果を保証するものではありません。token 使用量への影響は workload-dependent です。実際の対価は次の 3 点:

- **Cross-source data integration**: 1 request can combine relevant public-program, case-study, loan, enforcement, law, tax, bid, and invoice-registrant datasets with source URLs and freshness metadata. Caller 側で同等を組み立てる場合の取得・正規化・整合性検証を肩代わりする
- **Primary source citation**: 99%+ の rows に 一次資料 (官公庁 / 政策金融公庫 等) の `source_url` を付与。aggregator 経由のデータは `source_url` に登録しない
- **Freshness metadata**: median 7 日以内の `source_fetched_at`。`/v1/meta/freshness` で per-source の鮮度分布を公開

匿名 IP 制限は discoverability 系 (`/meta`, `/v1/ping`, `/v1/programs/*`, `/v1/exclusions/*`, `/v1/feedback`) にのみ適用。`/healthz`, `/v1/billing/webhook`, `/v1/subscribers/unsubscribe`, dashboard 系 (`/v1/me/*`, `/v1/session`) はカウントしない。

匿名超過時:

```
HTTP/1.1 429 Too Many Requests
Retry-After: <翌日 JST 00:00 までの秒>

{"detail": "anon rate limit exceeded", "limit": 3, "resets_at": "2026-05-02T00:00:00+09:00"}
```

IP は raw 保存せず `HMAC-SHA256(ip, api_key_salt)` で hash 化。詳細は [pricing.md](./pricing.md)。

---

## Programs

### `GET /v1/programs/search`

自由記述 + 構造化フィルタで制度を検索。

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `q` | string | no | 自由記述検索。日本語の表記ゆれを正規化し、短い語句は補助的な一致方式で検索 |
| `tier` | string (repeat) | no | `S` / `A` / `B` / `C` / `X`。複数指定で OR |
| `prefecture` | string | no | 都道府県名 (完全一致, 例: `青森県`) |
| `authority_level` | string | no | 標準値: `national` / `prefecture` / `municipality` / `financial`。日本語別名 (`国` / `都道府県` / `市区町村` / `公庫`) も API 側で正規化して受け付ける |
| `funding_purpose` | string (repeat) | no | 資金用途 (例: `設備投資`) |
| `target_type` | string (repeat) | no | 対象者種別 (例: `認定新規就農者`) |
| `amount_min` | number | no | 助成上限の下限 (万円) |
| `amount_max` | number | no | 助成上限の上限 (万円) |
| `include_excluded` | bool | no | `true` で検索対象外の制度も含める (default `false`) |
| `limit` | int | no | 1〜100 (default 20) |
| `offset` | int | no | ページング (default 0) |
| `fields` | enum | no | `minimal` / `default` / `full`。レスポンスサイズ切替 (default `default`) |

**`fields` 選択肢:**

| 値 | `results[]` の中身 | 目安サイズ (1 record) | 用途 |
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
      "unified_id": "UNI-UNI-71f6029070",
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

**Response example at `fields=full`:** `default` と同じ `results[i]` に加え、各 record に `enriched` (A-J 次元) / `source_mentions` (list of `{url, fetched_at}`) / `source_url` / `source_fetched_at` / `source_checksum` が必ず入る (値が null でもキーは存在)。

**Example:**

```bash
# default shape
curl -H "X-API-Key: am_..." \
  "https://api.jpcite.com/v1/programs/search?q=IT導入&tier=S&tier=A&limit=5"

# minimal — list rendering / quick filter
curl -H "X-API-Key: am_..." \
  "https://api.jpcite.com/v1/programs/search?q=IT導入&limit=20&fields=minimal"
```

**ソート:** 自由記述検索では関連度順、それ以外は出典確認状況と制度名で安定ソート。

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
  "https://api.jpcite.com/v1/programs/UNI-71f6029070"

# minimal — just the headline fields
curl -H "X-API-Key: am_..." \
  "https://api.jpcite.com/v1/programs/UNI-71f6029070?fields=minimal"

# full — enriched / source_mentions / lineage keys included in the documented response shape
curl -H "X-API-Key: am_..." \
  "https://api.jpcite.com/v1/programs/UNI-71f6029070?fields=full"
```

**エラー:** 存在しない ID は `404 Not Found`。

---

### `POST /v1/programs/batch`

最大 50 件の `unified_id` をまとめて解決する。`GET /v1/programs/{unified_id}` を N 回叩く代わりに 1 リクエストで済ませる用途 (agent が `search_programs` の 20 件候補を全件 enrich したい等)。

**認証:** 任意 (未認証は匿名扱い)

**Request body (`BatchGetProgramsRequest`):**

```json
{"unified_ids": ["UNI-UNI-71f6029070", "UNI-71f6029070", "UNI-test-a-1"]}
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
      "unified_id": "UNI-UNI-71f6029070",
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

**Billing / cap:** batch は ID 件数分を billable units として扱う。実行前に月次 cap を projected units で検査し、cap 超過が見込まれる場合は処理前に 503 で止める。

**Example:**

```bash
curl -X POST https://api.jpcite.com/v1/programs/batch \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"unified_ids":["UNI-UNI-71f6029070","UNI-71f6029070"]}'
```

```python
# SDK パターン: search -> batch で 20 件 enrich
import httpx

with httpx.Client(
    base_url="https://api.jpcite.com",
    headers={"X-API-Key": "am_..."},
) as client:
    search = client.get(
        "/v1/programs/search",
        params={"q": "IT導入", "fields": "minimal", "limit": 20},
    ).json()
    ids = [item["unified_id"] for item in search["results"]]
    detail = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ids},
    ).json()
    for item in detail["results"]:
        print(item["unified_id"], item["primary_name"], item.get("enriched"))
    if detail["not_found"]:
        print("missing:", detail["not_found"])
```

---

## Exclusions

制度の併用チェック関連。概念は [exclusions.md](./exclusions.md)。

### `GET /v1/exclusions/rules`

登録済みの併用チェックルールを返す。

> **注意:** 登録済みルールに一致しない場合でも、「併用して安全」を保証するものではありません。実申請前に `source_urls` の一次資料、担当窓口、専門家を確認してください。

**認証:** 任意

**Response (`list[ExclusionRule]`):**

```json
[
  {
    "rule_id": "RULE-EXAMPLE-001",
    "kind": "same_asset_exclusive",
    "severity": "warning",
    "program_a": "UNI-1111111111",
    "program_b": "UNI-2222222222",
    "program_b_group": [],
    "description": "同じ設備費を二つの制度で重ねて申請できない可能性があります。",
    "source_notes": "公募要領の併給制限",
    "source_urls": ["<公式公募要領URL>"],
    "extra": {}
  }
]
```

**フィールド:**

| field | type | description |
|-------|------|-------------|
| `rule_id` | string | ルール一意 ID |
| `kind` | string | 論点の種類。例: 同時利用不可、前提条件、同一経費の重複、金額調整 |
| `severity` | string \| null | 確認の強さ。例: 重大、警告、要確認 |
| `program_a` | string \| null | 片側の制度 ID |
| `program_b` | string \| null | もう片側の制度 ID (または group を使用) |
| `program_b_group` | string[] | 複数制度が相手の場合のグループ |
| `description` | string \| null | ユーザー向けの要約 |
| `source_notes` | string \| null | 出典の簡易メモ |
| `source_urls` | string[] | 一次資料 URL |
| `extra` | object | 追加メタ |

---

### `POST /v1/exclusions/check`

候補制度セットに対して、併用時に確認すべき論点があるかを調べる。

**認証:** 任意

**Request body (`ExclusionCheckRequest`):**

```json
{
  "program_ids": ["UNI-1111111111", "UNI-2222222222"]
}
```

| field | type | required | description |
|-------|------|----------|-------------|
| `program_ids` | string[] | yes (1 件以上) | `search_programs` や `get_program` で得た制度 ID 配列。重複は自動 dedup |

**Response (`ExclusionCheckResponse`):**

```json
{
  "program_ids": ["UNI-1111111111", "UNI-2222222222"],
  "hits": [
    {
      "rule_id": "RULE-EXAMPLE-001",
      "kind": "same_asset_exclusive",
      "severity": "warning",
      "programs_involved": ["UNI-1111111111", "UNI-2222222222"],
      "description": "同じ設備費を二つの制度で重ねて申請できない可能性があります。",
      "source_urls": ["<公式公募要領URL>"]
    }
  ],
  "checked_rules": 181
}
```

**判定ロジック:**

- 併用不可や同一経費の重複は、関係する制度が候補セットに含まれると `hits` に出ます。
- 前提条件は、候補制度に必要な認定・資格・関連制度があり得る場合に `hits` に出ます。

> **限界 (重要):** `hits: []` は「登録済みルールでは衝突未検出」という意味です。「併用して安全」を意味しません。

**エラー:** `program_ids` が空なら `400 Bad Request`。

**Example:**

```bash
curl -X POST -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"program_ids":["UNI-1111111111","UNI-2222222222"]}' \
  https://api.jpcite.com/v1/exclusions/check
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

- `total_programs` は `programs` 全件 (tier S/A/B/C 11,684 + 検索対象外 2,788 = 14,472)
- `tier_counts` は tier 別件数。**検索対象外の制度は search では常に除外**
- `prefecture_counts` の `_none` は prefecture=null (全国制度または未ラベル) のバケット
- `exclusion_rules_count` は登録済みの併用チェックルール数
- `last_ingested_at` は DB の最終 ingest 時刻, `data_as_of` は元データの基準日
- `data_lineage.last_fetched_at` は `programs.source_fetched_at` の最大値、`unique_checksums` は `source_checksum` のユニーク数 (列が存在する時のみ)
- 採択事例 / 融資 / 行政処分 / 法令 等の周辺データセット件数は本エンドポイントの返却対象外 (それぞれ専用エンドポイント側で取得)

**Example:**

```bash
curl https://api.jpcite.com/v1/meta
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
| `server_version` | string | jpcite version |
| `rate_limit_remaining` | int \| null | 本日の残り呼び出し数。`paid` (metered) は `null` |

**使用量への影響:** **`/v1/ping` は認証付き呼び出しのみ使用量に反映されます**。
頻繁に heartbeat したい用途では `/healthz` を推奨します。

**匿名時の `rate_limit_remaining`:** 未認証時は匿名クォータの目安値を返します。

**Example:**

```bash
curl -H "X-API-Key: am_..." https://api.jpcite.com/v1/ping
```

---

## Billing

Stripe 経由のサブスクリプション管理。詳細フローは [getting-started.md](./getting-started.md#2-api-key)。

### `POST /v1/billing/checkout`

Stripe Checkout セッションを作成して URL を返す。

**認証:** 不要

**Request body:**

| field | type | required | description |
|-------|------|----------|-------------|
| `success_url` | string | yes | 決済後のリダイレクト先 (session_id を受け取るページ) |
| `cancel_url` | string | yes | キャンセル時のリダイレクト先 |
| `customer_email` | string | no | Stripe に事前に渡すメールアドレス |

tier フィールドは存在しません。課金は `¥3/req` の従量課金です。

**Response:**

```json
{"url": "https://checkout.stripe.com/...", "session_id": "cs_live_..."}
```

**エラー:** 請求設定が未完了の場合は `400`、一時的に請求サービスが利用できない場合は `503`。

---

### `POST /v1/billing/portal`

Stripe Customer Portal URL を返す (サブスク変更・キャンセル・カード変更用)。

**認証:** **必須** (Bearer / X-API-Key)

**Request body:**

```json
{"return_url": "https://your-app.example.com/account"}
```

**Response:**

```json
{"url": "https://billing.stripe.com/..."}
```

---

### `POST /v1/billing/keys/from-checkout`

Checkout 成功後に API key を発行する。1 session につき 1 回のみ。

**認証:** Checkout 開始時に発行した `jpcite_checkout_state` cookie が必要。
Stripe session_id だけでは API key を取得できない。通常は
`https://jpcite.com/success.html` / `https://jpcite.com/en/success.html`
のブラウザ画面から呼び出す。

**Request body:**

```json
{"session_id": "cs_live_..."}
```

**Response:**

```json
{"api_key": "am_...", "tier": "metered", "...": "..."}
```

`tier` は課金プランではなく、発行されたキーの種類を表す補助フィールドです。料金は有効な API key での利用が一律 ¥3/req (税込 ¥3.30) です。

**エラー:**

- `402 Payment Required` — session が paid になっていない
- `403 Forbidden` — checkout state cookie がない、または一致しない
- `409 Conflict` — 同 subscription で既に key 発行済み (rotation は `/v1/billing/portal` 経由)

---

### `POST /v1/billing/webhook`

Stripe webhook 受け口。以下のイベントを処理:

- `customer.subscription.created` — subscription 状態と請求書 metadata を同期。raw API key は発行しない
- `invoice.paid` — 支払い成功状態を同期。raw API key は発行しない
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

**認証:** 任意 (未認証でも OK)。API key を付けると、後から問い合わせ内容を確認しやすくなります。

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
- 認証時: API key に紐づく識別子
- `ip_hash` (raw IP は保存しない / HMAC-SHA256 with salt)
- `created_at` (UTC ISO)

**Example:**

```bash
curl -X POST https://api.jpcite.com/v1/feedback \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"message":"検索対象外判定の理由が見えづらい","rating":4}'
```

---

## Context Compression (workload-dependent estimate)

### `GET /v1/intelligence/precomputed/query`

LLM context prefetch 用に、事前計算済みの evidence bundle をコンパクトに返す。リクエスト時に LLM call は行わず、live web search も要求しない。これは evidence packaging のための endpoint であり、context-size や cost への影響は **workload-dependent** で保証されない。

**圧縮効果について:** この endpoint は、LLM に渡す前の資料整理を目的にしています。トークン数や回答コストの削減効果は、モデル、質問、プロンプト、検索設定、キャッシュ状態によって変わるため、固定の削減率は保証しません。

公開できる数値は、同じ質問群、同じモデル、同じ実行日で比較したベンチマーク結果に限定します。「常に何 % 削減」「必ず N 円安い」といった表現は使いません。

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `q` | string | yes | 事前計算済み summary に照合する自由記述 query |
| `prefecture` | string | no | 都道府県フィルタ |
| `tier` | string | no | tier フィルタ |
| `limit` | int | no | `records[]` の最大件数。1〜500 (default 10) |
| `include_facts` | bool | no | `true` で raw facts も含める。default `false` |
| `include_compression` | bool | no | context-size estimate を含める。default `true` |
| `input_token_price_jpy_per_1m` | number | no | caller 側の input token 単価。参考比較が可能な場合のみ使用し、削減額を保証しない |
| `source_tokens_basis` | string | no | `unknown` / `pdf_pages` / `token_count`。caller が比較対象を渡した場合だけ source estimate を出す |
| `source_pdf_pages` | int | no | LLM にそのまま読ませる予定だった PDF ページ数。`source_tokens_basis=pdf_pages` のときだけ使用 |
| `source_token_count` | int | no | caller が自分のモデル UI / tokenizer で測った入力 token 数。`source_tokens_basis=token_count` のときだけ使用 |
| `output_format` | string | no | 現在は `json` のみ対応 |

**Example:**

```bash
curl -H "X-API-Key: am_..." \
  "https://api.jpcite.com/v1/intelligence/precomputed/query?q=省力化&limit=5"
```

PDF をそのまま LLM に読ませる代わりに packet 化する場合の参考比較:

```bash
curl -H "X-API-Key: am_..." \
  "https://api.jpcite.com/v1/intelligence/precomputed/query?q=省力化&limit=5&source_tokens_basis=pdf_pages&source_pdf_pages=30&input_token_price_jpy_per_1m=300"
```

`source_pdf_pages` は caller が知っている比較対象を明示する値です。jpcite は URL から勝手にページ数やトークン数を推定しません。

すでに自分の LLM 画面や tokenizer で比較対象の token 数が分かっている場合:

```bash
curl -H "X-API-Key: am_..." \
  "https://api.jpcite.com/v1/intelligence/precomputed/query?q=省力化&limit=5&source_tokens_basis=token_count&source_token_count=18500&input_token_price_jpy_per_1m=300"
```

**Key response fields:**

| field | type | description |
|-------|------|-------------|
| `bundle_kind` | string | `precomputed_intelligence`。事前計算済み bundle であることを示す |
| `precomputed.record_count` | int | 事前計算済み summary を含む record 件数 |
| `usage.web_search_required` | bool | 常に `false`。caller 側の web search 要否を保証するものではなく、この endpoint 自体が live web search をしないことを示す |
| `compression` | object | context-size estimate。実測 savings や将来の cost reduction を保証しない |
| `compression.source_tokens_input_source` | string | `caller_supplied` の場合のみ、caller が渡した baseline に基づく比較であることを示す |
| `compression.savings_claim` | string | 常に `estimate_not_guarantee`。保証値ではなく参考推定であることを示す |
| `agent_recommendation.recommendation` | string | AI agent 向けの次アクション。`use_jpcite_prefetch` / `use_evidence_packet` / `broaden_query_or_skip` |
| `agent_recommendation.recommend_for_cost_savings` | bool | `true` のときだけ、caller が渡した baseline と token 単価で break-even を満たしたことを示す |
| `agent_recommendation.cost_savings_decision` | string | `supported_by_caller_baseline` のときだけ、AI は「この条件ならコスト削減の可能性がある」と説明できる |
| `agent_recommendation.missing_for_cost_claim` | array | コスト削減として説明するために不足している caller 入力 |
| `agent_recommendation.context_savings` | object | caller baseline がある場合だけ、`break_even_met` や `avoided_tokens_estimate` を機械可読にまとめる |

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

下記は OpenAPI spec (`docs/openapi/v1.json`) と対応する endpoint 一覧です。主要 endpoint は本ページ前半で詳しく説明し、それ以外は request / response の形と curl 例を中心に載せています。詳細は OpenAPI spec、もしくは [mcp-tools.md](./mcp-tools.md) の同名 MCP tool を参照してください。

> **凡例:**
> - **認証** 列の "任意 (未認証は匿名扱い)" は 3 req/日 per IP の anonymous quota を消費する。**必須** は 401/403 を返す (Bearer / X-API-Key 必須)。
> - **Response** の `"..."` は array/object の省略表記。完全 schema は OpenAPI spec を参照。
> - 一部の専門テンプレートや審査中の機能は、公開対象になった時点で OpenAPI と MCP ツール一覧に追加されます。

---

## Programs (additional)

### `POST /v1/programs/prescreen`

Rank programs by fit to a caller business profile.

This is the "judgment" complement to `/v1/programs/search`'s "discovery".

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
curl -X POST "https://api.jpcite.com/v1/programs/prescreen" \
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
curl -X GET "https://api.jpcite.com/readyz"
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
curl -X GET "https://api.jpcite.com/v1/meta/freshness?limit=50" \
  -H "X-API-Key: am_..."
```

---

## Billing (additional)

### `POST /v1/billing/refund_request`

Stripe で課金された ¥3/req メータリング分の返金を顧客が請求する ためのエンドポイント。運営側で 14 日以内に手動審査を行います。 このエンドポイントは受付番号の発行と通知のみで、自動的な返金や API キー失効は行いません。既に課金済みの分も審査完了までそのまま 残ります。

**認証:** 任意

**Request body (`RefundRequest`):**

```json
{
  "amount_yen": 0,
  "customer_id": "string (わかる場合のみ)",
  "reason": "string",
  "requester_email": "user@example.com"
}
```

**Response 201 (`RefundResponse`):**

```json
{
  "contact": "support",
  "expected_response_within_days": 14,
  "note": "返金は手動審査となります。既に課金済みの ¥3/req メータリング分は 自動取消しされません — 審査完了後、運営から個別にご連絡します。",
  "received_at": "string",
  "request_id": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.jpcite.com/v1/billing/refund_request" \
  -H "Content-Type: application/json" \
  -d '{"amount_yen": 0, "reason": "string", "requester_email": "user@example.com"}'
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
curl -X GET "https://api.jpcite.com/v1/me" \
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
curl -X POST "https://api.jpcite.com/v1/me/billing-portal" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/me/billing_history`

API key に紐づく直近の請求履歴を返す。請求書がまだない場合は空配列を返す。

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
curl -X GET "https://api.jpcite.com/v1/me/billing_history" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/me/cap`

Set the customer's self-serve monthly spend cap.

Authenticated with `X-API-Key` or `Authorization: Bearer`.
Anonymous callers (no key) cannot set a cap because the anonymous tier is
already gated by the 3 req/日 free quota — there is nothing to cap.

The unit price stays ¥3/req. `monthly_cap_yen` is a client
budget control: at cap-reached the API returns 503 with
`cap_reached: true` and Stripe usage is not recorded for the rejected
request, so the cap is enforced.

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
curl -X POST "https://api.jpcite.com/v1/me/cap" \
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
  "last_30_amount_yen": 0,
  "last_30_calls": 0,
  "last_7_calls": 0,
  "month_to_date_amount_yen": 0,
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.jpcite.com/v1/me/dashboard?days=30" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/me/rotate-key`

現在の API key を失効し、新しい API key を発行します。月次上限や通知設定は引き継がれます。

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
curl -X POST "https://api.jpcite.com/v1/me/rotate-key" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/me/tool_recommendation`

Map a free-text intent to recommended tool candidates.

Pure keyword scoring — no LLM API call.
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
curl -X GET "https://api.jpcite.com/v1/me/tool_recommendation" \
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
curl -X GET "https://api.jpcite.com/v1/me/usage?days=30" \
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
curl -X GET "https://api.jpcite.com/v1/me/usage_by_tool?days=30" \
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
curl -X POST "https://api.jpcite.com/v1/session" \
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
curl -X POST "https://api.jpcite.com/v1/session/logout" \
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
curl -X GET "https://api.jpcite.com/v1/usage" \
  -H "X-API-Key: am_..."
```

---

## Alerts (`/v1/me/alerts`)

### `POST /v1/me/alerts/subscribe`

認証済み API key にアラート通知を登録します。`webhook_url` または `email` のどちらか一方は必須です。

`filter_value` は `filter_type='all'` 以外で必須です。

**認証:** **必須** (Bearer / X-API-Key)

**Request body (`AlertSubscribeRequest`):**

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
curl -X POST "https://api.jpcite.com/v1/me/alerts/subscribe" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "filter_type": "tool", "filter_value": "string", "min_severity": "critical", "webhook_url": "string"}'
```

---

### `GET /v1/me/alerts/subscriptions`

認証済み API key の有効なアラート通知を一覧します。停止済み通知は通常レスポンスに含まれません。

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
curl -X GET "https://api.jpcite.com/v1/me/alerts/subscriptions" \
  -H "X-API-Key: am_..."
```

---

### `DELETE /v1/me/alerts/subscriptions/{sub_id}`

Deactivate (soft-delete) the subscription.

The record stays retained with active=0 so audit trails remain intact. A
re-subscribe creates a fresh record rather than reviving the old one — this
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
curl -X DELETE "https://api.jpcite.com/v1/me/alerts/subscriptions/<sub_id>" \
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
  "client_id": "jpcite-mcp",
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
curl -X POST "https://api.jpcite.com/v1/device/authorize" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"client_id": "jpcite-mcp", "scope": "string"}'
```

---

### `POST /v1/device/complete`

Called by /go after Stripe Checkout succeeds.

1. Verifies the Stripe session is paid (or metered — no_payment_required).
2. Marks device_code activated.
3. Issues a device-scoped API key and links it.
4. Makes the newly issued key available for one-time retrieval so the MCP's
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
curl -X POST "https://api.jpcite.com/v1/device/complete" \
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
  "client_id": "jpcite-mcp",
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
curl -X POST "https://api.jpcite.com/v1/device/token" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"client_id": "jpcite-mcp", "device_code": "string", "grant_type": "string"}'
```

---

## Subscribers (Email)

### `GET /v1/email/unsubscribe`

メール下部のリンクから表示される unsubscribe ページ。

リンクに含まれる token を検証し、ユーザーが明示的に操作した場合に配信停止を行う。

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `email` | string | yes | — |
| `token` | string | yes | — |

**Example:**

```bash
curl -X GET "https://api.jpcite.com/v1/email/unsubscribe" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/email/unsubscribe`

配信停止を受け付ける endpoint。同じ token で複数回呼ばれても結果は同じ。

無効な token でも、メールアドレスの存在確認に使われないよう同じ形のレスポンスを返す。

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
curl -X POST "https://api.jpcite.com/v1/email/unsubscribe" \
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
curl -X POST "https://api.jpcite.com/v1/email/webhook"
```

---

### `POST /v1/subscribers`

Subscribe

**認証:** 任意 (未認証は匿名扱い)

**Request body (`SubscriberSubscribeRequest`):**

```json
{
  "email": "user@example.com",
  "source": "string"
}
```

**Response 201 (`SubscriberSubscribeResponse`):**

```json
{
  "subscribed": true
}
```

**Example:**

```bash
curl -X POST "https://api.jpcite.com/v1/subscribers" \
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
curl -X GET "https://api.jpcite.com/v1/subscribers/unsubscribe" \
  -H "X-API-Key: am_..."
```

---

## Compliance Newsletter

### `POST /v1/compliance/stripe-checkout`

Create a Stripe Checkout Session for a verified paid subscriber.

Requires the subscriber record to already exist and be verified. The
session's `client_reference_id` is the subscriber_id so the webhook
can tie the Stripe subscription back to our record.

**認証:** 任意 (未認証は匿名扱い)

**Request body (`CheckoutRequest`):**

```json
{
  "cancel_url": "https://jpcite.com/alerts.html?status=canceled",
  "subscriber_id": 0,
  "success_url": "https://jpcite.com/alerts.html?status=ok"
}
```

**Response 200 (`CheckoutResponse`):**

```json
{
  "session_id": "string",
  "url": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.jpcite.com/v1/compliance/stripe-checkout" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"cancel_url": "https://jpcite.com/alerts.html?status=canceled", "subscriber_id": 0, "success_url": "https://jpcite.com/alerts.html?status=ok"}'
```

---

### `POST /v1/compliance/stripe-webhook`

Handle customer.subscription.created/.deleted for the alert product.

On `created` the subscription becomes active for the alert product.
On `deleted` the subscription is marked canceled.

**認証:** Stripe / Postmark 署名検証 (header)

**Response 200:**

```json
{}
```

**Example:**

```bash
curl -X POST "https://api.jpcite.com/v1/compliance/stripe-webhook"
```

---

### `POST /v1/compliance/subscribe`

Create a new subscription request and send a verification email.

Duplicate email behaviour: the response shape is privacy-preserving and
does not reveal whether an email is already registered. Repeated requests
may resend the verification email subject to rate limits.

**認証:** 任意 (未認証は匿名扱い)

**Request body (`ComplianceSubscribeRequest`):**

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

**Response 201 (`ComplianceSubscribeResponse`):**

```json
{
  "checkout_url": "string",
  "next_step": "verify",
  "subscriber_id": 0
}
```

**Example:**

```bash
curl -X POST "https://api.jpcite.com/v1/compliance/subscribe" \
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
curl -X POST "https://api.jpcite.com/v1/compliance/unsubscribe/<unsubscribe_token>" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/compliance/verify/{verification_token}`

Verify a subscriber email and render a minimal HTML page. The link is
idempotent; repeated clicks show the same success page. Paid subscribers
are directed to Stripe Checkout after verification.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `verification_token` | string | yes | — |

**Example:**

```bash
curl -X GET "https://api.jpcite.com/v1/compliance/verify/<verification_token>" \
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
curl -X GET "https://api.jpcite.com/v1/stats/confidence" \
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
  "laws": 0,
  "...": "..."
}
```

**Example:**

```bash
curl -X GET "https://api.jpcite.com/v1/stats/coverage" \
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
curl -X GET "https://api.jpcite.com/v1/stats/data_quality" \
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
curl -X GET "https://api.jpcite.com/v1/stats/freshness" \
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
curl -X GET "https://api.jpcite.com/v1/stats/usage" \
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
curl -X POST "https://api.jpcite.com/v1/me/testimonials" \
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
curl -X DELETE "https://api.jpcite.com/v1/me/testimonials/<testimonial_id>" \
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
curl -X GET "https://api.jpcite.com/v1/testimonials" \
  -H "X-API-Key: am_..."
```

---

## Advisors

### `GET /v1/advisors/match`

Return advisors matching the supplied filters, ordered by relevance.

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
curl -X GET "https://api.jpcite.com/v1/advisors/match" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/advisors/report-conversion`

Record a referral conversion and queue the corresponding referral summary.

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
curl -X POST "https://api.jpcite.com/v1/advisors/report-conversion" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"conversion_value_yen": 0, "evidence_url": "https://...", "referral_token": "string"}'
```

---

### `POST /v1/advisors/signup`

Create an advisor profile and return the onboarding URL. Public listing starts after official registry verification and payout readiness are complete.

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
curl -X POST "https://api.jpcite.com/v1/advisors/signup" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"address": "string", "agreed_to_terms": true, "city": "string", "commission_model": "flat", "commission_rate_pct": 5, "commission_yen_per_intro": 3000, "contact_email": "user@example.com", "contact_phone": "string", "...": "..."}'
```

---

### `POST /v1/advisors/track`

Record a referral click and return a referral redirect URL. Any referral fee is resolved at conversion time.

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
curl -X POST "https://api.jpcite.com/v1/advisors/track" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"advisor_id": 0, "source_program_id": "string", "source_query_hash": "string"}'
```

---

### `POST /v1/advisors/verify-houjin/{advisor_id}`

Verify the advisor's organization number against the official registry. Repeated successful verification is safe.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `advisor_id` | integer | yes | — |

**Example:**

```bash
curl -X POST "https://api.jpcite.com/v1/advisors/verify-houjin/<advisor_id>" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/advisors/{advisor_id}/dashboard-data`

Return referral and earnings summary for the advisor dashboard.

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
curl -X GET "https://api.jpcite.com/v1/advisors/<advisor_id>/dashboard-data" \
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
curl -X GET "https://api.jpcite.com/v1/widget/enum_values" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/widget/search`

Search programs restricted to the widget surface.

Widget 向けに `/v1/programs/search` と同等の制度検索を返す軽量 endpoint。

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
curl -X GET "https://api.jpcite.com/v1/widget/search" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/widget/signup`

Create a Stripe Checkout session for the widget plan.

The widget key is provisioned after Stripe confirms checkout completion.

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
curl -X POST "https://api.jpcite.com/v1/widget/signup" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"cancel_url": "string", "email": "user@example.com", "label": "string", "origins": ["string"], "plan": "business", "success_url": "string"}'
```

---

### `POST /v1/widget/stripe-webhook`

Process widget billing events. Checkout completion provisions a widget key; subscription cancellation or payment failure disables widget access until billing is resolved.

**認証:** Stripe / Postmark 署名検証 (header)

**Response 200:**

```json
{}
```

**Example:**

```bash
curl -X POST "https://api.jpcite.com/v1/widget/stripe-webhook"
```

---

### `GET /v1/widget/{key_id}/usage`

Return the owner-visible widget usage summary.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `key_id` | string | yes | — |

**Example:**

```bash
curl -X GET "https://api.jpcite.com/v1/widget/<key_id>/usage" \
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
  "contact": "support",
  "expected_response_within_days": 30,
  "received_at": "string",
  "request_id": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.jpcite.com/v1/privacy/deletion_request" \
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
  "contact": "support",
  "expected_response_within_days": 14,
  "received_at": "string",
  "request_id": "string"
}
```

**Example:**

```bash
curl -X POST "https://api.jpcite.com/v1/privacy/disclosure_request" \
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
curl -X GET "https://api.jpcite.com/v1/calendar/deadlines?within_days=30" \
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
| `q` | string | null | no | Free-text search over company_name + case_title + case_summary + source_excerpt. Short names and short ASCII queries use fallback matching. |
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
curl -X GET "https://api.jpcite.com/v1/case-studies/search" \
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
curl -X GET "https://api.jpcite.com/v1/case-studies/<case_id>" \
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
curl -X GET "https://api.jpcite.com/v1/loan-programs/search" \
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
curl -X GET "https://api.jpcite.com/v1/loan-programs/<loan_id>" \
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
| `q` | string | null | no | Free-text search over program_name_hint + reason_excerpt + source_title (case-insensitive text match). |
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
curl -X GET "https://api.jpcite.com/v1/enforcement-cases/search" \
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
curl -X GET "https://api.jpcite.com/v1/enforcement-cases/<case_id>" \
  -H "X-API-Key: am_..."
```

---

## Invoice Registrants

### `GET /v1/invoice_registrants/search`

Search 適格請求書発行事業者 by name / 法人番号 / location / status.

This endpoint is lookup-only. Bulk-style queries (empty q + empty
filters paging through the complete dataset) work but return exactly one
page at a time; the PDL v1.0 attribution is repeated on every page to
keep 出典明記 + 編集・加工注記 visible across paginated reads.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `q` | string | null | no | Prefix match on 事業者名 (normalized_name). Short queries (< 2 chars) are rejected to keep the match selective. |
| `houjin_bangou` | string | null | no | Exact 13-digit 法人番号 filter. Returns only rows where houjin_bangou matches (sole-proprietor rows excluded). |
| `kind` | string | null | no | corporate = 法人 (registrant_kind='corporation'); individual = 個人事業主 (registrant_kind='sole_proprietor'). Omit to include both plus 'other'. |
| `prefecture` | string | null | no | Prefecture name. Canonical = full-suffix kanji ('東京都'); short form ('東京') and romaji also accepted. |
| `registered_after` | string | null | no | ISO date (YYYY-MM-DD) — inclusive lower bound on registered_date. |
| `registered_before` | string | null | no | ISO date (YYYY-MM-DD) — inclusive upper bound on registered_date. |
| `active_only` | boolean | no | When true (default), excludes revoked (revoked_date IS NOT NULL) and expired (expired_date IS NOT NULL) rows. Flip to false for historical/audit research. |
| `limit` | integer | no | Page size. Default 50, maximum 100. No wildcard bulk export — point consumers at NTA's own download URL for full snapshots. |
| `offset` | integer | no | — |

**Response 200 (`InvoiceRegistrantSearchResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/invoice_registrants/search" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/invoice_registrants/{invoice_registration_number}`

Exact lookup by 適格請求書発行事業者登録番号 ('T' + 13 digits).

未登録または未収録の場合は、単純な 404 だけで終わらせず、確認に使える追加情報を返す。重要な確認では、レスポンス内の案内に従って国税庁の公式検索も確認してください。

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
curl -X GET "https://api.jpcite.com/v1/invoice_registrants/<invoice_registration_number>" \
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
| `q` | string | null | no | Free-text search across law_title + law_short_title + law_number + summary. Japanese phrases are normalized; for very short terms, structured filters are more reliable. |
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
curl -X GET "https://api.jpcite.com/v1/laws/search" \
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
curl -X GET "https://api.jpcite.com/v1/laws/<unified_id>" \
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
curl -X GET "https://api.jpcite.com/v1/laws/<unified_id>/related-programs" \
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
curl -X POST "https://api.jpcite.com/v1/court-decisions/by-statute" \
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
| `q` | string | null | no | Free-text search across case_name + subject_area + key_ruling + impact_on_business with Japanese phrase normalization. |
| `court` | string | null | no | Filter by 裁判所名 (exact match, e.g. '最高裁判所第三小法廷'). |
| `court_level` | string | null | no | Filter by court tier. One of: supreme | high | district | summary | family. |
| `decision_type` | string | null | no | Filter by decision shape. One of: 判決 | 決定 | 命令. |
| `subject_area` | string | null | no | Filter by 分野 (substring match; source vocabulary varies by 判例集). |
| `references_law_id` | string | null | no | Filter rows whose related-law identifier list contains this LAW identifier. |
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
curl -X GET "https://api.jpcite.com/v1/court-decisions/search" \
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
curl -X GET "https://api.jpcite.com/v1/court-decisions/<unified_id>" \
  -H "X-API-Key: am_..."
```

---

## Tax Rulesets

### `POST /v1/tax_rulesets/evaluate`

Evaluate one or more rulesets against a caller business_profile.

Walks `eligibility_conditions_json` for each selected record and returns
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
curl -X POST "https://api.jpcite.com/v1/tax_rulesets/evaluate" \
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
| `q` | string | null | no | Free-text search across ruleset_name + eligibility_conditions + calculation_formula. Japanese phrases are normalized; for very short terms, structured filters are more reliable. |
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
curl -X GET "https://api.jpcite.com/v1/tax_rulesets/search" \
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
curl -X GET "https://api.jpcite.com/v1/tax_rulesets/<unified_id>" \
  -H "X-API-Key: am_..."
```

---

## Bids

### `GET /v1/bids/search`

Search bids (入札案件). Text search when `q` is given, else most recently
published first.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `q` | string | null | no | Free-text search across bid_title + bid_description + procuring_entity + winner_name. Japanese phrases are normalized; for very short terms, use a longer phrase or structured filters. |
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
curl -X GET "https://api.jpcite.com/v1/bids/search" \
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
curl -X GET "https://api.jpcite.com/v1/bids/<unified_id>" \
  -H "X-API-Key: am_..."
```

---

## jpcite: Programs (Active / Related / Stats / GX)

### `GET /v1/am/acceptance_stats`

採択率 / 採択事例 statistics from the acceptance statistics corpus.

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

**Response 200 (`SearchResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/acceptance_stats" \
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

**Response 200 (`ActiveAtResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/active_at" \
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

**Response 200 (`SimpleSearchResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/gx_programs?theme=ghg_reduction" \
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

**Response 200 (`OpenProgramsResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/open_programs" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/programs/active_v2`

Three-axis active-at: effective window + application_open + application_close in one query.

Returns programs that:
  - are effective on `as_of` (effective_from <= as_of < effective_until,
    with `effective_from_source` provenance hint), AND
  - have an application round whose open_date <= `application_open_by`
    (when provided), AND
  - have an application round whose close_date >= `application_close_by`
    (when provided), AND
  - match `prefecture` (when provided).

Caveat: 改正履歴の時系列データは一部のみ充足しています。`effective_from` /
`effective_until` が入っている record だけを日付別追跡に使い、その他は現時点の
スナップショットとして扱ってください。response には `_lifecycle_caveat` が含まれる
場合があります。

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
curl -X GET "https://api.jpcite.com/v1/am/programs/active_v2" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/related/{program_id}`

Graph walk over public program relationships (prerequisite / compatible / incompatible / replaces / amends / related / references_law etc.).

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

**Response 200 (`RelatedProgramsResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/related/<program_id>?relation_types=['string']" \
  -H "X-API-Key: am_..."
```

---

## jpcite: Intent / Reason / Enums

### `GET /v1/am/enums/{enum_name}`

List canonical enum values + frequency for a given enum_name.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `enum_name` | string | yes | — |

**Response 200 (`EnumValuesResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/enums/<enum_name>" \
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

**Response 200 (`IntentResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/intent" \
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

**Response 200 (`ReasonResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/reason" \
  -H "X-API-Key: am_..."
```

---

## jpcite: Tax Incentives & Certifications

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

**Response 200 (`SearchResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/certifications" \
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

**Response 200 (`SearchResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/tax_incentives" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/tax_rule`

Single tax measure lookup with root law, rate, and applicability window.

**認証:** 任意 (未認証は匿名扱い)

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `measure_name_or_id` | string | yes | — |
| `rule_type` | string | null | no | — |
| `as_of` | string | null | no | ISO YYYY-MM-DD (default today) |

**Response 200 (`TaxRuleResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/tax_rule" \
  -H "X-API-Key: am_..."
```

---

## jpcite: Loans & Mutual Insurance

### `GET /v1/am/loans`

Loan product query — 公庫 / 商工中金 / 自治体制度融資 with 3-axis guarantor filter.

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

**Response 200 (`LoanSearchResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/loans?loan_kind=ippan" \
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

**Response 200 (`LoanSearchResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/mutual_plans?plan_kind=retirement_mutual" \
  -H "X-API-Key: am_..."
```

---

## jpcite: Laws & Enforcement

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

**Response 200 (`LawProgramResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/by_law" \
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

**Response 200 (`EnforcementCheckResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/enforcement" \
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

**Response 200 (`LawArticleResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/law_article" \
  -H "X-API-Key: am_..."
```

---

## jpcite: Annotations / Validation / Provenance

### `GET /v1/am/annotations/{entity_id}`

制度・法人・法令などの補足メモ、品質ラベル、検証結果を entity_id から取得する。

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `entity_id` | string | yes | jpcite の entity_id |

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `kinds` | string[] | null | no | annotation kind で絞り込み。repeat 指定で OR 条件 |
| `include_superseded` | boolean | no | Include superseded / expired annotations (default False = currently-live only). |
| `limit` | integer | no | — |

**Response 200 (`AnnotationsResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/annotations/<entity_id>?kinds=['string']" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/provenance/fact/{fact_id}`

Return source details for one fact, with entity-level sources when fact-level provenance is unavailable.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `fact_id` | integer | yes | Fact identifier |

**Response 200 (`ProvenanceResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/provenance/fact/<fact_id>" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/provenance/{entity_id}`

Return source URLs, license, role, fetched timestamp, and license summary for one entity.

**認証:** 任意 (未認証は匿名扱い)

**Path parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `entity_id` | string | yes | Stable entity identifier |

**Query parameters:**

| name | type | required | description |
|------|------|----------|-------------|
| `include_facts` | boolean | no | If True, also return per-fact provenance when available. Default False = entity-level sources only. |
| `fact_limit` | integer | no | Max facts when include_facts=True (default 200). |

**Response 200 (`ProvenanceResponse`):**

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
curl -X GET "https://api.jpcite.com/v1/am/provenance/<entity_id>?include_facts=false" \
  -H "X-API-Key: am_..."
```

---

### `POST /v1/am/validate`

汎用 intake 検証。入力された applicant_data を登録済みの検証ルールに照らして評価し、
rule 単位の passed/failed/deferred を返します。

**認証:** 任意 (未認証は匿名扱い)

**Request body (`ValidationRequest`):**

```json
{
  "applicant_data": {},
  "entity_id": "string",
  "scope": "intake"
}
```

**Response 200 (`ValidationResponse`):**

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
curl -X POST "https://api.jpcite.com/v1/am/validate" \
  -H "X-API-Key: am_..." \
  -H "Content-Type: application/json" \
  -d '{"applicant_data": {}, "entity_id": "string", "scope": "intake"}'
```

---

## jpcite: Static Resources & Example Profiles

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
curl -X GET "https://api.jpcite.com/v1/am/example_profiles" \
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
curl -X GET "https://api.jpcite.com/v1/am/example_profiles/<profile_id>" \
  -H "X-API-Key: am_..."
```

---

### `GET /v1/am/static`

List curated jpcite taxonomies, including glossary, money types, obligations, sector terms, and exclusion-rule categories.

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
curl -X GET "https://api.jpcite.com/v1/am/static" \
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
curl -X GET "https://api.jpcite.com/v1/am/static/<resource_id>" \
  -H "X-API-Key: am_..."
```

---

## jpcite: Health

### `GET /v1/am/health/deep`

サービス状態をまとめて返す health endpoint。監視用途で `status` ∈ {ok, degraded, unhealthy} を確認できる。

通常はキャッシュ済みの結果を返します。直近状態を確認したい場合だけ `?force=true` を指定してください。

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
curl -X GET "https://api.jpcite.com/v1/am/health/deep?force=false" \
  -H "X-API-Key: am_..."
```

---

## 関連

- [mcp-tools.md](./mcp-tools.md) — 同じ機能を MCP tool として叩く
- [exclusions.md](./exclusions.md) — 排他ルールの概念
- [pricing.md](./pricing.md) — 料金
- [サンプル集](./examples.md) — 8 本の runnable サンプル (Python 4 + TypeScript 4, 各ファイル 50-150 行)
