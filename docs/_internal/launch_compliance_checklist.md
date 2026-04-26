# Pre-launch Compliance Checklist (JP payment + consumer law gate)

最終更新: 2026-04-23 / Launch target: **2026-05-06**

本書は Stripe live mode を ON にし、DNS を本番 machine へ切り替える前に通す最後のゲートである。各項目に `[ ]` を付け、`what / how / owner` の 3 カラムで進める。`autonomath.ai` は商標リブランド決着後に確定する (`project_jpintel_trademark_intel_risk.md` 参照、現在コード中に `autonomath.ai` がハードコードされているのは全て要置換)。

凡例: `you` = 梅田 / `ops` = 同上 operator hat / `lawyer` = 弁護士レビュー / `外注` = 外部委託。

---

## 1. Stripe live account readiness

- [ ] **Business profile** — 事業者名・所在地・業種 (SaaS)。個人事業主なら Sole proprietor 選択。`dashboard.stripe.com/settings/account` / owner: you
- [ ] **Bank account (JPY payout + prenote)** — 円口座登録、Stripe が ¥1 prenote 送信し 2-3 営業日で確認。Settings → Payouts / owner: you
- [ ] **Identity verification** — マイナンバーカード / 運転免許証 / パスポートのいずれかを KYC に提出。Settings → Verifications / owner: you
- [ ] **Tax ID (インボイス T-号)** — 取得後 Settings → Tax → Tax IDs に `jp_trn` で追加。未取得なら国税庁 e-Tax `https://www.nta.go.jp/taxes/shiraberu/zeimokubetsu/shohi/keigenzeiritsu/invoice.htm` から申請、通常 2 週間リード。未取得なら §3 フォールバック参照 / owner: you
- [ ] **Products & prices — 1 metered price** — `AutonoMath per-request` product 配下に ¥3/req, `tax_behavior=exclusive`, `recurring.usage_type=metered`, `aggregate_usage=sum`, `lookup_key=per_request_v3` で作成。price ID を `STRIPE_PRICE_PER_REQUEST` env に投入 (`config.py`)。旧 3-tier (`plus/pro/business`) Price + legacy `per_request_v1` (¥0.5) / `per_request_v2` (¥1) は archive 済 / owner: you
- [ ] **Customer Portal** — subscription update / cancel / payment method update / invoice history 全 ON。TOS・Privacy URL を Business info に登録し config ID を `STRIPE_BILLING_PORTAL_CONFIG_ID` へ (`config.py:34`)。Settings → Billing → Customer portal / owner: you
- [ ] **Webhook endpoint** — `https://autonomath.ai/v1/billing/webhook` に 5 event (`customer.subscription.created` / `invoice.paid` / `invoice.payment_failed` / `customer.subscription.updated` / `customer.subscription.deleted`) を購読。signing secret を `STRIPE_WEBHOOK_SECRET` に投入。`stripe-signature` 検証は `api/billing.py` 実装済 / owner: you
- [ ] **Radar baseline** — CVC / 住所 / 3DS2 既定ルールが有効かを確認、変更しない / owner: you
- [ ] **Stripe CLI test** — test mode で `stripe listen --forward-to http://localhost:8000/v1/billing/webhook` → 別 shell で `stripe trigger invoice.paid` → `api_keys` に 1 行発行されるか目視 / owner: you

---

## 2. 特商法 32 条 — `site/tokushoho.html` disclosure

現状 `site/tokushoho.html` は DRAFT バナー + `[要確定]` が 6 箇所残存。live mode 前に全て埋める。all owner: you unless noted.

- [ ] 事業者名 (line 54), 代表者氏名 (58), 運営責任者 (62) の 3 `[要確定]`
- [ ] 適格請求書発行事業者登録番号 (line 65) → §1 / §3 完了後に T + 13 桁記入
- [ ] 所在地 (line 69) — 「請求あり次第、遅滞なく開示」特例は個人事業主で可。ただし **Stripe live account 登録住所と整合必須**。バーチャルオフィス採用なら実受取テストを 1 回。
- [ ] 電話番号 (line 73) — 同開示特例可。請求から 3 営業日以内の応答運用を整える。
- [ ] DRAFT バナー (line 44) 撤去
- [ ] 販売価格整合性 (line 80-88) — §1 の metered ¥3/req と完全一致していること (税別明記)
- [ ] tos.html `[管轄裁判所 — 要確定]` (`tos.html:104`) — 個人事業主なら住所所在地裁判所を記載
- [ ] **lawyer レビュー** — 32 条必須 8 項目 (事業者名 / 住所 / 電話 / 販売価格 / 支払方法 / 引渡時期 / 返品特約 / 連絡先メール) テンプレは全部存在。launch 前 1 時間の法律相談を通す / owner: lawyer

---

## 3. インボイス制度 (適格請求書) — 2023-10 施行済、2026-04 時点必須

詳細は `research/stripe_jct_setup.md` (canonical)。以下は実行チェックのみ。all owner: you unless noted.

- [ ] T-号 登録 (§1 と同項)
- [ ] `jp_trn` type で `POST /v1/tax_ids` → `invoice_settings.default_account_tax_ids` に attach
- [ ] `INVOICE_FOOTER_JA` env に `"適格請求書発行事業者登録番号: T__________"` (`config.py:33`)、PDF の top + footer 両印字を test カード 1 件で目視
- [ ] 消費税法 57-4 の 5 項目 (登録番号 / 取引年月日 / 適用税率 / 税率ごと消費税額 / 交付事業者名) を test mode PDF で目視確認。`STRIPE_TAX_ENABLED=true` で税額は自動
- [ ] **フォールバック** (T-号 launch 間に合わず時) — `tokushoho.html` に「発行事業者登録申請中」明示、経過措置 (2026-09 まで 80% / 2029-09 まで 50% 控除) を B2B に通知 / owner: you + lawyer

---

## 4. 消契法 8 条 / 8 条の 2 — 免責条項の有効性

- [ ] **tos.html 8 条 免責** (`tos.html:87-92`) — 現行文言は第 4 項で「消費者 (消契法 2 条 1 項) の場合は 8 条・8 条の 2 に反する限度で適用しない」とガードレール済。文言維持。NG パターン (全部免責) を Grep 残存 0 件で最終確認 / owner: you
- [ ] **sla.md "best effort"** (`sla.md:58`) — 和文には全部免責表現無し (99.0% target + 除外 6 項目のみ)。消契法 8 条 2 項抵触なし、維持可 / owner: you
- [ ] **Checkout 前 TOS 同意** — `api/billing.py:65-74` に `consent_collection={"terms_of_service": "required"}` 追加、Dashboard → Settings → Checkout に TOS URL `https://autonomath.ai/tos.html` 登録 / owner: you
- [ ] **pricing.html の導線** — footer に 3 legal リンクあり、checkout ボタン近傍にも 1 回明示 / owner: you
- [ ] lawyer レビュー (免責条項の実効性) / owner: lawyer

---

## 5. APPI 17-18 / 28 条 — 個人情報取扱

- [ ] **3rd-party 提供 (17-18 条)** — `privacy.html:76-82` に Stripe / Fly.io / Sentry 記載済。**Cloudflare Pages** (fallback DNS + 静的配信、`fallback_plan.md` 実装あり) を追記 / owner: you
- [x] **保存期間整合** — 2026-04-23 reconciliation: 顧客面の公約は `privacy.html` 第 6 条「API 利用ログ 90 日」で確定 (既存の `conversion_funnel.md:64, 223` とも一致)。code 側の `usage_events` cleanup cron は W6 `POST_DEPLOY_PLAN_W5_W8.md` でこの 90 日を実装する。旧 spec の "30 日" 記述は本書から削除、privacy.html 90 日が唯一の canonical / owner: you
- [ ] **28 条 外国移転** — `privacy.html:84-91` 第 4 条の 2 の包括同意 + PPC 一覧リンクはテンプレ適合。相当措置の具体名 (Stripe Japan K.K. 国内 entity、Fly / Sentry / Cloudflare SCC) を 1 行追記推奨 / owner: you + lawyer
- [ ] **開示・削除請求 SLA** — `privacy.html` 第 7 条の窓口 `hello@autonomath.ai` の応答 SLA (最大 2 週間) を internal runbook に明記 / owner: you

---

## 6. DNS / domain / TLS final checks

`autonomath.ai` は商標レビュー待ち (`project_jpintel_trademark_intel_risk.md`)。以下は placeholder、確定値で `.github/workflows/tls-check.yml:27` を置換。all owner: you.

- [ ] **Primary CNAME → Fly** — `autonomath.ai` apex を Fly A/AAAA or proxied CNAME、flip 48h 前に TTL 30-60s 短縮
- [ ] **Backup (Cloudflare Pages)** — `autonomath.ai-fallback.pages.dev` warm 確認、`.github/workflows/pages-preview.yml` Actions グリーン
- [ ] **MX / SPF / DKIM / DMARC** — `hello@autonomath.ai` 送受信。`dig MX/TXT`、`_dmarc` に `v=DMARC1; p=quarantine`、Gmail / Outlook に test 送信し 3 Pass
- [ ] **TLS auto-renew** — `.github/workflows/tls-check.yml` で日次、<10 日 Slack alert。現 `DOMAIN_PLACEHOLDER` のため skip 中。rebrand 後に確定値置換 + `workflow_dispatch` で green 確認

---

## 7. Kill-switch rehearsal (`docs/fallback_plan.md`)

owner: you, target 全工程 10 min 以内。

- [ ] Dry-run 6 step: (1) `flyctl status` (2) staging で `flyctl scale count 0` で擬似障害 (3) Cloudflare DNS `@` を `autonomath.ai-fallback.pages.dev` CNAME に差し替え (4) `site/status.html` の `active` class を `.state.down` に移動→push→Pages redeploy (5) `curl -I https://autonomath.ai/` で Cloudflare `cf-ray` header 確認 (6) `fallback_plan.md` Recovery § 逆順で復旧
- [ ] 各 step の所要秒数を `docs/launch_war_room.md` に時刻付きで追記
- [ ] `flyctl scale count 1` で本番復帰、`status.html` を `.state.ok` に戻す

---

## Summary — scheduling

| Deadline | Item |
|---|---|
| **TODO by 2026-05-01** | §1 Bank verification / Identity / T-号 申請 (2 週間リード) / Webhook endpoint / Radar baseline / Products&Prices / §2 tokushoho.html 5 `[要確定]` / §2 tos.html 管轄 / §3 T-号 登録 or フォールバック文言 / §4 Stripe Checkout の `consent_collection` 追加 / §5 privacy.html 90 日 canonical 維持 + code 側 cleanup cron / §6 rebrand 決着後の DOMAIN 置換 / lawyer 1h レビュー予約 |
| **TODO by 2026-05-05** | §1 Stripe CLI test / §3 PDF 実サンプル目視 / §4 tos.html grep 全部免責 0 件 / §5 Cloudflare 追記 / §6 MX/SPF/DKIM/DMARC 送信テスト / §6 tls-check.yml DOMAIN 置換 / §7 kill-switch dry-run |
| **Can defer post-launch** | §5 外国移転 相当措置 1 行追記 (推奨) / §3 custom PDF generator (Stripe PDF に未採用時) / §6 Backup domain 二次ドメイン化 / SLA クレジット制度 (beta 明け) |

---

## Top 3 launch blockers (2026-04-23 時点で未解決なら 5/6 に間に合わない)

1. **商標リブランド (DOMAIN 未決定)** — `autonomath.ai` は Intel 著名商標衝突懸念 (`project_jpintel_trademark_intel_risk.md`)。AutonoMath へのリネームを採用済だが、`site/*.html`、`tls-check.yml`、mailto、meta og:url の一括置換が残存する可能性あり。2026-04-23 時点で `autonomath.ai` へ大部分移行済、grep で `autonomath.ai` 参照が残っていないか最終確認。
2. **T-号 (適格請求書) 確認** — Bookyou 株式会社 **T8010001213708** (令和7年5月12日登録済) を使用。残タスクは Stripe Dashboard に登録 + `tokushoho.html` / `privacy.html` / invoice footer への記載反映のみ。
3. **Pivot 後の pricing 整合性** — 2026-04-23 pivot: 3-tier (`plus/pro/business`) → pure metered (¥0.5/req 税別) へ。`site/pricing.html` / `tokushoho.html` / `docs/pricing.md` 更新済。Stripe 側は `STRIPE_PRICE_PER_REQUEST` (`lookup_key=per_request_v1`, `tax_behavior=exclusive`, metered) 1 本のみ live 登録、旧 Price は archive。
