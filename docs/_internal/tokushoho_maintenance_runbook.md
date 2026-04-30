# 特商法表示 Maintenance Runbook

**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26

Operator-only — do not link from public docs. Excluded from mkdocs build via
`exclude_docs: _internal/` (`mkdocs.yml`).

**Scope**: Maintenance of 特定商取引法 (特商法) 第 32 条 mandated
disclosures across all customer-facing surfaces. Covers 6-month review
cadence, change procedures for 法人 information drift (operator address
change, 代表 change, 法人 移転, T-号 update), and contact-info
synchronization across HTML pages, contracts, and Stripe metadata.

For the broader pre-launch compliance posture, see
`launch_compliance_checklist.md` §2.

For consumer inquiry handling, see `operators_playbook.md` §9.1.

---

## 1. Why this runbook exists

特商法 § 32 requires Japanese consumer-facing online services to disclose
8 mandatory items:

1. 事業者名 (legal entity name)
2. 所在地 (legal entity address — physical, not P.O. Box)
3. 電話番号 (phone — open-by-request acceptable for sole proprietors / 法人)
4. 販売価格 (price)
5. 支払方法 (payment method)
6. 引渡時期 (delivery timing)
7. 返品特約 (return / refund policy)
8. 連絡先メール (email)

Items 1, 2, 3, 8 carry **operator obligation** — they identify who to
contact. Drift between the displayed value and reality (e.g. operator
moves house but `tokushoho.html` still shows old address) is a 違反
under 特商法 § 14 (誇大広告等) interpreted broadly + 消費者契約法 § 3
(信義則).

Drift is the most common compliance failure for solo operators. Causes:

- 法人 移転 (Bookyou 株式会社 changes 本店 address)
- 代表 個人 incidence (operator moves residence — affects 開示請求の
  receiving address even if 法人本店 unchanged)
- 電話番号 change (operator changes carrier or number)
- T-号 (適格請求書発行事業者登録番号) — should not change once issued
  but updates trigger displayed-value review
- バーチャルオフィス subscription lapse (if used)

This runbook prevents drift through scheduled review + change-event
discipline.

---

## 2. Surfaces that display 特商法 contact info

Every change must propagate to all of these. Missing any one creates
drift.

### 2.1 HTML pages (Cloudflare Pages, auto-deploy from main)

| Path | Audience | Required content |
| --- | --- | --- |
| `/site/tokushoho.html` | JP consumers (primary) | All 8 items per § 32 |
| `/site/en/tokushoho.html` | EN consumers (parity) | Translated, semantically identical |
| `/site/docs/compliance/tokushoho/index.html` | mkdocs build output | Generated; verify post-build |
| `/site/privacy.html` | All users | Operator name + address (not all 8 items) |
| `/site/en/privacy.html` | EN users | Same |
| `/site/tos.html` | All users | Operator name + email + 管轄裁判所 |
| `/site/en/tos.html` | EN users | Same |
| Site footer (every page, generated via template `_partials/footer.html`) | All users | © Bookyou株式会社 (T8010001213708) · info@bookyou.net |

### 2.2 Contracts and templates

| Location | Required content |
| --- | --- |
| Stripe Customer Portal Business info | Bookyou株式会社, info@bookyou.net |
| Stripe Tax ID registration | T8010001213708 |
| Stripe public business profile (`statement_descriptor`) | "AUTONOMATH" or similar (must match 事業者名 indirectly) |
| Postmark sender identity (`info@bookyou.net`) | Verified domain |
| Email templates in `templates/` (welcome, refund, deletion) | Sender footer with 事業者名 + 住所 |
| Server-side `_response_models.py` `_disclaimer` field | Bookyou株式会社 attribution where applicable |
| `pyproject.toml` author / maintainer | Bookyou (or operator personal email — currently mixed) |
| `package.json` (npm SDKs) | Same |

### 2.3 Auxiliary disclosures

| Location | Required content |
| --- | --- |
| GitHub org profile (Bookyou) | Verified domain + contact email |
| MCP registry submissions (`server.json`, smithery.yaml, dxt manifest) | `author.name` + `author.email` |
| PyPI package metadata | Author + email |
| npm package metadata | Same |

---

## 3. 6-month review schedule

The first review is anchored to the launch date (2026-05-06 + 6 months
= 2026-11-06). Subsequent reviews every 6 months: 2027-05-06,
2027-11-06, etc.

Set calendar reminders 7 days in advance.

### Step 1. Pull canonical reference values

Open this runbook + `CLAUDE.md` as the source of truth. Canonical values
as of 2026-04-26:

```
事業者名: Bookyou株式会社
適格請求書発行事業者番号: T8010001213708
代表者: 梅田茂利
所在地: 〒112-0006 東京都文京区小日向 2-22-1
電話番号: 請求あり次第、遅滞なく開示
メール: info@bookyou.net
T-号 (適格請求書): T8010001213708 (令和7年5月12日登録)
管轄裁判所: 東京地方裁判所
```

If any of these have changed since last review, follow §4-§7 for the
specific change type, then continue with the review.

### Step 2. Run the canonical-value grep

```bash
# JP HTML
grep -rE "Bookyou|T8010001213708|info@bookyou\.net|文京区小日向|梅田茂利|東京地方裁判所" \
  /Users/shigetoumeda/jpintel-mcp/site/ \
  --include="*.html" \
  -l

# EN HTML
grep -rE "Bookyou|T8010001213708|info@bookyou\.net|Bunkyo-ku|Umeda Shigetoshi" \
  /Users/shigetoumeda/jpintel-mcp/site/en/ \
  --include="*.html" \
  -l

# Templates and metadata
grep -rE "Bookyou|T8010001213708|info@bookyou" \
  /Users/shigetoumeda/jpintel-mcp/templates/ \
  /Users/shigetoumeda/jpintel-mcp/pyproject.toml \
  /Users/shigetoumeda/jpintel-mcp/server.json \
  /Users/shigetoumeda/jpintel-mcp/smithery.yaml \
  /Users/shigetoumeda/jpintel-mcp/dxt/manifest.json \
  -l 2>/dev/null
```

For each file in the output, open and verify the displayed values match
the canonical reference. Especially check for:

- Old / outdated address (pre-移転 if any move occurred)
- Stale phone numbers
- Missing T-号 from invoice footer
- Inconsistent 事業者名 spelling (e.g. "Bookyou Inc." vs "Bookyou株式会社"
  — only the 株式会社 form is the legally registered name)
- Hardcoded domain `jpcite.com` vs `bookyou.net` mix-ups

### Step 3. Verify Stripe Dashboard alignment

1. Stripe Dashboard → Settings → Business settings → Public details
   - Statement descriptor: "AUTONOMATH"
   - Public business name: "Bookyou株式会社"
   - Support address, phone, email: match canonical
2. Settings → Tax → Tax IDs: T8010001213708 listed as active
3. Settings → Billing → Customer portal → "Business information"
   section: address + email match

If any drift: update in Stripe Dashboard. No code change needed (Stripe
fetches at render time).

### Step 4. Verify TLS / DNS / domain registrations

Domain registrar (1Password item `domain_registrar`) should list the
WHOIS contact as Bookyou株式会社 / info@bookyou.net. WHOIS privacy is
fine; the underlying contact must be current.

```bash
whois bookyou.net
whois jpcite.com
```

If contact has drifted (rare unless 法人 moved), update via registrar
control panel.

### Step 5. Review consumer inquiry log for SLA compliance

Open `research/consumer_inquiries/`. Last 6 months. For each inquiry:

- 1次応答 within 3 営業日 (per `operators_playbook.md` §9.1)?
- 完了応答 within stated SLA?
- Inquiry root cause: was it a 特商法 disclosure issue? (if so, fix
  the disclosure, not just the response)

### Step 6. Document the review

Append to `research/tokushoho_reviews.log`:

```
2026-11-06 | scheduled | drift_found=0 | files_audited=12 | inquiries_reviewed=3 | next_review=2027-05-06 | operator=umeda
```

If `drift_found > 0`:

```
2026-11-06 | scheduled | drift_found=2 | files_audited=12 | drift_files=site/en/tokushoho.html,templates/welcome.md | resolution_pr=#1234 | inquiries_reviewed=3 | next_review=2027-05-06 | operator=umeda
```

### Step 7. Confirm calendar reminder for next review

Verify next-review date is on the operator's calendar. If using Google
Calendar / equivalent, the recurring 6-month event should already be
scheduled. If not, set it.

---

## 4. Change event: 法人本店 移転

Bookyou株式会社 changes 本店 address (e.g. moves out of 文京区小日向 2-22-1).

This is a high-impact event because it affects:

- 法人登記簿 (commercial registry)
- 国税庁 適格事業者登録 (T-号 may not change but address registered with
  T-号 must update)
- Stripe Business profile
- All HTML displays
- Customer-facing contracts (no auto-update mechanism)

### Step 1. Complete the legal移転 first (司法書士)

1. 株主総会決議 (取締役会のみで可能な場合あり、定款による)
2. 移転登記申請 (旧本店 → 新本店、移転日から 2 週間以内、商業登記法 §
   915)
3. 司法書士 経由が現実的、登録免許税 ¥30,000

Do **not** update HTML before 登記完了 — there is a window where the
displayed address must match the registered address.

### Step 2. Update 国税庁 / 税務署 / 都税事務所

1. 異動届出書 を 移転日から 1 ヶ月以内 に 旧管轄税務署 + 新管轄税務署
   に提出 (eLTAX 経由可)
2. 都税事務所 (法人都民税) にも同様
3. 適格請求書発行事業者の登録事項変更 — 国税庁 e-Tax → 「変更届出」
   → 新住所登録。T-号 自体は不変。

### Step 3. Update Stripe Dashboard

Stripe Dashboard → Settings → Business settings → Public details →
Business address → update to new address. Save.

Stripe will re-validate the address asynchronously (1-3 business days).
During validation, payouts may be temporarily held — plan the change for
a low-revenue window if possible.

### Step 4. Update HTML files

Edit:
- `site/tokushoho.html` line ~69 (所在地)
- `site/en/tokushoho.html` corresponding line
- `site/privacy.html` (operator address mention)
- `site/en/privacy.html` same
- `site/_partials/footer.html` (if footer shows address)

Use Edit tool to change `〒112-0006 東京都文京区小日向 2-22-1` →
new address with new postal code. Verify with the canonical-value grep
in §3 Step 2.

### Step 5. Update templates and metadata

- `pyproject.toml` author address (if present)
- `templates/welcome.md` and other email templates that include sender
  address
- `templates/refund_full.md`, `templates/refund_prorated.md`,
  `templates/refund_denied.md`
- `templates/data_correction_acknowledged.md`
- `server.json` author address (if present)

### Step 6. Run mkdocs build to refresh generated docs

```bash
mkdocs build --strict
```

Verify `site/docs/compliance/tokushoho/index.html` reflects new address.

### Step 7. Deploy

```bash
git add -A
git commit -m "chore(tokushoho): 法人本店移転に伴う住所更新 (旧→新)"
git push origin main
```

Cloudflare Pages auto-deploys in 30-60s.

### Step 8. Notify users (optional but recommended)

If the address change is significant (e.g. 移転 between 都道府県), send
a one-shot email to all paying customers via Postmark Broadcast:

```
件名: Bookyou株式会社 本店移転のお知らせ

平素より AutonoMath をご利用いただき、誠にありがとうございます。

このたび Bookyou株式会社は、{{ effective_date }} 付けで本店を下記の
通り移転いたしました。サービス運営に変更はございません。

旧住所: 〒112-0006 東京都文京区小日向 2-22-1
新住所: {{ new_address }}

請求書・特商法表示は本日付けで更新済です。
詳細: https://jpcite.com/tokushoho

引き続きご愛顧のほど、よろしくお願い申し上げます。

Bookyou株式会社
代表 梅田茂利
```

Within the same 都道府県 (例: 文京区 → 新宿区) — notification is courteous
but not legally required.

### Step 9. Log the change

Append to `research/tokushoho_changes.log`:

```
2026-11-15 | 法人移転 | 〒112-0006 東京都文京区小日向 2-22-1 → 〒... | 司法書士=... | 登記日=2026-11-15 | files_updated=8 | stripe_updated=2026-11-16 | broadcast_sent=2026-11-17 | operator=umeda
```

---

## 5. Change event: 代表 (代表取締役) 変更

Operator (代表取締役 梅田茂利) is replaced by a new representative. This
overlaps significantly with `operator_succession_runbook.md` for the
death case; this section covers the alive-but-changing case (acquirer
takeover, voluntary handoff).

### Step 1. Complete legal change

1. 株主総会 / 取締役会 で 新代表選任決議
2. 代表取締役変更登記 (変更から 2 週間以内、商業登記法 § 915)
3. 司法書士 委任、登録免許税 ¥30,000

### Step 2. Update 印鑑証明 / 銀行届出

1. 法務局 で 新代表 の 印鑑届出 → 新法人実印
2. 銀行 (法人口座) の代表者変更届
3. Stripe 銀行口座情報 更新 (口座名義は 法人名のため通常不変、ただし
   Stripe KYC は 新代表 個人の 本人確認再提出 必須)

### Step 3. Update Stripe representative

Stripe Dashboard → Settings → Business settings → Account representative
→ update to new 代表 個人 information (氏名、生年月日、住所、本人確認
書類). Stripe re-runs KYC on the new representative.

During KYC re-validation: payouts may be paused. Plan the change for
month-end (after monthly invoice cycle completes) to minimize cash flow
impact.

### Step 4. Update HTML files

Edit:
- `site/tokushoho.html` 代表者氏名 line (~58)
- `site/en/tokushoho.html` corresponding line
- `site/privacy.html` if it names the representative
- `site/en/privacy.html` same

Search:

```bash
grep -rn "梅田茂利\|Umeda Shigetoshi" /Users/shigetoumeda/jpintel-mcp/site/
```

Update each. Use Edit tool, replace_all per file.

### Step 5. Update internal documentation

- `CLAUDE.md` line "Operator: Bookyou株式会社" — update 代表 name
- `operators_playbook.md` header "operator hat = ..."
- `operator_absence_runbook.md` 責任者 footer
- `operator_succession_runbook.md` 責任者 footer
- This runbook's footer
- All other `_internal/*.md` runbook footers

```bash
grep -rln "梅田茂利" /Users/shigetoumeda/jpintel-mcp/docs/_internal/ \
  /Users/shigetoumeda/jpintel-mcp/CLAUDE.md
```

### Step 6. Update Postmark sender + DNS

Postmark Servers → Sender Signatures → if `info@bookyou.net` was registered
under operator's personal name, re-verify under new representative's name
(usually no change required, just notation in Postmark account holder
profile).

### Step 7. Update PyPI / npm / GitHub maintainer

- PyPI: `pip install build twine`, then update `pyproject.toml` author
  email (if changing), and on next release the new metadata propagates.
- npm: `npm owner add <new_owner_email> autonomath-mcp` then `npm owner
  rm <old_owner_email>` after confirmation.
- GitHub Bookyou org: Settings → People → invite new owner, transfer
  ownership, remove old.

### Step 8. Deploy + notify

Same as §4 Step 7-8. Mandatory user notification for 代表 change (gives
users ground to terminate if they object to new operator).

### Step 9. Log

Append to `research/tokushoho_changes.log`:

```
2026-11-20 | 代表変更 | 梅田茂利 → {{ new_name }} | 司法書士=... | 登記日=2026-11-20 | files_updated=14 | stripe_kyc_complete=2026-11-25 | broadcast_sent=2026-11-21 | operator=umeda(outgoing)
```

---

## 6. Change event: T-号 (適格請求書発行事業者) update

T-号 itself does not change once issued. The change event is when
displayed-value review reveals it was missing or incorrect somewhere.

### Step 1. Verify current T-号

Canonical: T8010001213708 (令和7年5月12日登録)

Re-verify on 国税庁 適格請求書発行事業者公表サイト:
https://www.invoice-kohyo.nta.go.jp/regno-search/

Search: T8010001213708 → expect: 法人名 = Bookyou株式会社, 登録年月日 =
令和7年5月12日

If 未表示 or different name returned: open issue with 国税庁 (rare;
typically this means data entry error on registration).

### Step 2. Find missing or incorrect occurrences

```bash
grep -rln "T8010001213708\|適格請求書発行事業者" \
  /Users/shigetoumeda/jpintel-mcp/site/ \
  /Users/shigetoumeda/jpintel-mcp/templates/ \
  /Users/shigetoumeda/jpintel-mcp/pyproject.toml \
  /Users/shigetoumeda/jpintel-mcp/server.json
```

Cross-reference with the must-have list:

- `site/tokushoho.html` line ~65 (T-号 fielding row)
- `site/en/tokushoho.html` corresponding
- Stripe `INVOICE_FOOTER_JA` env: should be set to
  `"適格請求書発行事業者登録番号: T8010001213708"`
- Email template `templates/refund_full.md` etc. (any invoice-bearing
  email)

### Step 3. Verify Stripe invoice rendering

Issue a test invoice:

1. Stripe Dashboard → Customers → pick a test customer (or create one)
2. Invoices → Create invoice → use one-time charge of ¥100
3. Send invoice → open the resulting PDF
4. Footer must show: `適格請求書発行事業者登録番号: T8010001213708`
5. Verify required 5 items per 消費税法 § 57-4 (登録番号, 取引年月日,
   適用税率, 税率ごと消費税額, 交付事業者名)

### Step 4. Fix any drift

Use Edit tool to add T-号 where missing. Re-deploy via §4 Step 7.

### Step 5. Log

Append to `research/tokushoho_reviews.log`:

```
2026-MM-DD | T-号 verify | drift_found=0 (or count) | resolution=... | next_check_part_of_6mo_review
```

---

## 7. Change event: 電話番号 / 連絡先メール update

Phone number is "請求あり次第、遅滞なく開示" (open-by-request). This is
acceptable for sole proprietors / small 法人 per 消費者庁 guidance.

If the operator chooses to switch to publicly-displayed phone, or if the
open-by-request response phone changes:

### Step 1. Update internal contact records

Open `operators_playbook.md` §8 — update the 連絡先 row.

### Step 2. If switching to public display

Edit `site/tokushoho.html` line ~73:

```html
<!-- Before: -->
<td>請求があった場合、遅滞なく開示いたします。<a href="mailto:info@bookyou.net">info@bookyou.net</a> までご連絡ください。</td>

<!-- After: -->
<td>03-XXXX-XXXX (営業時間: 平日 10:00-18:00 JST)</td>
```

Same for `site/en/tokushoho.html`.

### Step 3. If email changes (rare — info@bookyou.net is the canonical)

If migrating off bookyou.net domain (e.g. 法人 移転 + 屋号変更): plan
this as a 法人 change (§4) — email is a minor downstream of 法人 changes.

If just adding an additional email (e.g. `support@bookyou.net` for
non-urgent inquiries): add as a secondary in `tokushoho.html`,
`privacy.html`, `tos.html`. Set up Postmark forwarding to ensure both
addresses route to the operator inbox.

### Step 4. Deploy + log

Same as §4 Step 7. Append to `research/tokushoho_changes.log` with
event_type=連絡先変更.

---

## 8. Annual full audit (in addition to 6-month review)

Once per year (anchored to launch + 12 months = 2027-05-06), perform a
deeper audit beyond the 6-month canonical-grep review.

### Step 1. Read aloud the displayed `tokushoho.html`

Open `https://jpcite.com/tokushoho.html` in a browser. Read each of
the 8 mandatory items aloud. Confirm each is current and accurate.
Reading aloud (vs scanning) catches stale text the eye glides over.

### Step 2. 消費者契約の専門用語 check

Verify:

- 「未成年者契約」exclusion language present (民法 § 5)
- 「クーリングオフ非該当」clarification: SaaS は 特商法 § 26 で
  クーリングオフ対象外 (通信販売であり、商品引渡し方法が異なる)
- 「消費者契約法 § 8 / § 8-2」のガードレール文言維持 (`tos.html`)

### Step 3. lawyer 1h review

Once per year, send the current `tokushoho.html` + `tos.html` +
`privacy.html` to operator's lawyer for 1-hour spot review. Cost:
~¥30,000-50,000. Output: list of recommended changes (if any).

If lawyer flags a 必修 change: open a ticket in `research/legal_followups/`
with deadline. Implement within 30 days.

### Step 4. 国民生活センター 動向 check

Check 国民生活センター (https://www.kokusen.go.jp/) for recent 消費者
苦情 trends related to SaaS pricing, 自動継続, 解約困難 etc. If any new
guidance applies, fold into next 6-month review.

### Step 5. Document the annual audit

Append to `research/tokushoho_reviews.log` with `annual=true`:

```
2027-05-06 | annual | drift_found=0 | lawyer_review=完了 | lawyer_ticket=N/A | next_annual=2028-05-06
```

---

## 9. Cross-references

- `operators_playbook.md` §9.1 — 消費生活センター 対応
- `launch_compliance_checklist.md` §2 — 特商法 pre-launch gate
- `breach_notification_sop.md` — 個人情報漏洩 (separate APPI obligation)
- `operator_absence_runbook.md` — 不在中 SLA
- `operator_succession_runbook.md` — 代表死亡 / 不能 case
- `stripe_webhook_rotation_runbook.md` — Stripe secret cycling
- `templates/` — email templates that include 事業者情報

---

最終更新: 2026-04-26
責任者: 代表 梅田茂利 (Bookyou株式会社, T8010001213708, info@bookyou.net)
次回 6 ヶ月レビュー: 2026-11-06
次回年次監査: 2027-05-06
