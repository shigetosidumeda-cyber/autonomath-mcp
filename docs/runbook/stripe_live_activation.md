---
title: Stripe live mode activation runbook
updated: 2026-05-07
operator_only: true
category: deploy
---

# Stripe live mode activation runbook

Operator-facing one-shot procedure for flipping the Stripe account from
test mode → live mode. This is **legal contract activation** — Bookyou株式会社
(T8010001213708) attests business identity, tax registration, and bank
ownership against Stripe's KYC. Cannot be delegated to AI agents per
`docs/_internal/stripe_tax_setup.md` §1.

> Working hypothesis: jpcite metered billing already runs end-to-end in
> test mode (`STRIPE_SECRET_KEY=sk_test_...`, webhook firing into
> `/v1/billing/webhook`). Live activation flips the dashboard, then we
> swap two Fly secrets (sk_test → sk_live, whsec_test → whsec_live) and
> re-verify the 5 webhook events arrive signed.

Cross-references:
- `docs/runbook/secret_rotation.md` — `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` rotation steps (Step 3 of initial provisioning).
- `docs/_internal/stripe_tax_setup.md` — Stripe Tax registration (separate operator step, runs **after** activation).
- `docs/runbook/stripe_meter_events_migration.md` — metered billing API migration when Stripe deprecates `usage_records`.

## Prerequisites — gather before opening Dashboard

Pre-collect into 1Password / operator keystore so the activation form
fills in one sitting (Stripe times out partial drafts after ~30 min):

| Field | Source | Value pattern |
|---|---|---|
| 法人番号 (Corporate Number) | National Tax Agency | `8010001213708` (13 digits, no T prefix in this field) |
| 適格請求書番号 (T-bangou) | NTA invoice registry | `T8010001213708` |
| 法人名 (Legal name, kanji) | 履歴事項全部証明書 | `Bookyou株式会社` |
| 法人名 (Legal name, kana) | 履歴事項全部証明書 | `ブックユーカブシキガイシャ` |
| 法人名 (Legal name, romaji) | 履歴事項全部証明書 | `Bookyou Co., Ltd.` |
| 設立日 | 履歴事項全部証明書 | YYYY-MM-DD |
| 代表者氏名 | 履歴事項全部証明書 | 梅田 茂利 |
| 代表者生年月日 | 運転免許証 | YYYY-MM-DD |
| 代表者住所 | 運転免許証 (現住所) | full 都道府県 + 市区町村 + 番地 + 建物 |
| 本店所在地 | 履歴事項全部証明書 | 東京都文京区小日向2-22-1 |
| 業種 (Industry / MCC) | self-classified | **5734 — Computer Software Stores** (or 7372 — Prepackaged Software). Stripe MCC list: <https://docs.stripe.com/connect/setting-mcc>. AI / API resale falls under 5734 most cleanly; 7372 acceptable alternative. |
| 主要事業内容 (Business description) | composed | "API resale of Japanese government program data + MCP server for AI agents. Metered ¥3 per request, no subscription tiers." |
| Public-facing site | live | `https://jpcite.com` |
| Statement descriptor (≤ 22 chars) | composed | `JPCITE` (paired with full descriptor `JPCITE-MCP` per R7-OPS) |
| Customer support email | operator inbox | `info@bookyou.net` |
| Customer support phone | operator | (must be answerable; Stripe sometimes verifies) |
| Bank account (JPY payouts) | Bookyou 法人口座 | 銀行名 / 支店名 / 口座種別 / 口座番号 / 口座名義 (カナ) |
| Estimated monthly volume | conservative | "¥0 — ¥1,000,000 / month, average ¥3 per transaction" |
| Estimated avg transaction | exact | `¥3` (¥3.30 税込) |
| Refund / cancellation policy URL | live | `https://jpcite.com/legal/refund` |
| Terms of service URL | live | `https://jpcite.com/legal/terms` |
| Privacy policy URL | live | `https://jpcite.com/legal/privacy` |

Verify the 3 legal URLs return HTTP 200 from a clean browser session
**before** opening the activation form — Stripe scrapes them during
review and 4xx can stall activation by days.

## Step-by-step: Stripe Dashboard activation

1. Sign in at <https://dashboard.stripe.com/> with the operator account
   bound to `info@bookyou.net`. Confirm 2FA + recovery codes are
   accessible (printed copy in operator keystore per R7-OPS §A).
2. Top-left environment toggle: confirm currently shows **Test mode**.
3. Click "Activate account" banner (or Settings → Account → Account
   information → "Complete account activation").
4. Form section "Business details":
   - Country: Japan
   - Business type: **Company** (株式会社)
   - Legal entity name (Japanese): `Bookyou株式会社`
   - Legal entity name (kana): `ブックユーカブシキガイシャ`
   - Legal entity name (romaji, English-character): `Bookyou Co., Ltd.`
   - Corporate number (法人番号): `8010001213708`
   - Date of incorporation: from 履歴事項全部証明書
   - Registered business address: 東京都文京区小日向2-22-1
   - Business website: `https://jpcite.com`
   - Industry / MCC: `5734 — Computer Software Stores`
   - Product description: pre-composed string above.
5. Form section "Representative details":
   - Full name (kana + kanji + romaji as separate fields)
   - Date of birth, gender (Stripe asks)
   - Home address (must match 運転免許証 — Stripe verifies via 公的書類)
   - Mobile phone number
   - Email: `info@bookyou.net`
   - Identity verification: upload 運転免許証 (front + back) or マイナンバー
     カード (face + back). Avoid 健康保険証 — Stripe rejects PII-redacted
     copies.
6. Form section "Banking details":
   - Account holder name (kana, full-width). Mismatched name vs 法人口座 →
     payouts fail microdeposit.
   - 銀行名 + 支店名 + 支店コード (3 桁) + 口座種別 (普通 / 当座) + 口座番号 (7 桁)
   - Stripe sends a microdeposit (¥1) → operator confirms by entering the
     amount within 7 days, or payouts stay paused.
7. Form section "Statement descriptor":
   - Full descriptor: `JPCITE-MCP`
   - Short / dynamic descriptor: `JPCITE`
   - Customer support phone: Bookyou main line.
8. Submit. Stripe sends a verification email; click through, then the
   form moves to "Pending review". Approval typically lands in 1-3
   business days. Activation **does not** require approval to retrieve
   live API keys — they are minted at submit; the account just cannot
   accept payments until approval.

## Step-by-step: webhook re-mount (post-activation)

Once Dashboard shows "Live mode" toggle as enabled:

1. Live-mode toggle on. Settings → Developers → Webhooks.
2. Click "Add endpoint". Endpoint URL:
   `https://api.jpcite.com/v1/billing/webhook`
3. Description: `jpcite billing webhook (live)`.
4. Events to send — select exactly these **5 events** (must match
   `src/jpintel_mcp/api/billing.py` event-type dispatch at L1320-1539):
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.paid`
   - `invoice.payment_failed`

   Optional but already handled (do **not** add unless we want them
   firing — current handlers are no-op stubs): `invoice.created`,
   `invoice.updated`, `invoice.voided`, `customer.subscription.trial_will_end`.

5. After save, Stripe shows the signing secret (`whsec_...`). Copy once;
   Stripe will not re-display.
6. Mint into Fly:
   ```bash
   fly secrets set STRIPE_WEBHOOK_SECRET="whsec_LIVE_..." -a autonomath-api
   fly secrets set STRIPE_SECRET_KEY="sk_live_..." -a autonomath-api
   # restricted live key recommended; full secret only when mass migrations need it.
   ```
   Watch boot log for `production secret gate passed (§S2)`. Both
   secrets are §S2-gated — boot fails closed if either is missing.
7. Smoke: from Stripe Dashboard → Webhooks → endpoint → "Send test
   webhook" → pick `customer.subscription.created`. Confirm receiver
   responds 200 within 5 seconds. If 401 → signature mismatch (the live
   `whsec_` was not deployed correctly). If 422 → livemode mismatch
   (`stripe.webhook.livemode_mismatch` log line — we are still on
   `sk_test_*`).
8. Repeat the test-webhook send for the other 4 events; confirm each
   produces a `stripe.webhook.duplicate_ignored` log line on second
   delivery (event_id dedup via `stripe_webhook_events` table works).

## Common gotchas

- **The activation form auto-saves drafts but the draft expires after
  ~30 min idle.** Pre-collect every field above before opening it.
- **Statement descriptor is locked once approved.** Changing later
  requires re-review (~1-3 days). Choose carefully — `JPCITE-MCP` is
  the agreed brand surface.
- **MCC mis-classification triggers Stripe Risk review.** AI / API
  resale at the 5734 vs 7372 boundary is fine; resist the Risk team
  suggesting 6051 (financial services) — that pulls in additional
  KYC tiers we do not need.
- **Microdeposit verification window is 7 days.** Miss it and the bank
  account gets unbonded; payouts stay paused until re-verified.
- **Do not pass `consent_collection={"terms_of_service": "required"}`
  in Checkout Session creation in live mode** — see CLAUDE.md "Common
  gotchas". Use `custom_text.submit.message` for ToS link.
- **Stripe Tax activation is a separate step.** Run
  `docs/_internal/stripe_tax_setup.md` §1-§2 **after** account
  activation lands. Order matters — Tax cannot be added to a
  not-yet-activated account.
- **The 5-event list is intentionally minimal.** Adding extra events
  (e.g. `charge.succeeded`, `payment_intent.succeeded`) does not crash
  but creates noise — every unhandled event still hits the dedup
  insert and gets `200 OK; etype not handled` logged. Keep the
  endpoint clean.

## Verification checklist (post-activation, before announcing)

- [ ] Stripe Dashboard top-right shows "Live mode"
- [ ] Webhook endpoint shows 5 events, all green delivery in last hour
- [ ] `fly secrets list -a autonomath-api` shows `STRIPE_SECRET_KEY` +
      `STRIPE_WEBHOOK_SECRET` updated_at within last 30 min
- [ ] Boot log shows `production secret gate passed (§S2)`
- [ ] Test transaction (real ¥330) fired from a personal card resolves
      to a real `invoice.paid` webhook delivery → `api_keys.tier`
      promotion → refund the ¥330 from Dashboard
- [ ] `docs/_internal/stripe_tax_setup.md` §1-§2 queued as next operator
      action (Stripe Tax depends on activation)
