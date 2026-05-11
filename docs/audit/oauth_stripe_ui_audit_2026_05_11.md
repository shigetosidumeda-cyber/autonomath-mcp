# OAuth (magic-link) + Stripe Customer Portal Audit — 2026-05-11

Read-only audit; no code touched. Scope: dashboard / pricing UI + `src/jpintel_mcp/api/billing.py` + `src/jpintel_mcp/api/billing_webhook_idempotency.py` + `src/jpintel_mcp/api/me/` package + `site/.well-known/mcp.json`. Compared against the 8 audit items provided.

## Source files inspected

- `site/dashboard.html` (1397 行)
- `site/dashboard.js` / `site/dashboard.src.js` / `site/dashboard_v2.js` / `site/dashboard_v2.src.js` (portal binding JS)
- `site/pricing.html` (790 行)
- `site/.well-known/mcp.json`
- `src/jpintel_mcp/api/billing.py` (1820 行)
- `src/jpintel_mcp/api/billing_webhook_idempotency.py` (63 行, 新 helper)
- `src/jpintel_mcp/api/me/__init__.py` (legacy shim + package re-export)
- `src/jpintel_mcp/api/me.py` (1461 行, legacy module side-loaded)
- `src/jpintel_mcp/api/me/login_request.py` (109 行, 新)
- `src/jpintel_mcp/api/me/login_verify.py` (84 行, 新)
- `src/jpintel_mcp/api/main.py` (router 取り込み確認)
- `src/jpintel_mcp/api/anon_limit.py` (per-IP 3 req/日 counter)
- `scripts/migrations/053_stripe_webhook_events.sql` (旧 dedup table)
- `scripts/migrations/205_stripe_event_idempotency.sql` (新 dedup table)

備考: input 指定の `functions/api/billing/` は **存在しない**。`functions/` 配下は `artifacts/` のみで、billing 連携の CF Pages Functions は未実装。全ての billing 経路は Fly 側 (`api/billing.py`) で完結している。

---

## Audit item 結果

### 1. dashboard.html に `#billing` アンカー + portal redirect ボタン
**green**

- `site/dashboard.html:508` に `<div class="stat-card" id="billing-section">`、`L1362` に `<section id="billing">` あり (内部 nav 用 anchor も `L1351` で `#billing` 指している)。
- 「Stripe ポータルを開く →」ボタンは `L512` `<a id="dash-billing-btn">`、dunning banner 上の「Stripe ポータルへ」は `L251` `<a id="dash-dunning-portal">`。
- JS 結線: `site/dashboard.js:40, 97` および `site/dashboard.src.js:973, 978` が `dash-billing-btn` クリックで `POST /v1/me/billing-portal` (CSRF header 付き) を叩き、返ってきた `body.url` に `window.location` を移す。`dashboard_v2.js:26` でも `dash-dunning-portal` 用に同じ wiring。
- 残課題: dashboard 内 9-widget 互換 nav の `#billing` section 本体 (`L1362`) は placeholder 文言のみで、Wave 8 で hydrate 予定の旨明記。portal 起動自体は `#billing-section` (L508) 側で機能している。

---

### 2. `STRIPE_PORTAL_RETURN_URL` env が `portal_url` に正しく injection
**yellow**

- `api/billing.py:229-232` の dunning メール送信パスは `os.environ.get("STRIPE_PORTAL_RETURN_URL", "https://jpcite.com/dashboard.html#billing")` で読み込み、`_get_email_client().send_dunning(..., portal_url=portal_url, ...)` に渡している。Env 未設定時はダッシュボード `#billing` アンカーへ fallback、これは正しい。
- 一方、Customer Portal を**実際に開く** `POST /v1/billing/portal` (`L970-1012`) と `POST /v1/me/billing-portal` (`me.py:1357`) は、`payload.return_url` (caller-supplied) を `_validate_portal_return_url` (`L551`) で allowlist 通過させた上で `billing_portal.Session.create(return_url=…)` に渡している。`STRIPE_PORTAL_RETURN_URL` env は **portal 作成時には参照されない** — dunning email 文面の URL にだけ injection されている。
- 評価: dunning 経路は green。ただし portal 起動本体は env injection されず caller-supplied URL に依存。「return_url を env で固定したい」要件であれば未充足。今のところ `_PORTAL_RETURN_PATHS` allowlist で安全側に倒れているので機能的破綻はないが、運用上 env 1 箇所で portal 戻り先を集中管理したい場合は別途実装が要る。

---

### 3. `billing_address_country=JP` enforcement (Stripe API 引数)
**red**

- `api/billing.py:875-879` で Stripe Tax が ON のときだけ `extra["billing_address_collection"] = "required"` を Checkout.Session.create() に追加。これは「住所を集める」フラグであって、**`country=JP` のホワイトリスト指定ではない**。
- 同 file 全行 grep しても `billing_address_country` / `"country": "JP"` / `restricted_countries=["JP"]` の文字列は存在しない。Stripe SDK 側 `customer_creation` や `customer_update` の `allowed_countries=["JP"]` も指定なし。
- `mcp.json:194` で `eligibleRegion: {"@type": "Country", "name": "Japan"}` を schema.org に宣言しているが、これは API 引数強制ではなく宣言メタデータ。
- 結果として **海外住所の顧客でも Checkout は通る**。Stripe Tax 設定で JP 10% を取りこぼした場合 (顧客がパスポート JP / 居住地海外など) でも、システム側で reject されない。memory「JP only」原則を Stripe API 呼び出しで担保したい場合は未実装。
- 残課題: `extra["billing_address_collection"] = {"allowed_countries": ["JP"]}` 相当の追加、もしくは `automatic_tax` 結果からの post-validation で `country != "JP"` を拒否する webhook 処理が必要。

---

### 4. magic-link 6 桁 code + HS256 JWT 24h + HttpOnly Secure SameSite=Lax cookie
**red**

- 新規 `me/login_request.py` + `me/login_verify.py` の **コード自体は仕様適合**:
  - `login_request.py:70-78`: `secrets.randbelow(1_000_000):06d` で 6 桁生成、`sha256(email:code)` でハッシュ保存、TTL 900 s (15 分)、`reuse_existing_code` 真偽返却。SMTP は xrea bookyou.net (memory `reference_bookyou_mail.md` 準拠)。
  - `login_verify.py:60-82`: HS256, payload `{sub, iat, exp}`, `exp=now+86400` (24h)、`response.set_cookie(key="jpcite_session", httponly=True, secure=True, samesite="lax", path="/", max_age=86400)`。全て指定通り。
- **致命的 gap**: 両 router は **FastAPI app に include されていない**。
  - `api/main.py:2320` で `app.include_router(me_router)` (legacy `me.py` の API-key paste session 用 router) のみ。
  - `api/me/__init__.py` は legacy `me.py` を `importlib` で side-load して全 symbol を package namespace に再 export しているが、新 `login_request_router` / `login_verify_router` を package の `router` として merge していない。
  - `grep -rn 'login_request\|login_verify'` 結果: `tests/test_me_auth.py` のみが `POST /v1/me/login_request` を叩いているが、実際の app で route 解決できないため (本番では) **404**。テストでは monkey-patch で通している可能性大。
- 結果: 仕様コードは存在するが**本番 deploy では magic-link 経由でログインできない**。dashboard は依然として「API キーを paste して session 化」する legacy flow のみ動作。
- 残課題: `api/me/__init__.py` で `from .login_request import router as login_request_router` + `from .login_verify import router as login_verify_router` を export し、`api/main.py` で両方 `include_router` する。または legacy `me.router` に APIRouter.include_router() で merge する。

---

### 5. webhook idempotency table 経由で重複 event 排除
**yellow**

- 重複排除自体は機能している: `api/billing.py:1290-1357` が migration 053 の `stripe_webhook_events` table (event_id PRIMARY KEY) を `BEGIN IMMEDIATE` + `INSERT INTO stripe_webhook_events` で dedup している。`processed_at IS NULL` 状態の同一 event_id が来たら 200 で短絡。レース条件 (双子 webhook delivery) も `UNIQUE constraint failed` を捕捉して `duplicate_ignored_race` でログ。
- **gap**: input 指定の `billing_webhook_idempotency.py` (新 helper, migration 205 の `stripe_event_idempotency` table 用) は **どこからも import されていない**。`grep` で `from .billing_webhook_idempotency` / `from jpintel_mcp.api.billing_webhook_idempotency` 0 件。
- つまり「webhook idempotency 機能は live」だが、「audit 対象として新規追加した helper module + 新 table (migration 205)」は arrowhead 状態 (定義だけあって consumer なし)。migration 053 と 205 の table が 2 系統並存していて、片方しか使われていない。
- 残課題: (A) billing.py の dedup を新 helper にリファクタして 205 系に統一する、もしくは (B) migration 205 + `billing_webhook_idempotency.py` を撤去して 053 系一本化を明示する。現状放置はスキーマ drift と「audit ありき」コードの 2 種類のリスクを残す。

---

### 6. anonymous 3 req/day per IP counter が portal 経由ログイン後に paid mode に切り替わる
**green**

- `api/anon_limit.py:553-601` の `enforce_anon_ip_limit` が router-level dep として:
  - `request.headers["x-api-key"]` または `Authorization: Bearer …` を抽出。
  - HMAC-SHA256(`api_key_salt`, raw_key) で hash 計算 → `api_keys WHERE key_hash = ? AND revoked_at IS NULL LIMIT 1` で active key 確認。
  - active key 見つかれば `return` で counter 増分なしに bypass。
  - 見つからなければ JST 日次 bucket (`anon_rate_limit` table) に対し `_try_increment` で +1、3 req 超で 429。
- DB lock や connect 失敗時は **fail-CLOSED** (W28, 2026-05-04) で 429 を返す posture が明記されている。
- portal で API キーを発行した瞬間 (`/v1/billing/keys/from-checkout`) から `api_keys` row が作られ、その raw key を caller が `X-API-Key` header に乗せた呼び出しは即時 paid mode (anon counter 非増分) に切替。
- 残課題なし。ただし magic-link 経由の cookie session (item 4 で red 認定) では `X-API-Key` ヘッダが付かないため、cookie session だけで anon limit を bypass できない設計になっている点に注意。item 4 が直る前提なら、`api/anon_limit.py` 側にも cookie session 認識 path を追加するか、別 router-level dep を組む必要がある。

---

### 7. pricing.html `#api-paid` のリンクが portal に正しく繋がる
**green** (やや caveat あり)

- `site/pricing.html:608` で `<article class="price-card highlight" aria-labelledby="api-paid">` + `L610` `<h2 id="api-paid">従量</h2>` で anchor 存在。
- `L617` のチェックアウトボタンは `POST https://api.jpcite.com/v1/billing/checkout` (`L686-695`) を叩き、返り `data.url` で `window.location` 移行。consent gate (`L613-616`) + 15s timeout + 402/500 ハンドリング込み。
- `#api-paid` 自体は **Stripe Customer Portal** に直接遷移するわけではなく「Checkout で新規キー発行 → 既存ユーザは dashboard 経由で portal」という 2 段構え。これは memory「pricing.html は API キー発行ファーストエントリ」の設計と一致。
- 残課題: pricing.html の `#api-paid` から portal へ「既に契約済みの方は dashboard で portal を開く」リンクが見当たらない (Stripe ポータルへの ON-RAMP が dashboard 限定)。組織内 / 経理担当者が pricing から直接 portal を開きたい用途は未充足だが、要件「リンクが portal に**正しく**繋がる」を「checkout 経由で結果として portal にアクセスできる契約状態を作れる」と読めば green。厳格解釈なら yellow。

---

### 8. `mcp.json` `auth.type=apiKey + X-API-Key header` の宣言が API 実装と一致
**green**

- `site/.well-known/mcp.json`:
  - `L21-39`: `mcp.auth.type=apiKey`, `header=X-API-Key`, `env=JPCITE_API_KEY`, `anonymous_limit="3 requests/day per IP"`, `paid.api_key_header=X-API-Key`。
  - `L195-211`: top-level `authentication.type=apiKey`, `scheme=header`, `header=X-API-Key`, `env_var=JPCITE_API_KEY`, `anonymous_fallback.per_day_per_ip=3`。
- API 側との一致確認:
  - `api/main.py:1547` で CORS allowlist に `X-API-Key`, `X-CSRF-Token` 含む。
  - `api/main.py:1825, 2556`: OpenAPI / docs strings で「`X-API-Key: am_…` 」を明示。
  - `api/anon_limit.py:563`: `request.headers.get("x-api-key")` で読み取り (lower-case で受ける = HTTP header の case-insensitive 仕様一致)。
  - `mcp.json` の `Authorization: Bearer` 互換は宣言されていないが、`api/anon_limit.py:564-568` は **Bearer も実装側で受け付け**ている。これは「宣言が控えめ / 実装が緩い」方向の drift で、互換性的に害なし。
- 残課題: 厳密一致を求めるなら `mcp.json` 側に `Authorization: Bearer` の補助記述を追加。現状でも red ではない。

---

## 集計

| 判定 | 件数 | 項目 |
| --- | --- | --- |
| green | 4 | 1, 6, 7, 8 |
| yellow | 2 | 2, 5 |
| red | 2 | 3, 4 |

合計 8 / 8 件。

## red の deploy gate 影響度

1. **Item 4 (magic-link 未配線)**: deploy 直後の magic-link login flow が **404 で死ぬ**。pricing → checkout → key → dashboard の paid path は機能するが、「メアド入れてログイン」UX (input 仕様で要求されたもの) は本番で **動かない**。最優先で `api/me/__init__.py` に新 router を export + `main.py` で include_router 2 行追加。
2. **Item 3 (`billing_address_country=JP` 未強制)**: 海外居住の顧客が Checkout を通過できてしまう。Stripe Tax で輸出 0% にレートが寄ると JCT 10% 取りこぼし → インボイス制度 / 消費税申告が不整合。memory「JP only」と矛盾。`extra["billing_address_collection"] = {"allowed_countries": ["JP"]}` の追加で OK。

## yellow の運用 risk

- **Item 2**: `STRIPE_PORTAL_RETURN_URL` は dunning メール用 fallback にのみ injection、portal 起動 API は caller-supplied `return_url` 依存。allowlist で安全に倒れているが「env 1 箇所で集中管理」要件は未充足。
- **Item 5**: 新 `billing_webhook_idempotency.py` + migration 205 が定義のみで consumer なし。実 dedup は migration 053 の `stripe_webhook_events` が担っているので機能不全はないが、コード base に未使用 helper / 二重 schema が残る。

## 制約遵守確認

- 既存 .py / .html / .json への **修正は一切行っていない** (read のみ)。
- 提案部は全て「audit 結果 + 残課題 1 行」形式で記述し、実コード変更 / commit / push なし。
- 「solo + zero-touch」「¥3/req metered, JP only」「破壊なき整理整頓」原則に違反する提案は含まない。

---

(audit by Claude Code, 2026-05-11, read-only audit pass, file paths absolute)
