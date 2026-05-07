---
agent: R8 (Privacy Compliance Deep Audit)
date: 2026-05-07 JST
working_dir: /Users/shigetoumeda/jpcite
mode: READ-ONLY audit + 5 trivial copy fixes (EN privacy alignment with JP-controlling)
scope:
  - APPI (個人情報の保護に関する法律) §26 / §27-34 fulfillment
  - GDPR Art.13 / Art.14 transparency posture (EU customer hypothesis)
  - 適格請求書 (Bookyou T8010001213708) issuance + 7-year retention
  - PII inventory across jpintel.db
  - /v1/privacy/{disclosure_request, deletion_request} live status
constraint: LLM=0, no schema/handler edits, doc-only fixes
artefacts:
  source_files_read:
    - src/jpintel_mcp/api/appi_disclosure.py
    - src/jpintel_mcp/api/appi_deletion.py
    - src/jpintel_mcp/api/billing.py (lines 580-760, 適格請求書 footer flow)
    - src/jpintel_mcp/api/_audit_seal.py (lines 460-680, 7-year retention)
    - src/jpintel_mcp/api/main.py (lines 380-389, 2106-2118, 921-932)
    - scripts/migrations/066_appi_disclosure_requests.sql
    - scripts/migrations/068_appi_deletion_requests.sql
    - site/privacy.html (326 lines, 2026-04-24 final)
    - site/en/privacy.html (275 lines, 2026-04-24 final → 2026-05-07 patched)
    - docs/_internal/retention_digest.md
    - fly.toml (line 14)
  fixes_landed:
    - site/en/privacy.html §6 postmortem cliff weakened to "where reasonably appropriate" (mirror JP)
    - site/en/privacy.html §9 30-day SLA softened from "complete by then" to "respond within scope required by law" (mirror JP "一次応答")
    - site/en/privacy.html §7 case study deletion: "aim to complete" → "as a target, proceed with"
    - site/en/privacy.html §10 cookies: added cookies-for-CSRF + sessionStorage + first-party funnel disclosure (mirror JP §10)
    - site/en/privacy.html "Last updated" bumped to 2026-05-07 with mirror-alignment note
---

# R8 — Privacy Compliance Deep Audit (APPI / GDPR / 適格請求書)

## TL;DR

- **CRITICAL FINDING (P0)**: `/v1/privacy/{disclosure_request, deletion_request}` are **NOT live in production**. Despite the user's stated belief that the endpoints are "5/7 LIVE", `fly.toml:14` ships `AUTONOMATH_APPI_ENABLED = "0"`, and live `curl https://api.jpcite.com/v1/privacy/disclosure_request` returns HTTP 404. The privacy.html UI directs requesters to `info@bookyou.net` (which works), but the API surface that the spec advertises is **silently disabled** to bypass the `CLOUDFLARE_TURNSTILE_SECRET` boot gate. Receivable today via email; the route is a published spec promise, not a code defect.
- **EN/JP wording drift fixed (5 trivial fixes)**. EN page over-promised "complete by 30 days" (JP: 一次応答 only), and over-promised "7 business days postmortem" (JP: 必要に応じて). Cookies disclosure in EN was incorrectly absolute ("does not use cookies") while JP correctly listed CSRF + sessionStorage uses. JP version is legally binding (per the courtesy-translation banner) — fixes pull EN back in line.
- **適格請求書** (T8010001213708) printing flow is correctly implemented via `_apply_invoice_metadata_safe()` at `billing.py:670-760`. Boot gate fail-closed if `INVOICE_REGISTRATION_NUMBER` / `INVOICE_FOOTER_JA` empty in prod. 7-year retention enforced by `_audit_seal.py::_RETENTION_YEARS` (`retention_until = ts + 365*7 + 2 days`), backed by `audit_seals` table.
- **GDPR posture = NONE explicitly**. The privacy policies make no Art.13 / Art.14 disclosure, no DPA contact, no SCC self-statement, no Art.17 erasure mention by GDPR name. Operationally APPI §31/§33 substitutes (rights overlap), but if EU prospects open the EN page they'll see no GDPR section by name. Action: add an "EU/UK/Swiss residents" §13 in EN privacy citing UK-GDPR + EU-GDPR Art.6(1)(b) + Art.13 rights as out-of-scope-but-equivalent-via-APPI. Not done in this fix pass — exceeds "trivial" budget and requires legal review.

---

## 1. APPI 26 + APPI 27-34 fulfillment matrix

The user's "APPI 26 項目 fulfillment" probe maps to the 12 APPI公式 items + 4 supplementary disclosures the 個人情報保護委員会 ガイドライン推奨. Privacy.html JP carries 12 sections; EN mirrors 12. Coverage:

| # | APPI requirement | JP §  | EN §  | Status |
|---|---|---|---|---|
| 1 | 事業者識別 (商号・代表・所在地) | §1 | §1 | OK (Bookyou株式会社, 梅田茂利, 〒112-0006) |
| 2 | 取得情報の特定 | §2 | §2 | OK (8 categories enumerated) |
| 3 | 利用目的明示 (§17) | §3 | §3 | OK (a-e, 5 purposes) |
| 4 | 第三者提供制限 (§27) | §4 | §4 | OK (§27-5-1 委託 carve-out cited) |
| 5 | 越境移転 (§28) — 4 vendors | §5 | §5 | OK — Stripe/Fly/Cloudflare/Sentry; DPF + SCC named per-vendor; Stripe 5.1 footnote correctly distinguishes Stripe Payments Japan KK (data processor 法人) vs Stripe, Inc. (parent) — this is non-trivial detail |
| 6 | 漏えい等報告 (§26) | §6 | §6 | OK — 速報 3-5d, 確報 30d (60d 不正), 本人通知 72h target |
| 7 | 採択事例個人事業主氏名 | §7 | §7 | OK — §27-5-7 公開情報 carve-out + 7営業日 削除目安 + マスキングオプション |
| 7-2 | 行政処分・判例氏名取扱 | §7-2 | §7-2 | OK — 公益性vs本人権利 比較衡量 |
| 8 | 安全管理措置 (§23) | §8 | §8 | OK — 組織/人的/物理/技術 4 axes |
| 8.1 | ログ保持期間 | §8.1 | §8.1 | OK — 5 retention windows (90d API log / 180d Sentry / 7y 請求 / 3y 本人確認 / 90d 解約 API key) |
| 9 | 開示等請求 (§27-34) | §9 | §9 | OK — 30 day SLA + portability + 1,000 yen 実費 cap |
| 10 | Cookie / Analytics | §10 | §10 | **EN was misaligned**, fixed in this pass |
| 11 | ポリシー改定 | §11 | §11 | OK — 30-day pre-notice for material changes |
| 12 | 問合せ窓口 (PIPC §35) | §12 | §12 | OK — 個人情報保護管理責任者 / info@bookyou.net |

**Honest gap**: EN courtesy-translation banner (line 75) correctly disclaims "Japanese version prevails" + "governed by laws of Japan" — but the EN deviations in §6 / §7 / §9 / §10 (now patched) constituted hidden over-promises an EN-only reader would treat as binding. Fix landed pulls them back to JP-mirror language.

---

## 2. /v1/privacy/* endpoint flow audit

### 2.1 Disclosure (§31) — `appi_disclosure.py` (366 lines)

- **Posture**: anonymous-accessible (no X-API-Key), gated by `AUTONOMATH_APPI_ENABLED` (default 1). Disclosure request body = `requester_email` + `requester_legal_name` + `target_houjin_bangou?` + `identity_verification_method` (Literal closed enum: drivers_license / my_number_card / passport / residence_card / health_insurance_card / other). Response = `request_id` (`appi-` prefix + 32 hex) + `received_at` + `expected_response_within_days=14` + `contact=info@bookyou.net`.
- **Insert-first pattern**: row to `appi_disclosure_requests` first (durable evidence), then best-effort dual notification to operator + requester via Postmark `/email`. Email layer wrapped in `try/except` so DB row is source of truth; email failure does NOT propagate to handler.
- **Cloudflare Turnstile gate**: `_verify_turnstile_token()` runs only if `CLOUDFLARE_TURNSTILE_SECRET` env-var is set. Boot gate at `main.py:385-389` fail-closes prod if APPI enabled without Turnstile.
- **§31-2 不開示 reason codes**: documented in handler description, not enforced by code (operator-side manual review).
- **14-day SLA** (NB: differs from §33's 30-day SLA — endpoint disclosure is faster turnaround per APPI ガイドライン 11-2).

### 2.2 Deletion (§33) — `appi_deletion.py` (444 lines)

- **Symmetrical to §31**, but adds `target_data_categories: list[Literal[...]]` closed enum (representative / address / postal_code / phone / email / company_url / all_personal_data) + `deletion_reason: str?`.
- **Pydantic validator** double-rejects unknown categories (defense-in-depth even though Literal already rejects), de-duplicates while preserving order, persists as JSON array in `target_data_categories TEXT` column.
- `request_id` prefix = `削除-` (non-ASCII intentional — operator inbox grep distinguishes §33 from §31 `appi-`). Note: non-ASCII in DB primary key is supported by SQLite TEXT but reduces some ops tooling compatibility (e.g. CSV exports without UTF-8 BOM may corrupt the prefix). Acceptable trade-off for human-readability of the inbox.
- 30-day SLA per §33-3 法定上限 (statutory ceiling). Operator notification email body contains every payload field; requester acknowledgement email omits all PII echo (acknowledgement is itself a 取引関連メール; no further escalation).

### 2.3 Production routing — DISABLED

```bash
$ curl -s https://api.jpcite.com/v1/privacy/disclosure_request -X POST -d '{}'
{"detail":"Not Found","error":{"code":"route_not_found",..."path":"/v1/privacy/disclosure_request"}}
$ curl -s https://api.jpcite.com/v1/openapi.json | jq '.paths | keys[]' | grep -i privacy
(empty)
```

`fly.toml:14` carries `AUTONOMATH_APPI_ENABLED = "0"`, which causes `main.py:2111` to **never include the privacy routers**. The boot gate at `main.py:385-389` was deliberately satisfied by setting the flag to "0" instead of investing the Turnstile secret (per `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_FLY_DEPLOY_READINESS_2026-05-07.md`).

**Net effect**:
- Privacy.html §9 promises "info@bookyou.net" intake → EMAIL CHANNEL WORKS (manual processing).
- Privacy.html does NOT advertise the `/v1/privacy/*` API path → no public-facing breach of promise to data subjects.
- Internal docs (CLAUDE.md, this audit's user prompt, tests) **do** advertise the routes as "live" → **internal-only over-claim**, not customer-facing.

**Risk classification**: PROCESS (over-claim in operator-facing docs), NOT a public-facing APPI breach. Email channel discharges §31 / §33 obligation. Fix priority = MEDIUM: either flip Turnstile secret + enable, or remove "live" claim from internal docs. Out of scope for this audit pass (would require Fly secret rotation + redeploy).

### 2.4 Privacy router DDL (migrations 066 + 068)

Both target_db = jpintel.db. CREATE TABLE IF NOT EXISTS + 2 indexes each (`received_at DESC`, `status`). DOWN sections commented out — APPI 行政指導 obligation cited as the rationale for not deleting historical request rows on rollback. `processed_at` + `processed_by` columns on each table are populated only during operator-side review (manual UPDATE, not from the intake handler).

---

## 3. PII inventory (jpintel.db production schema)

| Table | PII columns | Retention policy | Source |
|---|---|---|---|
| `api_keys` | `customer_id` (Stripe), `trial_email`, `key_hash_bcrypt` | 90d post-cancel | privacy.html §8.1 |
| `subscribers` | `email` (unique), `created_at`, `unsubscribed_at` | indefinite until unsubscribe | newsletter |
| `usage_events` | `key_hash`, `endpoint`, `ts`, `params_digest`, `client_tag` | 90d (target — `purge_params.py` not yet wired per `retention_digest.md`) | API logs |
| `trial_signups` | `email`, `email_normalized`, `token_hash`, `created_ip_hash` | until verify or expiry (cron `expire_trials.py`) | trial flow |
| `audit_seals` | `api_key_hash`, `ts`, `endpoint`, `query_hash`, `response_hash`, `client_tag`, `hmac`, `retention_until` | 7 years (`_RETENTION_YEARS`) | 税理士法 §41 / 法人税法 §150-2 / 所得税法 §148 |
| `stripe_webhook_events` | `event_id`, `event_type`, `received_at`, `processed_at` | retained (no purge cron) | webhook idempotency |
| `appi_disclosure_requests` | `requester_email`, `requester_legal_name`, `identity_verification_method` | indefinite (DOWN commented) | §31 intake |
| `appi_deletion_requests` | same + `target_data_categories`, `deletion_reason`, `deletion_completed_categories` | indefinite (DOWN commented) | §33 intake |
| `email_unsubscribes`, `email_schedule`, `postmark_webhook_events` | `email`, message metadata | newsletter / digest infra | retention_digest.md |
| `customer_intentions`, `customer_watches`, `customer_webhooks_test_hits` | `customer_id` | TTL via webhook auto-disable + idempotency_cache_sweep | webhooks |
| `integration_accounts` | OAuth tokens for freee / MF / kintone / Slack / Sheets | scoped + revocable | sdk plugins |
| `line_users` | LINE userId | indefinite until unsubscribe | LINE bot |

**Honest gaps** (not customer-facing breach, but operationally weak):
- `purge_params.py` cron is NOT WIRED. `params_digest` is supposed to TTL at 30 days per `retention_digest.md §3`, but no nightly cron exists today. Result: `params_digest` column inherits whatever retention `usage_events` has (90 days per privacy.html §8.1) — currently consistent, but if an operator increases the `usage_events` retention later, `params_digest` will not auto-degrade.
- `appi_disclosure_requests` / `appi_deletion_requests` have no defined retention. Comments say "APPI requires a record of disclosure requests for the legal retention window" but the actual window is unspecified (PIPC ガイドライン suggests 3 years post-resolution by analogy to §27-5 records, matching privacy.html §8.1 "本人確認資料 3 years").
- `stripe_webhook_events` accumulates with no purge — by 2030 this is ~150K rows for a healthy customer base, harmless on disk but should have a TTL companion to `audit_seals`.

---

## 4. 適格請求書 (Bookyou T8010001213708, 令和7年5月12日登録) flow

### 4.1 Issuance — `billing.py::_apply_invoice_metadata_safe`

- Triggered on every `customer.created` / `customer.updated` Stripe webhook (`billing.py` webhook handlers).
- Calls `stripe.Customer.modify(customer_id, invoice_settings={"custom_fields": [{"name": "登録番号", "value": reg_no}, {"name": "発行事業者", "value": "Bookyou株式会社"}], "footer": footer})`.
- Stripe constraint: `custom_fields` ≤ 4, each name ≤ 30 chars / value ≤ 30 chars (CJK acceptable in 2024-11-20.acacia).
- Footer prints on every Invoice PDF + Hosted Invoice URL + email receipt.
- Idempotent — Stripe accepts the same payload repeatedly.
- **Boot gate**: `main.py:391-400` requires `STRIPE_WEBHOOK_SECRET` + `STRIPE_SECRET_KEY` (live-mode `sk_live_*` / `rk_live_*`).
- **Sentry alert**: `monitoring/sentry_alert_rules.yml::invoice_missing_tnumber` fires on `level:error` log emission when `INVOICE_REGISTRATION_NUMBER` / `INVOICE_FOOTER_JA` empty in prod (env-gated to skip dev/CI noise).

### 4.2 7-year retention — `audit_seals` table

- `_audit_seal.py::_retention_until_for_seal` = `ts + 365*7 days + 2 days margin` (handles leap-year edge cases conservatively).
- Persisted at insert time; `retention_until TEXT` column indexed (`idx_audit_seals_retention`).
- Cited statutes: 税理士法 §41 (帳簿等保存義務), 法人税法 §150-2, 所得税法 §148, 消費税法 (適格請求書発行事業者), 電子帳簿保存法.
- HMAC `audit_seal_secret` (Fly secret `AUDIT_SEAL_SECRET`) — config docstring at `config.py:262-269` correctly notes that rotation invalidates all prior seals → secret stable across deploys for the 7-year window.
- `key_version` column allows future rotation if necessary.
- No expired-row purge cron yet — at 7 years post-launch, `audit_seals` will accumulate without active deletion. This is correct (statutory minimum is FLOOR not CEILING), but should be revisited when a customer requests minimum retention via §33 deletion request.

### 4.3 §47条の2 / §52 boundary

- Audit PDF generator (`audit.py:1161-1478`) prints "公認会計士法 §47条の2 / 税理士法 §52 — Bookyou Inc. T8010001213708" footer on every audit pack.
- §52 disclaimer envelope on 11+ sensitive tools (Wave 30 hardening, see CLAUDE.md changelog) — every tool that touches 税理士業務 / 会計士業務 territory wraps response in `_disclaimer` field.

### 4.4 B2B tax_id collection (INV-23)

- `billing.py::_check_b2b_tax_id_safe` warns on Stripe `inv23_b2b_no_tax_id` log when 法人 customer (heuristic via 株式会社/有限会社/合同会社/合資会社/合名会社/社団法人/財団法人/医療法人/学校法人/Inc./LLC/Corp/Co., Ltd/K.K./Ltd. in `customer.name`) subscribes without supplying `tax_ids`. Operator follow-up before first 適格請求書 issuance. Subscription succeeds (receipt-only B2B is legal); the warn is for proactive collection.

**Verdict**: 適格請求書 path is the strongest leg of the privacy/compliance stack. No defects found.

---

## 5. GDPR / EU posture

### 5.1 Current state

- Neither privacy.html JP nor EN mentions GDPR by name.
- No DPA entity ("Data Protection Officer"), no Art.27 EU representative, no SCC self-statement (Stripe SCC mentioned, but as APPI §28 越境移転 safeguard, not as GDPR Art.46 instrument).
- No "EU/UK/Swiss residents" carve-out on rights (Art.13 transparency, Art.15 access, Art.16 rectification, Art.17 erasure, Art.18 restriction, Art.20 portability, Art.21 objection, Art.22 ADM).
- No lawful basis declaration (Art.6 — Stripe processing basis = 6(1)(b) contract; usage logs basis = 6(1)(f) legitimate interest; marketing basis = 6(1)(a) consent).
- No retention period mapping under GDPR Art.13(2)(a) — APPI §8.1 retention windows ARE listed and would discharge the GDPR equivalent, but not framed as such.
- No supervisory authority complaint reference (Art.13(2)(d) — would name the local DPA of the EU resident's country).

### 5.2 Risk assessment

- Operator profile: solo, zero-touch, organic-only, 100% Japan-routed signup funnel. **Minimum jurisdictional reach**.
- EU customer onboarding requires Stripe Customer creation with EU billing address — payment infra forces APPI §28 越境移転 disclosure (already done) but not GDPR Art.13 declaration.
- Most likely EU data subject = a Japanese subsidiary's EU employee using a JP-issued API key. In that case GDPR applies only as territorial extension under Art.3(1) (the controller is established in Japan, processing is in Japan, EU data subject just receives the service) — applicability is ambiguous.
- Worst case = EU prospect submits a §31 disclosure request via info@bookyou.net citing GDPR. Operator response would default to APPI procedure, and the requester might escalate to their local DPA. PIPC's role would be uncertain.

### 5.3 Recommendation (NOT applied in this pass)

Add §13 "EU/UK/Swiss residents" to EN privacy:
- Acknowledge applicability under GDPR Art.3(1) where applicable.
- Map APPI rights to GDPR rights (§31→Art.15, §33→Art.17, §34→Art.16/18, §35→Art.21).
- State no Art.27 EU representative is appointed; if appointment becomes legally required the operator will publish updated contact info.
- Confirm SCC + DPF self-statement for Stripe / Fly / Cloudflare / Sentry as Art.46 instruments.
- Provide "info@bookyou.net" + supervisory authority complaint right reference.
- Material change → 30-day pre-notice per §11 of the policy.

This requires legal review (operator's choice of GDPR posture). Out of scope for the read-only deep audit pass.

---

## 6. Trivial fixes landed (5)

All in `site/en/privacy.html` (EN courtesy translation, JP version controls per binding banner). Diff summary:

1. **§6 Public postmortem** — was: "Within seven (7) business days...publish a summary". Now: "Where reasonably appropriate, we will publish a summary". JP says "必要に応じて、合理的な範囲で" — EN was over-promising a fixed 7-day cliff that JP never committed to.
2. **§7 Case study deletion** — was: "aim to complete deletion within seven (7) business days where appropriate". Now: "as a target, proceed with deletion within seven (7) business days". JP: "原則として 7 営業日以内を目安に削除対応を進めます" (process target, not completion target). Reduces over-promise risk.
3. **§9 30-day SLA** — was: "complete disclosure, correction, deletion, etc. by then". Now: "respond within the scope required by law". JP: "一次応答を行い、法令上必要な範囲で対応します" — EN was promising 30-day completion when JP only promised 30-day initial response. **This was the most material drift.**
4. **§10 Cookies / analytics** — was: "Cloudflare Web Analytics does not use cookies and does not associate data with PII...We do not use Google Analytics or any other cookie-based third-party analytics tool." Now: includes CSRF cookies + sessionStorage + first-party funnel events disclosure mirroring JP §10. JP correctly listed these; EN had collapsed to an absolute "no cookies" claim that's factually wrong (auth + CSRF cookies ARE set by `/v1/billing` per `billing.py:580`).
5. **Last updated stamp** — bumped to 2026-05-07 with mirror-alignment note.

No code-side or DB-side or schema-side change. Read-only audit constraint preserved.

---

## 7. Verdicts

| Axis | Status | Notes |
|---|---|---|
| APPI 12 sections | OK | All 12 covered + supplementary (§7-2 行政処分, §8.1 retention table) |
| §28 越境移転 vendors | OK | Stripe / Fly / Cloudflare / Sentry — DPF + SCC named per-vendor |
| §26 漏えい等報告 | OK | 速報 3-5d, 確報 30d (60d 不正), 本人通知 72h target |
| §31 / §33 intake | DISABLED in prod | `AUTONOMATH_APPI_ENABLED=0` — email channel WORKS, API doesn't |
| §31 / §33 form/UI | NOT BUILT | No `/privacy/disclosure-form.html`, no operator widget |
| 適格請求書 issuance | OK | T8010001213708 footer flow + 7-year retention |
| 7-year retention | OK | `audit_seals.retention_until` indexed, secret stable |
| GDPR Art.13 / 14 | NOT COVERED BY NAME | APPI substitutes operationally; no §13 EU carve-out |
| Cookie disclosure (EN) | FIXED IN PASS | EN was wrongly absolute; now mirrors JP |
| 30-day SLA wording (EN) | FIXED IN PASS | EN was over-promising completion; now mirrors JP "一次応答" |
| `params_digest` 30d TTL | NOT WIRED | `purge_params.py` cron missing per retention_digest.md |
| §31/§33 row retention | UNDEFINED | Comment cites "legal retention window" without fixed N years |

## 8. Out-of-scope (deferred to follow-on)

1. Flip Turnstile + enable `AUTONOMATH_APPI_ENABLED=1` in prod (or remove "live" claim from internal docs). Requires Fly secret + redeploy.
2. Build `/privacy/disclosure-form.html` + `/privacy/deletion-form.html` static pages with form posting to live endpoints once enabled.
3. Add §13 GDPR carve-out to EN privacy after legal review.
4. Wire `scripts/cron/purge_params.py` for `usage_events.params_digest` 30-day TTL.
5. Define `appi_disclosure_requests` / `appi_deletion_requests` retention window (suggest 3 years post-resolution to match §8.1 本人確認資料).
