# Stripe Tax + JCT + インボイス 本番投入手順

最終更新: 2026-04-23 / Launch target: **2026-05-06** (`docs/launch_compliance_checklist.md` §1, §3 の実務版)

本書は Dashboard 側でやる作業を順番に並べたランブック。コード側 (`src/jpintel_mcp/api/billing.py` の Checkout Session に `automatic_tax / tax_id_collection / billing_address_collection`) はすでに投入済み。残りは **オーナー (梅田)** の Dashboard 操作。

canonical 設計: `research/stripe_jct_setup.md` (repo-internal)。本書と食い違ったら research 側が一次。
compliance ゲート: [`docs/_internal/launch_compliance_checklist.md`](launch_compliance_checklist.md)。

---

## 0. 結論 (TL;DR)

- 2026-04-25 v3 改訂: pure metered 1 Price (`¥3 / unit 税別`, `tax_behavior=exclusive`, `lookup_key=per_request_v3`, live `price_1TPw8sL3qgB3rEtw4GyG4DHi`) のみ。旧 3-tier (`plus/pro/business`) + legacy `per_request_v1` (¥0.5) / `per_request_v2` (¥1) は archive 済。
- 税別表示 (外税) を採用。消費税法 63 条 総額表示義務は **消費者向け B2C** が対象。AutonoMath は開発者向け API (B2B) のため税別+自動請求で OK。landing の pricing 表示には "税別" を明記。
- Stripe Tax を有効化しないと `automatic_tax` が動かない → コードは常に `automatic_tax={"enabled": True}` を送るので、本番切替時に必ず Dashboard で Stripe Tax を Activate する。
- T-号 (適格請求書発行事業者登録番号) は **国税庁に 2 週間リード**。既に T8010001213708 (Bookyou 株式会社、令和7年5月12日登録) が登録済 → Stripe Dashboard に反映するだけ。

---

## 1. Stripe Tax の有効化

**Dashboard → Settings → Tax → "Enable Stripe Tax"**

1. `Settings → Tax` を開く。
2. "Activate Stripe Tax" をクリック。
3. 事業形態 (Sole proprietor / Company) を選択。Bookyou 株式会社として **Company**。
4. 規約同意して Save。

## 2. Origin (原産地) = 日本 の登録

Stripe Tax で **最重要**。origin=JP でないと、Stripe は AutonoMath を **foreign seller** 扱いし、JP→JP が「輸出 0%」に誤判定される。

1. `Settings → Tax → Registrations` を開く。
2. "Add a registration" → Country **Japan** → Type **Standard**。
3. 事業所住所 (Bookyou 株式会社、東京都文京区小日向2-22-1。`tokushoho.html` と完全一致させる)。
4. Tax code (製品分類): SaaS は `txcd_10000000` "General — Services, Digital services"。
5. Effective date = 課税事業者登録の効力発生日 (令和7年5月12日、T8010001213708 取得日)。

## 3. Price の `tax_behavior` 確認 (metered ¥3/billable unit)

**これが一番ミスりやすい**。Price は `tax_behavior` を一度決めたら変更できない。誤ったら新しい Price を作って env を差し替え。

### 3-1. 既存 Price の検証

Dashboard → `Products` → `AutonoMath per-request` を開く。右側 "Prices" の該当行をクリック → "Tax behavior" が以下のとおりか確認:

| env var                     | 単価 (税別)  | 消費税 (10%, Stripe 自動計算) | `tax_behavior`  | Billing mode |
|-----------------------------|--------------|------------------------------|-----------------|--------------|
| `STRIPE_PRICE_PER_REQUEST`  | ¥3 / unit     | ¥0.30 / req (外税)           | `exclusive`     | Metered (legacy `usage_records`, `aggregate_usage=sum`) |

`lookup_key=per_request_v3` で固定 (live: `price_1TPw8sL3qgB3rEtw4GyG4DHi` per `docs/_internal/COORDINATION_2026-04-25.md`)。pivot 以前の `STRIPE_PRICE_PLUS/PRO/BUSINESS` および legacy `per_request_v1` (¥0.5) / `per_request_v2` (¥1) は **archive 済**。

CLI で確認する場合:

```
stripe prices retrieve price_1TPw8sL3qgB3rEtw4GyG4DHi --api-key sk_live_... | jq '{tax_behavior, billing_scheme, recurring}'
```

`"exclusive"` + `"per_unit"` + `recurring.usage_type=metered` でなければ 3-2 へ。

### 3-2. 誤りがあった場合のやり直し

1. Dashboard → `Products` → `AutonoMath per-request` を選択。
2. "Add another price" で新しい Price を作成:
   - Billing: Recurring / Monthly / **Usage is metered** (legacy `usage_records` の "Sum of usage values" を選択)
   - Price: ¥3 per unit
   - Currency: JPY
   - **"Include tax in price"** は OFF (= `tax_behavior=exclusive`)
   - lookup_key: `per_request_v3`
3. 旧 Price は "Archive" する (既存 subscriber の更新だけ生きる)。
4. Fly env を更新: `flyctl secrets set STRIPE_PRICE_PER_REQUEST=price_NEW`
5. 再デプロイ確認。

### 3-3. 税別 vs 税込 — 請求書にどう載るか

コードは **exclusive 前提** (pure metered, B2B)。想定される invoice line は以下:

**exclusive (本番構成)** — 10,000 req を ¥3/billable unit で月次請求:
```
AutonoMath per-request × 10000    ¥30,000
Subtotal:                          ¥30,000
Tax (消費税 JP 10%):               ¥3,000
Total:                             ¥33,000
```

**inclusive (誤設定時、やってはいけない)** — ¥3 を税込扱い:
```
AutonoMath per-request × 10000    ¥30,000
  (Tax included ¥2,727)
Total:                             ¥30,000
```

metered 商品を inclusive にすると Total が税込固定になり、利益が常に 10% 目減りする。必ず exclusive。

## 4. 売主 T-号 (適格請求書発行事業者登録番号) の Dashboard 登録

前提: Bookyou 株式会社は **T8010001213708** (令和7年5月12日登録) を既に取得済。

1. Dashboard → `Settings → Business → Tax IDs` (Tax details ではなく **Business details** の下)。
2. "Add tax ID" → Country **Japan** → Type `Japan Tax Registration Number (jp_trn)` → `T8010001213708` を入力。
3. Save。
4. 同 `Settings → Billing → Invoice template` (または `Invoice settings`) → "Default account tax IDs" に作った jp_trn を **チェック** (これで PDF ヘッダに T-号が印字される)。
5. 同画面 "Default footer" に belt-and-suspenders 用の文字列を貼る:
   ```
   適格請求書発行事業者登録番号: T8010001213708
   ```
6. Fly env `INVOICE_REGISTRATION_NUMBER` / `INVOICE_FOOTER_JA` にも同じ値を入れておく (コードからの参照は現時点ゼロだが env 整合性チェック用)。

## 5. 通貨 (JPY) の取り扱い — レポートと実請求の区別

Stripe Dashboard のデフォルトレポートは **USD 換算** (Stripe 社の "Presentment currency" 設定) で表示されるため、`Overview` で「¥5,000 が $33 と表示されている」と誤認しやすい。**請求されるのは JPY、入金も JPY**。

- `Dashboard → Reports` の右上 currency selector で **JPY** を選択する (個人設定として保存される)。
- Payout は Settings → Payouts で設定した JPY 銀行口座に入る (`docs/launch_compliance_checklist.md` §1 Bank verification)。
- Invoice PDF の通貨は **Price の currency**。`jpy` で作成した Price は `¥` プレフィックス + 整数 (JPY は minor unit なし)。metered 上の ¥3 は internally `unit_amount=3` で保持 (整数)。legacy `per_request_v1`/`v2` (¥0.5 / ¥1) は archive 済。

## 6. Checkout Session 側の設定 (コード — 既に投入済)

`src/jpintel_mcp/api/billing.py` の `create_checkout` は常に以下を送る:

- `line_items=[{"price": settings.stripe_price_per_request}]` — quantity を送らない (metered は subscription 作成時に 0)。
- `automatic_tax={"enabled": True}` — Stripe が消費税 10% を自動計算。
- `tax_id_collection={"enabled": True}` — JP B2B 顧客が自分の T-号を入力可能。
- `billing_address_collection="required"` — Stripe Tax が国判定に使う。
- `consent_collection={"terms_of_service": "required"}` — 特商法導線 (既存)。
- `locale="ja"` (既存)。
- `mode="subscription"` + `subscription_data` は省略 (Price の recurring 設定が metered の月次を自動適用)。

**env 手順** (Fly.io live):
```
flyctl secrets set \
  STRIPE_PRICE_PER_REQUEST=price_1TPw8sL3qgB3rEtw4GyG4DHi \
  STRIPE_API_VERSION=2024-11-20.acacia \
  STRIPE_BILLING_PORTAL_CONFIG_ID=bpc_1TPAI0L3qgB3rEtwDm85NMUQ \
  STRIPE_WEBHOOK_SECRET=whsec_REDACTED \
  INVOICE_REGISTRATION_NUMBER=T8010001213708 \
  INVOICE_FOOTER_JA='適格請求書発行事業者登録番号: T8010001213708'
```

`STRIPE_API_VERSION` は legacy `usage_records` を使うため `2024-11-20.acacia` に pin (新しい Meter API 移行は別イシュー)。

## 7. T-号 の確認

既に **T8010001213708** (Bookyou 株式会社、令和7年5月12日登録) を取得済。Dashboard に未反映なら §4 の手順で登録。

cross-link: `docs/launch_compliance_checklist.md` §1 `Tax ID (インボイス T-号)` + §3 インボイス制度。

## 8. Smoke test (本番切替 30 分以内)

1. test mode で先に一度通す。Dashboard を `Test mode` に切替。
2. Checkout URL を作成 → 3DS2 test card `4000 0025 0000 3155` で決済。
3. 入力欄に以下が出ることを目視:
   - Billing address (country + postal code) → **required** になっているか。
   - "Tax ID (optional)" → 入力欄あり、jp_trn を試し打ちできるか。
   - Total 行に `¥0.00 due today` (metered は初回 ¥0)。
4. Subscription が作成されたら:
   - `POST /v1/billing/webhook` が `customer.subscription.created` を受け、API key が発行される (最速経路)。
   - 遅れて `invoice.paid` (¥0 の初回 invoice) が来ても同 subscription_id なので **idempotent** (key は二重発行されない)。
5. 次に `GET /v1/programs/search` を API key 付きで 10 回叩き、`stripe.SubscriptionItem.create_usage_record` が Dashboard → Billing → Usage に 10 件計上されているか確認。
6. 翌月の month-end で ¥30 (10 req × ¥3) + 消費税 ¥3 = ¥33 の invoice が自動 finalize されるかを sandbox clock で前倒し検証。
7. test mode OK なら `Test mode` を off にして live mode で自分で 1 req (¥3) だけ叩いて月末請求を待つ → 翌月 refund。

---

## 参照
- `research/stripe_jct_setup.md` — canonical 設計 (repo-internal)。
- [`docs/_internal/launch_compliance_checklist.md`](launch_compliance_checklist.md) — 全体ゲート。§1 Stripe / §3 インボイス。
- `src/jpintel_mcp/api/billing.py` — Checkout Session コード。
- `src/jpintel_mcp/billing/stripe_usage.py` — metered usage fire-and-forget reporter。
- `src/jpintel_mcp/config.py` — env 定義 (`STRIPE_PRICE_PER_REQUEST` ほか)。
- `tests/test_billing_tax.py` — Checkout Session が正しいタックス param を送っていることのテスト。
