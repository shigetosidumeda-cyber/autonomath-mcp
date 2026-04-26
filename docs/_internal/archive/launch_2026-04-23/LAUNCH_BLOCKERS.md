# Launch Blockers (2026-04-23 現在)

Launch target: **2026-05-06**. This file is the MINIMAL set that blocks paid-customer launch. Everything else is nice-to-have.

Memory rule: 最小 5-8 本のみを本番 gate にする (`feedback_completion_gate_minimal`).

---

## B1. Rename (商標出願 なし) — task #44

- **方針 (2026-04-23 梅田判断)**: 商標登録は **しない**. 「Intel」衝突は rename のみで回避 (memory: `feedback_no_trademark_registration`).
- **Why blocks**: 新しい製品名 が決まらないと、DNS / Stripe Connect metadata / MCP registry 8 箇所の submit / Postmark From ヘッダ / TLS cert / OpenAPI title / README / 全 126 箇所の docs placeholder が固まらない.
- **Owner action**:
  1. 新 brand 名を決める (候補は過去メモに3案: `JPI Data` / `jpinst` / `JGI`. 梅田が別候補でも可)
  2. ドメインを 1 本取る (e.g. `jpinst.dev` / `jpi-data.jp`)
  3. `scripts/rebrand_mcp_entries.sh --to <NEW_NAME> --apply` を実行 (AI 側で一括置換、弁理士関与なし)
- **Lead time**: 名前決定 10min + ドメイン登録 10min + 置換 CI通過 60min. **1日以内**で完了可能.
- **商標登録 はやらない**. 将来売上が立って他社が抜け駆けリスクが現実化したら再考.

## ~~B2. T-号 (インボイス事業者登録番号)~~ ✅ 解消 (2026-04-23)

- **状態**: 既に登録済 — **T8010001213708** (Bookyou 株式会社 / 令和7年5月12日登録).
- **一次資料**: `/Users/shigetoumeda/Desktop/インボイス登録番号＿bookyou.pdf` (国税庁適格請求書発行事業者公表サイト)
- **公表サイト確認 URL**: https://www.invoice-kohyo.nta.go.jp/regno-search/detail?selRegNo=8010001213708
- **所在地**: 東京都文京区小日向2丁目22番1号
- **残り作業** (blocker ではないが launch 前に):
  - `site/tokushoho.html` の「適格請求書発行事業者登録番号」欄に `T8010001213708` を埋める
  - `site/privacy.html` の「事業者」欄に `Bookyou 株式会社 / 上記所在地` を埋める
  - Stripe ダッシュボード「事業者情報」に同番号を入れる
  - `docs/stripe_tax_setup.md` 内の「申請中」表記を T号 に置換
- memory: `project_bookyou_invoice`

## ~~B3. Data integrity — 5件の偽/placeholder URL~~ ✅ 解消 (2026-04-23)

`scripts/fix_url_integrity_blockers.py --apply` で 8 column patches を 1 tx で適用.
`scripts/url_integrity_scan.py` → **violations: 0 / 6771 programs**.

| unified_id | 元の問題 | 修正後 URL |
|---|---|---|
| UNI-e33d7b0613 | 捏造 `example.com/kujihara_yuuki_shinseisho.pdf` | `https://www.kuriharacity.jp/w018/030/030/yuukikikaisien/PAGE000000000000008075.html` (栗原市公式、FY2026 更新確認済) |
| UNI-47b67cba4a | `/...` placeholder | `https://www.town.yokohama.lg.jp/index.cfm/6,999,18,134,html` (横浜町公式、index 経由確認) |
| UNI-b0b9565569 | 同上 (noukaweb dupe) | 同上 |
| UNI-81c7fb2813 | 切れた `https://w` in enriched_json quote | `https://www.pref.tottori.lg.jp/64862.htm` (既に source_url で clean) |
| UNI-d8aa2870e3 | 全角スラッシュ `／` in enriched excerpt | `betsukai-kenboku.jp/` + space normalize (PDF excerpt artifact) |

- UNI-e33d7b0613 row-corruption 懸念: primary_name / authority / prefecture / municipality は全て「宮城県栗原市」で内部一貫していた. 修正は URL 差し替えのみで十分、再 ingest 不要と判定.
- UNI-47b67cba4a / UNI-b0b9565569 は noukaweb 由来の duplicate row. dedup は別 task に切り出す (launch gate ではない).
- **CI guard**: `.github/workflows/data-integrity.yml` が nightly + PR で再発防止.
- `source_url_corrected_at` column 追加 (2026-04-23T06:33:51Z), 今後の監査用.

## B4. Staging deploy (task #25)

- **Why blocks**: 本番は staging で 72h 健康だった後のみ。まだ未 deploy.
- **Owner action**: `flyctl launch --no-deploy` → secrets → `flyctl deploy --strategy rolling`.
- **Blocks on**: B1 (rename で 正しい app name が決まる) + 下記 Stripe live secrets.

### Stripe — launch 前に必要な secrets (4 本)

本番の Stripe ダッシュボードで live mode に切り替え、以下を `flyctl secrets set` で Fly.io に登録:

| env var | 取得場所 |
|---|---|
| `STRIPE_SECRET_KEY` | Dashboard → Developers → API keys → Secret key (**live mode**, `sk_live_…`) |
| `STRIPE_WEBHOOK_SECRET` | Dashboard → Developers → Webhooks → エンドポイント作成後に表示される `whsec_…` (live 用を別に作る) |
| `STRIPE_PRICE_PER_REQUEST` | Products → "Per-request metered" (¥0.5 / req, tax_behavior=exclusive, lookup_key=`per_request_v1`) の price id (`price_…`) |
| `STRIPE_BILLING_PORTAL_CONFIG_ID` | Billing → Customer portal → Save したあとの config id (`bpc_…`) |

加えて **Stripe 側の設定**:
- 「事業者情報」に **T8010001213708 / Bookyou 株式会社 / 東京都文京区小日向2-22-1** を入力
- JCT (日本消費税) を有効化 → `STRIPE_TAX_ENABLED=true` も env にセット
- ロケール ja / 自動税計算 / tax id collection / 住所収集 は `src/jpintel_mcp/api/billing.py` 側で既に ON 済
- `customer.subscription.created` + `invoice.paid` + `invoice.payment_failed` + `customer.subscription.deleted` + `customer.subscription.updated` の 5 event を webhook subscribe

test mode の keys は `.env.example` / CI 用のみで、live 鍵は Fly secret に直接セット (repo には絶対コミットしない).

## ~~B5. 3-tier 価格整合~~ ✅ 解消 (2026-04-23 pure metered pivot)

- 3-tier (Plus/Pro/Business) 廃止. 単一の metered price (`¥0.5/req` 税別) に統合.
- site/pricing.html / tokushoho.html / index.html / docs/faq.md / docs/api-reference.md 全て pure metered 反映済.
- memory: `project_autonomath_business_model`.

---

## 確認済で通過 (blocker 解除済)

- WCAG 2.1 AA + 障害者差別解消法 2024-04: `docs/accessibility_audit.md` (a11y 監査 2026-04-23)
- APPI 28条 第三者移転開示: Cloudflare / Postmark / Stripe all listed in `site/privacy.html`
- 消契法 8/8-2 guardrail: `site/tos.html` 責任限定 文言 修正済
- ToS consent on Checkout: `consent_collection={"terms_of_service": "required"}` in `billing.py`
- Stripe locale=ja: 適用済
- Security headers + CSP: `src/jpintel_mcp/api/main.py` middleware
- Anon rate limit (100/day per IP): `src/jpintel_mcp/api/anon_limit.py`, router-dep wired
- 165 tests passing + CI green + coverage audit in progress
- Observability: Sentry + structlog + /readyz + /healthz + TLS monitoring
- Docs: MkDocs `--strict` builds 29 pages clean
- MCP registries: 6 viable submissions drafted (blocked on B1)
- 採択事例 PoC: 事業再構築 17,931 行、W5 ingest 即起動可.
- Onboarding D+0 welcome: `src/jpintel_mcp/email/onboarding.py` (Wave 10 で D+3/7/14/30 追加中).

---

**Rule**: このファイルに 1 項目でも未解決がある = launch 不可.
