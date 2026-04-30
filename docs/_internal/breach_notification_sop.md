# Breach Notification SOP (operator-only)

**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26

**Audience:** Bookyou株式会社 (T8010001213708) sole operator (代表 梅田茂利, info@bookyou.net).
**Visibility:** Excluded from the public docs site via `mkdocs.yml::exclude_docs` (`_internal/` prefix). Do **not** link from public pages.
**Last updated:** 2026-04-26.

This SOP exists because APPI (改正個人情報保護法) §26 mandates "速やかに" notification of the 個人情報保護委員会 (PPC) and affected users on personal data breach, GDPR Art. 33 imposes a 72h clock to the lead supervisory authority, and a solo operator cannot be expected to remember either procedure mid-incident. Read it cold; rehearse it twice a year (drill cadence at the bottom).

The product surface is small. PII at risk is, in order of likelihood:

- **email** — registered users + Stripe customers
- **ip_hash** — sha256 (not raw IP; still treated as personal data because re-identifiable with auth log + access timestamp)
- **Stripe customer IDs** — `cus_*` strings; map to email via Stripe console
- **API keys** — argon2id hashed at rest. Plaintext exists only at rotation moment (welcome email). Treat any exposure of the welcome email outbound as a credentials leak.
- **usage_events.query** — free-text user input. Could contain PII the customer typed in (法人番号, address, contact name). Telemetry middleware redacts but redaction is best-effort.

There is **no 要配慮個人情報** at rest by design (no health, race, criminal record, social status data). This matters because APPI §26 mandatory notification only triggers when (a) sensitive PII is involved, **or** (b) ≥1,000 individuals affected, **or** (c) financial harm risk, **or** (d) malicious intent. The decision matrix in §8 below reflects this.

---

## 1. Trigger conditions

A breach is any of the following confirmed or strongly suspected events. Anything in this list jumps to T+0 immediately — do **not** wait for full triage.

| Trigger | What to confirm | Severity hint |
| --- | --- | --- |
| **Stripe webhook leak** — raw event JSON containing `customer_email` posted to a public URL (Sentry public DSN, GitHub gist, HTTP echo server) | Sentry "Recent events" search for `customer.subscription.*` payloads with email field; check Stripe event log delivery URLs. | High if any production event leaked. |
| **Database file leak** — `autonomath.db` / `jpintel.db` dump appearing outside the Fly volume | Cloudflare R2 access logs; GitHub repo for accidentally-committed `.db` / `.bak` files; Fly volume snapshot ACLs. | Critical — entire user table + email + ip_hash exposed. |
| **API key leak** — welcome email forwarded externally; raw key string posted to GitHub / pastebin / public Slack | Search `sk_live_` prefix via grep.app + GitHub code search. Postmark "outbound" for unusual recipient domains in 24h window. | Medium — keys are rotatable; impact bounded by per-key spend. |
| **Backup R2 bucket misconfiguration** — `autonomath-backup` bucket flips to public ACL / signed URL window unintentionally extends | Cloudflare R2 bucket settings audit; `cloudflared` access log grep for `s3:GetObject` from non-Fly IP. | Critical — full DB exposure. |
| **Log file leak** — Fly.io stdout retention captured in third-party log aggregator (Datadog free trial, etc.) without redaction | Fly logs export config; verify INV-21 `redact_pii` middleware is active in production (`/v1/__internal/middleware_state` if exposed). | Medium-High depending on log content. |

**Adjacent triggers (not breaches but escalate immediately):**

- Stripe webhook signature verification failures spiking (forged events probing) — not a breach yet, but a precursor.
- Argon2 verification time anomaly (signal of timing oracle attack).
- Cloudflare WAF block rate >5σ above baseline against `/v1/me/*`.

These go to incident-watch in `monitoring.md` runbook, not this SOP. This SOP is for **confirmed personal data exposure**.

---

## 2. T+0 — within 1 hour of detection

**Goal:** stop the leak, preserve evidence, anchor the timeline.

Do these **in order**. Do not skip steps to "save time" — the timeline anchor is what determines whether you make the 72h GDPR window.

### 2.1 Note exact time of detection

Write to `docs/_internal/incidents/YYYY-MM-DD-<slug>.md` (create the file now even if empty):

```
detection_time_jst: 2026-MM-DD HH:MM:SS JST
detection_time_utc: 2026-MM-DD HH:MM:SS UTC
detection_source: <Sentry alert ID | user email | tweet | self-spotted>
first_evidence: <link to alert / screenshot path>
```

The `detection_time_utc` is what GDPR Art. 33 counts from. Do **not** retroactively edit this row — append amendments below.

### 2.2 Stop the leak source

Match the trigger to the action:

| Trigger | Stop action | Verify |
| --- | --- | --- |
| Stripe webhook leak | Rotate Stripe webhook secret in dashboard; update `STRIPE_WEBHOOK_SECRET` in Fly secrets; redeploy. | `fly logs --app autonomath-api \| grep webhook_signature_invalid` should show no successful events post-rotation. |
| Database file leak (committed to repo) | `git rm` + force-push **only after** evidence snapshot. Open ticket with GitHub for cache purge: https://github.com/contact/dmca | Verify the file 404s on GitHub raw URL. Note: cached forks are out of our control — assume permanent. |
| Database file leak (R2) | Revoke the offending R2 token via Cloudflare dashboard → R2 → Manage API tokens; rotate `R2_ACCESS_KEY_ID` + `R2_SECRET_ACCESS_KEY` Fly secrets. | New backup run should succeed; old token's calls should 403. |
| API key leak | Force-rotate the affected `api_keys` row: `UPDATE api_keys SET key_hash='REVOKED', revoked_at=CURRENT_TIMESTAMP WHERE id=...;` and email the customer (template in §5). | Customer's next request returns 401; cap cache invalidates within 60s. |
| R2 bucket public ACL | Cloudflare dashboard → R2 → bucket → Settings → flip to private; revoke any custom domain mapping. | `curl -I https://<bucket>.r2.dev/<file>` returns 403. |
| Fly stdout log leak | Disable the third-party log integration; rotate any tokens it had; if log retention is the issue, contact the aggregator vendor for deletion. | Vendor-side confirmation required. |

### 2.3 Snapshot evidence

Before any rotation, dump:

- **Fly logs**: `fly logs --app autonomath-api -n 10000 > /tmp/incident-flylogs-$(date +%s).txt`
- **R2 access log** (if R2-related): Cloudflare dashboard → R2 → bucket → Logs → Download CSV for the last 7 days.
- **Stripe event log**: dashboard → Developers → Events → filter by date → "Export" → CSV.
- **Sentry incident timeline**: link the Sentry issue ID into the incident file.
- **DB row count delta** (if data exfiltration suspected): record `SELECT COUNT(*) FROM api_keys`, `SELECT COUNT(*) FROM subscribers`, etc., for diff vs. baseline.

Store the dumps under `docs/_internal/incidents/<incident-slug>/evidence/`. **Do not commit Stripe customer-email exports to git** — keep them local + encrypted (age, gpg, or `openssl enc -aes-256-cbc`). Reference by hash in the incident file.

### 2.4 Open the incident file

Skeleton at `docs/_internal/incidents/YYYY-MM-DD-<slug>.md`:

```markdown
# Incident: <slug>

- **status**: detecting / containing / triaging / notifying / closed
- **detected**: <JST + UTC>
- **contained**: <JST + UTC, fill at end of T+0>
- **trigger**: <which §1 row>
- **affected_pii**: [email, ip_hash, ...]
- **affected_count_estimate**: TBD (fill at T+24h)
- **mandatory_ppc_notify**: TBD (fill at T+24h)
- **gdpr_in_scope**: TBD (fill at T+24h)
- **public_disclosure**: TBD

## Timeline

- HH:MM JST — detection
- HH:MM JST — leak source confirmed
- HH:MM JST — leak stopped
- HH:MM JST — evidence snapshotted

## Evidence

- /tmp/...
- evidence/...

## Decisions

- (filled at T+24h)
```

---

## 3. T+24h — internal triage

**Goal:** answer the four questions that drive notification obligation.

### 3.1 Affected user count

For each trigger, the count query differs:

- **Stripe webhook leak**: count of unique `customer_email` values in the leaked payloads (read from evidence dump, not live DB).
- **Database file leak**: `SELECT COUNT(DISTINCT email) FROM subscribers` + `SELECT COUNT(*) FROM api_keys WHERE revoked_at IS NULL` at the time of the snapshot.
- **API key leak**: 1 per leaked key (the customer who owned it).
- **R2 bucket leak**: same as DB file leak (worst case is full R2 contents — assume both `jpintel.db` and `autonomath.db` exposed).
- **Log file leak**: count of unique IPs / api_key_ids in the leaked log window.

Round **up**. Document the methodology in the incident file.

### 3.2 PII categories affected

Check each box that applies:

- [ ] email
- [ ] ip_hash (re-identifiable → personal data under APPI)
- [ ] Stripe customer ID (financial identifier — adjacent to payment data even though card numbers never touch our system)
- [ ] API key plaintext (credentials — different obligation tier; treat as financial harm risk)
- [ ] usage_events.query content (free-text; could contain anything the user typed)
- [ ] 要配慮個人情報 (sensitive PII) — almost certainly **no** for AutonoMath, but verify the leaked data does not include health / race / criminal record / belief data accidentally captured in query content

### 3.3 Mandatory PPC notification gate

Per APPI §26, notification to the PPC + affected individuals is **mandatory** when **any** of the following holds:

| Gate | Triggered when |
| --- | --- |
| Sensitive PII | leaked data includes 要配慮個人情報 (health / criminal / race / belief / social status) |
| Scale | ≥1,000 individuals affected |
| Financial harm risk | leaked data could enable financial harm to the individual (API key plaintext, Stripe customer ID + email correlation) |
| Malicious intent | the breach was caused by intentional unauthorized access (intrusion, insider exfiltration, phishing) |

If **none** of these gates trip, notification is **discretionary** (任意の自主公表). Even discretionary, default to notify if the leak was on a public surface (GitHub, R2 public bucket) — silence on a public leak invites later 景表法 / 信義則 problems.

Record decision in the incident file:

```
mandatory_ppc_notify: yes (gate: scale, ≥1000 emails)
                    | no (none of the four gates tripped; voluntary disclosure planned)
```

### 3.4 GDPR Art. 33 in-scope check

Run: `SELECT email FROM subscribers UNION SELECT email FROM api_keys` filtered to TLDs in the EEA list (`.de`, `.fr`, `.it`, `.es`, `.nl`, `.be`, `.at`, `.se`, `.fi`, `.dk`, `.ie`, `.pt`, `.gr`, `.pl`, `.cz`, `.sk`, `.hu`, `.ro`, `.bg`, `.hr`, `.si`, `.ee`, `.lv`, `.lt`, `.lu`, `.mt`, `.cy`, `.is`, `.no`, `.li`, `.eu`).

Email TLD is a heuristic. The legal hook is whether AutonoMath "monitors the behaviour" or "offers goods/services" to data subjects in the EU (GDPR Art. 3(2)). At launch we only target Japanese SMEs; an inbound EU customer is incidental. If even one such email exists in the affected set **and** the breach is real (not a near-miss), assume Art. 33 applies and run the §6 path **in parallel** to the APPI path.

---

## 4. T+72h — PPC notification (if mandatory)

**Form**: https://www.ppc.go.jp/personalinfo/legal/leakAction/

**Required fields** (verbatim from PPC guidance, §3条 of 個情委規則):

1. **概要** — natural-language summary of the incident
2. **漏えい等が発生し又は発生したおそれがある個人データの項目** — concrete field list (email, ip_hash, etc.)
3. **件数** — affected individual count (use the rounded-up number from §3.1)
4. **原因** — root cause (e.g., "Cloudflare R2 bucket ACL誤設定により1名のオペレーターが任意ユーザーから読み取り可能な状態となった")
5. **二次被害又はそのおそれの有無及びその内容** — secondary harm (e.g., "API key were not in clear; rotation forced; no observed misuse")
6. **本人への対応の実施状況** — user notification status (link to §5 templates dispatch log)
7. **公表の実施状況** — public disclosure status (link to /security/incidents/ page if used)
8. **再発防止のための措置** — preventive measures (e.g., "ACL自動監査追加 / pre-commit hook で `*.db` を block / R2 token rotation cadence を 30→14日に短縮")
9. **その他参考となる事項** — anything else relevant (timeline, vendor cooperation status)

**If the form is unavailable**, email the PPC at the address listed on the dashboard's "お問い合わせ" page (verify at notification time — do not hardcode here, the address rotates).

**Speed-bound (速報)**: The PPC distinguishes 速報 (within 3-5 business days, partial info OK) from 確報 (within 30 days for normal breaches, 60 days for unauthorized-access breaches, full info). If the §3.3 gate trips, file 速報 immediately even if §3.1 count is still being refined; mark "件数: 概算XXX名 (確定後追記)". The 確報 deadline is from the same detection anchor in §2.1.

---

## 5. User notification templates

Send via Postmark **transactional** stream (not broadcast — it's a 1:1 contractual notice, not marketing). Postmark has a separate `transactional` server token; the `broadcast` token is reserved for the alerts list. **Do not** use the broadcast stream for incident notifications — it suppresses on bounce/unsub but breach notices are obligation-bound.

### 5.1 JA template

```
件名: 【重要】個人情報の漏えいに関するお知らせ (AutonoMath)

{{customer_name}} 様

平素より AutonoMath をご利用いただき誠にありがとうございます。
このたび、当社が運営するサービスにおいて、お客様の個人情報の一部が
外部に漏えいした事案を確認いたしましたので、お知らせいたします。

■ 発生事象
{{incident_summary}}

■ 漏えいした可能性のある情報
- {{pii_categories}}

■ 対応状況
- 漏えい源の停止: 完了 (YYYY-MM-DD HH:MM JST)
- 個人情報保護委員会への報告: {{ppc_status}}
- 二次被害確認: {{secondary_harm}}

■ お客様にお願いしたい対応
{{user_action_items}}

■ お問い合わせ窓口
Bookyou 株式会社 (適格請求書発行事業者番号 T8010001213708)
代表 梅田茂利
info@bookyou.net

ご迷惑をおかけしますことを深くお詫び申し上げます。
今後このような事案を発生させないため、再発防止策を徹底してまいります。

Bookyou 株式会社
```

### 5.2 EN template

```
Subject: [Important] Notice of personal data incident (AutonoMath)

Dear {{customer_name}},

Thank you for your continued use of AutonoMath. We are writing to
inform you of an incident affecting your personal data that we
identified on {{detection_date_jst}}.

What happened
{{incident_summary}}

Information potentially affected
- {{pii_categories}}

Our response
- Source contained: YYYY-MM-DD HH:MM JST
- Japan PPC notification: {{ppc_status}}
- Secondary harm assessment: {{secondary_harm}}

What we ask you to do
{{user_action_items}}

Contact
Bookyou Inc. (Corporate Number T8010001213708)
Representative: Shigetoshi Umeda
info@bookyou.net

We deeply apologise for the inconvenience and are implementing
corrective measures to prevent recurrence.

Bookyou Inc.
```

Substitution rules:

- `{{user_action_items}}`: keep concrete. For API key leak: "1) ダッシュボードの「APIキーをローテート」を押してください。2) 漏えいキーで発行済みの request 履歴をご確認ください。"
- For email-only leak: "特段の対応は不要ですが、当社を装ったフィッシングメールにご注意ください。"
- For Stripe customer ID leak: "Stripe 請求情報そのもの (カード番号等) は当社サーバを経由しないため漏えいしておりません。請求書番号と Email アドレスの対応のみが漏えいしました。"

---

## 6. GDPR Art. 33 path (if §3.4 in-scope)

### 6.1 Lead supervisory authority

AutonoMath has no establishment in the EU. Per GDPR Art. 56(1), in absence of a main establishment, each affected member state's supervisory authority has jurisdiction. **Practical default**: file with the **Irish DPC** (https://www.dataprotection.ie/) since most EU SaaS-adjacent inquiries land there and they accept English filings. If the affected user(s) are concentrated in one specific country, also file with that country's DPA in parallel.

### 6.2 72-hour deadline

Counts from `detection_time_utc` in §2.1 (GDPR uses "awareness" — interpret as the moment the operator first had reasonable certainty, not the moment of the underlying event). If the deadline cannot be met, the notification must include a justification for the delay (Art. 33(1)).

### 6.3 Required content (Art. 33(3))

(a) Nature of the breach including, where possible, the categories and approximate number of data subjects concerned, and the categories and approximate number of personal data records concerned.

(b) Name and contact details of the data protection officer or other contact point. **AutonoMath has no DPO** (zero-touch ops, exempt under Art. 37 because we are not a public authority, do not engage in large-scale systematic monitoring, and do not process special categories at scale). The contact point is `info@bookyou.net` — say so explicitly.

(c) Likely consequences of the breach.

(d) Measures taken or proposed to address the breach, including measures to mitigate adverse effects.

Use the same evidence + §3 triage answers; just translate to English and submit via the DPC online form.

### 6.4 Art. 34 individual notification

If the breach is "likely to result in a high risk to the rights and freedoms" of data subjects, also notify each affected individual directly (Art. 34). The §5.2 EN template covers this. Skip Art. 34 only when (a) data was encrypted at rest with a key not exposed (argon2id hashes qualify; raw email does not), or (b) subsequent measures eliminate the high risk, or (c) individual notification would involve disproportionate effort (in which case a public communication suffices).

---

## 7. Post-incident

### 7.1 Postmortem within 7 days

Append to the same incident file under `## Postmortem`:

- **Timeline** — paste the timeline from §2.4, extended through closure.
- **Root cause** — five-whys, written for a future operator who has never heard of this incident.
- **What worked** — list at least three.
- **What failed** — list every gap honestly, even the embarrassing ones.
- **Action items** — each with owner (always: 梅田茂利) and due date.

### 7.2 Update CONSTITUTION / SOP if process gap found

If the postmortem identifies a structural problem (e.g., "the trigger condition was not in §1"), update this SOP **in the same commit** as the postmortem. Do not let process gaps stale-out.

If the gap is a non-negotiable invariant (e.g., "we must never log raw IP again"), update `CLAUDE.md` "What NOT to do" section and add a hard-fail boot check (`INV-NN`).

### 7.3 Public disclosure

If the incident was user-facing (any §3.3 gate tripped, or the leak was visible on a public surface), publish a redacted writeup at `https://jpcite.com/security/incidents/YYYY-MM-DD-<slug>/`. Use the public-facing tone of `site/security/policy.md` (no internal jargon, no Fly app names, no R2 bucket names — just timeline + impact + remediation).

If no §3.3 gate tripped **and** the leak was on a private surface and contained, public disclosure is optional. Default to **disclose anyway** for any incident with email-level PII exposure — silence on real incidents creates a worse trust baseline than honest writeups.

---

## 8. Decision matrix

Affected count × PII sensitivity × trigger → action.

| Affected | PII type | Trigger | PPC mandatory? | GDPR? | User notify? | Public disclosure? |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | email | API key leak (self-pasted to public) | No (financial harm low; key is rotatable) | If EU | Yes (1:1) | Optional |
| 1-99 | email + ip_hash | R2 bucket public ACL <1h | No (count <1000, no sensitive PII) | If EU | Yes (1:1) | Yes (public surface) |
| 100-999 | email + ip_hash | DB dump committed to GitHub | No by gate, but disclose voluntarily | If any EU | Yes | Yes |
| ≥1,000 | email | Any | **Yes (scale gate)** | If any EU | **Yes (mandatory)** | **Yes** |
| any | API key plaintext | Welcome email forwarded externally | If financial harm risk realised (key actually misused) | If EU | Yes (1:1) | Optional unless misuse confirmed |
| any | usage_events.query content | Log leak | Yes if query content contains 要配慮 PII | If EU | Yes | Yes |
| any (≥1) | Stripe customer_id + email correlation | Webhook leak | Yes (financial harm gate — id+email enables phishing) | If EU | Yes | Yes |
| 0 confirmed | any | Vulnerability disclosed but no exploitation | No | No | No | Optional (post-fix advisory) |

When in doubt, **notify**. The cost of over-notifying is reputational (and small — operators who notify proactively are trusted more); the cost of under-notifying when §26 applies is regulatory (PPC 命令 + named-and-shamed publication, plus 一年以下の懲役 or 100万円以下の罰金 for the representative).

---

## 9. Contact list

Keep this list current. Verify the phone numbers + addresses at every drill.

### Regulators

- **個人情報保護委員会 (PPC)** — 03-6457-9849 (代表). Online form: https://www.ppc.go.jp/personalinfo/legal/leakAction/. Email: see the dashboard's お問い合わせ page (rotates).
- **公正取引委員会 (JFTC)** — 03-3581-5471. Use **only** if the incident involves a 景表法 misrepresentation about pricing/availability (e.g., we mis-stated SLA at the time of breach). Not for the breach itself.

### Vendor security desks

- **Stripe** — security@stripe.com. Use for webhook leak / Stripe-side compromise. Stripe publishes their own breach SOP; they will guide rotation.
- **Postmark** — security@postmarkapp.com. Use for outbound email logs / token leak.
- **Cloudflare** — abuse@cloudflare.com (R2 / Pages misconfig); security@cloudflare.com (vulnerability in their product affecting us).
- **Fly.io** — security@fly.io. Use for volume snapshot ACL / log retention issues.

### Legal

- **弁護士窓口**: TBD — operator must establish a relationship with a Tokyo IT-law firm before the first incident. Placeholder: leave the firm + contact name + retainer status in `docs/_internal/legal_contacts.md` (operator action item).

### EU (only if §3.4 in-scope)

- **Irish DPC** — https://www.dataprotection.ie/en/contact/breach-notification. Default lead authority for non-EU controllers without establishment.
- **Local DPA** for the affected member state if concentration is clear (e.g., German BfDI for German users).

---

## 10. Drill cadence

**Twice/year tabletop.** Schedule at the same time as the DR drill in `dr_backup_runbook.md` so both are exercised in the same session.

Future automation: `/Users/shigetoumeda/jpintel-mcp/scripts/breach_drill.py` (not yet created — operator action item). Intent: scripted scenario walks that pretty-print "trigger row X was hit, walk through §2 → §3 → §4 with mock data and rate the operator's recall." Leave as future work; do not block this SOP on its existence.

Drill checklist (manual, until script lands):

- [ ] Pick one §1 trigger row at random (use `python -c "import secrets, random; rows=['stripe_webhook','db_file','api_key','r2_acl','log_leak']; print(random.choice(rows))"`).
- [ ] Set a 60-minute timer; walk T+0 from memory; check this doc only after the timer.
- [ ] Note every step missed or hesitated on; update §2 checklist if the doc was unclear.
- [ ] Compose the §5 template against a fictional customer; confirm Postmark transactional template ID is current.
- [ ] If GDPR-in-scope drill: render the §6.3 four-section content in English from memory.
- [ ] Update §9 contact list — verify each phone number / form URL is alive.
- [ ] Append drill result to `docs/_internal/incidents/drills/YYYY-MM-DD-drill.md`.

**No bug bounty / paid program** is offered — per the operator policy that AutonoMath runs 100% organic with zero outbound spend. Vulnerability disclosure is unpaid, recognition-only.
