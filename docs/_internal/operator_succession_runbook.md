# Operator Succession Runbook (death / long-term incapacity / cessation)

**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26

Operator-only — do not link from public docs. Excluded from mkdocs build via
`exclude_docs: _internal/` (`mkdocs.yml`).

**Scope**: Permanent or unrecoverable absence of the sole operator
(Bookyou株式会社 代表 梅田茂利). Triggers include death, long-term
unconsciousness, severe disability preventing operation, dissolution of
Bookyou株式会社, or voluntary discontinuation of the AutonoMath service.

For absences ≤ 14 days follow `operator_absence_runbook.md` instead.

This runbook is written so that **a successor (family member, executor,
acquirer, or operator's lawyer) who has never operated AutonoMath** can
discharge the operator's legal obligations to users without prior product
knowledge. Read top to bottom before acting.

---

## 0. Identifying the trigger

Use this runbook when **any one** of the following holds:

- Operator is confirmed deceased (死亡診断書 or 戸籍記載).
- Operator is in long-term unconsciousness / severe medical incapacity
  with no recovery prognosis within 30 days.
- Operator is permanently disabled and unable to authenticate to required
  systems (Cloudflare 2FA, GitHub 2FA, Stripe Dashboard, Fly.io CLI).
- Bookyou株式会社 is being voluntarily dissolved (株主総会特別決議 →
  解散登記).
- Operator decides to discontinue AutonoMath as a service (commercial
  cessation, even with operator alive and well).

If you are reading this as the operator's successor: you have legal
obligations under 特商法 § 32 (continued contact info disclosure during
wind-down), APPI § 26 (data subject rights remain active until deletion),
消費契約法 § 8 (refund obligations not extinguished by operator change),
and 商法 / 会社法 (creditor notice + asset / liability handling). This
runbook discharges those obligations in the minimum-effort path.

---

## 1. Credential storage locations (where things are, **not** what they are)

The successor needs to access credentials but this document never contains
them. The operator stores credentials in the following locations. Each
entry names the location only; the values live behind 2FA / master
password / hardware key.

| System | Storage location name | Recovery factor |
| --- | --- | --- |
| 1Password vault `Bookyou` | Operator's primary password manager | Master password (deposit copy with executor / lawyer in 緊急開封 envelope) |
| Cloudflare account | 1Password vault `Bookyou`, item `cloudflare_root_account` | Email-based account recovery + 2FA backup codes (also in 1Password under `cloudflare_2fa_backup_codes`) |
| Fly.io account | 1Password vault `Bookyou`, item `flyio_root_account` | Email-based recovery + 2FA backup codes (`flyio_2fa_backup_codes`) |
| Stripe account | 1Password vault `Bookyou`, item `stripe_account` | SMS 2FA on operator's phone number + backup codes (`stripe_2fa_backup_codes`) |
| GitHub (Bookyou org) | 1Password vault `Bookyou`, item `github_bookyou_org` | Hardware key (Yubikey serial in `github_yubikey_serial`) + recovery codes (`github_2fa_recovery`) |
| Postmark | 1Password vault `Bookyou`, item `postmark_account` | Email recovery |
| Sentry | 1Password vault `Bookyou`, item `sentry_account` | Email recovery |
| AWS / R2 (backup bucket) | 1Password vault `Bookyou`, item `cloudflare_r2_api_token` | Cloudflare account-bound; same recovery as Cloudflare |
| PyPI account | 1Password vault `Bookyou`, item `pypi_token` | Email + 2FA |
| npm account | 1Password vault `Bookyou`, item `npm_token` | Email + 2FA |
| Domain registrar (jpcite.com, bookyou.net) | 1Password vault `Bookyou`, item `domain_registrar` | Email recovery |
| Bookyou 法人銀行口座 | Bank-issued 通帳 + 印鑑 (operator's residence safe) | Bank-side procedure (succession-specific) |
| 法人実印 / 銀行印 / 角印 | Operator's residence safe | Physical possession |
| Bookyou 定款 + 登記簿謄本コピー | Operator's residence file cabinet | 法務局 で再発行可 |

**Master password / safe combination disclosure**: Operator deposits a
sealed envelope with their lawyer (顧問契約済), contents include 1Password
master password, residence safe combination, and the contact list in §2.
Lawyer's instruction: open only on confirmed death / incapacity /
written succession trigger. Lawyer contact: see `operators_playbook.md`
§8 row "弁護士".

If the lawyer relationship is not yet established: depositing with
spouse / next of kin / executor under sealed envelope is the fallback.
Document the depositary in `docs/_internal/succession/depositary.md`
(restricted file, not committed without encryption).

---

## 2. First-72-hour actions for the successor

Goal: stop the bleeding. Stop new commitments, preserve options, do not
yet promise users anything.

### Step 1. Confirm trigger condition

Obtain documentation:

- Death: 死亡診断書 or 戸籍謄本 (issued by 市区町村).
- Incapacity: 医師の診断書 stating duration of incapacity.
- Voluntary cessation: written notice from operator (or 株主総会議事録
  if dissolution).

Without one of these, do not invoke this runbook. Use
`operator_absence_runbook.md` for the indeterminate period.

### Step 2. Notify the lawyer

Contact the operator's lawyer (`operators_playbook.md` §8). Provide
trigger documentation. Lawyer will:

- Open the sealed envelope (§1) and hand over master password.
- Initiate 法定相続人 / 遺言執行 procedures if applicable.
- Coordinate with 司法書士 for 代表変更 / 解散登記 if applicable.

If no lawyer relationship was set up: the successor (typically family /
executor) opens the residence safe and 1Password master directly.

### Step 3. Notify Bookyou株式会社 stakeholders

Bookyou株式会社 (T8010001213708) is the legal entity behind the service.

- If 代表 dies: 商業登記法 § 21 → 14 日以内 に 代表者死亡 + 後任 (or 解散)
  の登記。司法書士 経由が現実的。
- If 解散: 株主総会特別決議 (議事録作成) → 解散登記 + 清算人選任登記。
- Notify any shareholders (currently 100% operator; on death this passes
  to 法定相続人 by default unless 遺言 specifies otherwise).

### Step 4. Pause Stripe payouts

Stripe Dashboard → Settings → Payouts → Pause schedule.

Reason: while succession is being sorted, no new revenue should leave
Stripe to the bank account, in case the bank account itself is frozen by
death / dissolution. Pausing payouts holds funds at Stripe (protected by
Stripe Japan K.K. as 資金決済業) until the new account holder situation is
resolved.

This does **not** stop charging customers. Stripe will continue billing
metered usage; funds simply accumulate in the Stripe balance. To stop
charging customers, follow §4 below (cancel subscriptions).

### Step 5. Toggle status banner: 「サービス継承中」

Edit `site/status.html`:

```html
<div class="status-banner status-warn">
  サービス継承手続き中: 代表者の不在に伴い、API 稼働は継続しておりますが、
  新規申込み・お問い合わせ対応は一時停止しております。詳細は
  https://jpcite.com/succession.html をご覧ください。
</div>
```

Create `site/succession.html` with the user notice template (§3 below).
Commit + push (or have a developer push if successor cannot operate git).

If successor cannot push to GitHub: skip this step and rely on the
30-day notice email (§3) as the sole user-facing channel. The status
page can be updated later by an acquirer / wind-down operator.

### Step 6. Document the trigger

Create `docs/_internal/succession/YYYY-MM-DD-trigger.md`:

```markdown
# Succession trigger: <type>

- **trigger_type**: death | incapacity | voluntary_cessation | dissolution
- **trigger_date**: YYYY-MM-DD
- **documentation**: <死亡診断書 path | 診断書 path | 議事録 path>
- **successor_name**: <name + relationship + contact>
- **lawyer_engaged**: yes | no (yes recommended)
- **司法書士_engaged**: yes | no (yes if 登記 changes are needed)
- **stripe_payouts_paused**: yes | no (paused at YYYY-MM-DDTHH:MM)
- **status_banner_updated**: yes | no
```

If successor cannot reach this document, lawyer can rebuild from
`research/data_deletion_log.md` + `research/refund_decisions.log` +
Stripe / Cloudflare audit logs.

---

## 3. User notification (30-day notice)

Required by 特商法 § 32 (continued obligation during wind-down) and best
practice for APPI compliance (data subjects need time to export and
request deletion).

### Step 1. Compose the announcement

Template `templates/succession_30day_notice.md`:

```
件名: 【重要】AutonoMath サービス終了 / 代表者継承のお知らせ

平素より AutonoMath をご利用いただき誠にありがとうございます。
Bookyou 株式会社 (適格請求書発行事業者番号 T8010001213708) より、本サービスに関する
重要なお知らせをいたします。

【お知らせ内容】
代表者 (梅田茂利) の {{ trigger_reason }} に伴い、本サービスは
{{ trigger_date_plus_30 }} をもちまして提供を終了いたします。

【今後のスケジュール】
- 本日 〜 {{ trigger_date_plus_15 }}:
    通常稼働。データ export 機能をご利用いただけます。
    詳細: https://jpcite.com/data-export.html
- {{ trigger_date_plus_15 }} 〜 {{ trigger_date_plus_30 }}:
    新規申込みを停止。既存ご利用は継続。Stripe 月次請求は
    {{ trigger_date_plus_30 }} を最終とし、日割り計算いたします。
- {{ trigger_date_plus_30 }} 23:59 JST:
    API / MCP サーバー停止。ご利用データ (API key、ログ、課金履歴)
    は法令上必要な保存期間 (法人税法 7 年・APPI 個人情報削除請求
    対応) を除き削除いたします。

【データ export 手段】
- API key の利用履歴 CSV: {{ data_export_url }}
- 個人情報削除請求: {{ trigger_date_plus_30 }} までに info@bookyou.net
  までご連絡ください。

【返金について】
ご利用月の従量課金 (¥3/billable unit) は日割り計算でご返金いたします。
返金処理は Stripe 経由で {{ trigger_date_plus_45 }} までに完了します。

【お問い合わせ】
info@bookyou.net (応答 SLA: 5 営業日)

なお、本通知後も特商法 § 32 に基づき、消費者からの照会窓口は
2027-{{ +1 year }} まで維持いたします。

Bookyou 株式会社
{{ successor_name }}
〒112-0006 東京都文京区小日向 2-22-1
```

### Step 2. Distribute the notice

```bash
# Pull all email recipients (paid customers + newsletter subscribers)
sqlite3 /data/jpintel.db <<SQL > /tmp/notice_recipients.csv
SELECT DISTINCT email FROM subscribers WHERE unsubscribed_at IS NULL
UNION
SELECT DISTINCT s.customer_email FROM stripe_customers s
  JOIN api_keys ak ON ak.stripe_customer_id = s.customer_id
  WHERE ak.revoked_at IS NULL;
SQL
```

Upload to Postmark Broadcast → schedule send for current day +6h (gives
review window). Use the operator-absence template adapted with the
succession message.

If successor cannot operate sqlite + Postmark: lawyer hires a developer
contractor for ~¥30,000 one-shot to execute this step. Budget for this
in the residence safe envelope.

### Step 3. Public posting

- `site/succession.html`: full notice in HTML (created in §2 step 5).
- X / Twitter @autonomath_jp: pinned post with link.
- Status page: link from banner.

### Step 4. Notify Stripe support proactively

Stripe Dashboard → Support → email — explain the succession event and
that the account will be wound down. Stripe will coordinate on:

- Final payout to the bank account (or to the successor's account if the
  original is frozen — requires KYC on the new account).
- Refund processing for any customer requests.
- Tax / 1099 / consumer right communications.

Stripe Japan K.K. has handled successions before; their support can guide
through the specific paperwork.

---

## 4. Stripe subscription cancellation

After the 30-day notice expires, all subscriptions must be canceled.

### Step 1. Identify all active subscriptions

Stripe Dashboard → Customers → Filter: "active subscriptions". Export to
CSV. Cross-reference with `api_keys` table:

```bash
sqlite3 /data/jpintel.db <<SQL
SELECT customer_id, key_prefix, tier, created_at, last_used_at, stripe_subscription_id
  FROM api_keys
 WHERE revoked_at IS NULL
   AND stripe_subscription_id IS NOT NULL;
SQL
```

### Step 2. Cancel each subscription

For each subscription:

1. Stripe Dashboard → Subscriptions → click subscription → Cancel
   subscription → "Cancel at period end? **No, cancel immediately**".
2. Reason: "Service discontinued — operator succession".
3. Refund decision: pro-rate the current period (calendar days
   remaining / 30 × monthly metered total to date).

For high-volume cancellation (> 50 subscriptions), use Stripe API:

```bash
# In a one-shot script (lawyer hires developer if successor cannot run)
for sub_id in $(cat /tmp/active_subs.txt); do
  curl -X POST https://api.stripe.com/v1/subscriptions/${sub_id} \
    -u sk_live_REDACTED: \
    -d cancel_at_period_end=false \
    -d invoice_now=true \
    -d prorate=true
done
```

### Step 3. Confirm webhook handles cancellations

The `customer.subscription.deleted` webhook is wired in `api/billing.py`
to revoke the corresponding `api_keys` row. Verify by spot-checking 5
random subscriptions:

```bash
sqlite3 /data/jpintel.db \
  "SELECT customer_id, revoked_at FROM api_keys WHERE customer_id = 'cus_XXXX';"
# expect: revoked_at = recent timestamp
```

If webhook is failing: revoke manually (`UPDATE api_keys SET revoked_at =
datetime('now') WHERE customer_id = ?;`) for each affected row.

### Step 4. Issue refunds

For each customer with usage during the partial period:

- Calculated refund = (calendar days remaining / 30) × (monthly usage
  total to date in JPY).
- Stripe Dashboard → Payments → most recent payment → Refund button →
  partial amount.
- Reason: "Service discontinuation".

Send confirmation email per refund (Stripe auto-sends receipt; add a
manual follow-up if the amount is non-trivial).

### Step 5. Final payout

After all refunds processed, request Stripe to disburse remaining balance
to the bank account on file. If account is frozen, Stripe holds funds
pending KYC on a successor account.

---

## 5. Data deletion + APPI obligations

After service shutdown, two parallel data-handling tracks run.

### Track A: User-requested deletion (APPI § 35)

Per the 30-day notice, users may request deletion. Process within 14 days
of receipt. Use the existing procedure in `operators_playbook.md` §6.3.

If `operators_playbook.md` is unavailable to the successor: the SQL
template is:

```sql
BEGIN;
DELETE FROM subscribers WHERE email = '<user_email>';
UPDATE api_keys
   SET revoked_at = COALESCE(revoked_at, datetime('now')),
       customer_id = NULL,
       stripe_subscription_id = NULL
 WHERE customer_id = '<user_customer_id>';
UPDATE feedback
   SET customer_id = NULL, ip_hash = NULL, message = '[deleted on user request]'
 WHERE customer_id = '<user_customer_id>';
COMMIT;
```

Log each deletion in `research/data_deletion_log.md`.

### Track B: Bulk shutdown deletion (after 30-day window)

After the cutoff date in §3, perform bulk deletion of all PII not under
explicit retention obligation:

```sql
-- 1. Newsletter subscribers (no legal retention requirement)
DELETE FROM subscribers;

-- 2. API keys: nullify customer_id link, retain key_hash for billing audit
UPDATE api_keys
   SET customer_id = NULL,
       stripe_subscription_id = NULL,
       revoked_at = COALESCE(revoked_at, datetime('now'));

-- 3. Feedback: nullify PII columns
UPDATE feedback
   SET customer_id = NULL,
       ip_hash = NULL,
       message = '[deleted on service shutdown]';

-- 4. usage_events: retain for 7 years (法人税法・所得税法 帳簿保管義務)
--    Do NOT delete. Move to backup-only retention.

-- 5. anon_rate_limit: delete entirely (no retention requirement)
DELETE FROM anon_rate_limit;
```

Track B execution requires the successor to be on the Fly.io machine.
If the machine is already shut down, restore from the last R2 backup
(`dr_backup_runbook.md` Scenario 2) into a temporary container, run the
SQL, and re-snapshot the cleaned DB to R2 for the 7-year retention
window.

### Step C: Stripe customer deletion

Stripe Dashboard → Customers → for each customer: Actions → Delete
customer. Stripe retains transaction records for 7 years per Japanese
financial regulation; deletion only removes customer-side metadata
(email, address, payment method). This is APPI-compliant.

### Step D: Final retention archive

Move to long-term cold storage (Cloudflare R2 with 7-year lifecycle
policy):

- `usage_events` table dump (billing audit)
- `stripe_invoices` table dump (税法 7-year obligation)
- `audit_log` table dump (operator action history)
- All `*.bak` files from `data/` directory

R2 lifecycle rule: transition to Glacier-equivalent class after 90 days,
delete after 7 years (= 2033 for current snapshots).

---

## 6. Infrastructure shutdown

After data deletion completes, tear down infrastructure to stop the
recurring spend.

### Step 1. Fly.io app shutdown

```bash
flyctl apps suspend autonomath-api
# Wait 24h to confirm no recovery requests
flyctl apps destroy autonomath-api --yes
flyctl volumes destroy <volume_id> --yes
```

### Step 2. Cloudflare Pages shutdown

Cloudflare Dashboard → Pages → autonomath project → Settings → Delete
project.

DNS records: leave `jpcite.com` and `bookyou.net` resolving to the
shutdown notice page for at least 12 months (特商法 contact obligation).
Use a static hosting alternative (e.g. GitHub Pages free tier) for the
sole `succession.html` + `tokushoho.html` pages.

### Step 3. Cloudflare R2 retention

Keep the `autonomath-backup` bucket active for 7 years (税法 帳簿). Pre-pay
estimated cost: ~¥150/month × 84 months = ¥12,600 → fund from final
Bookyou 法人 distribution.

### Step 4. PyPI / npm package archival

```bash
# Mark package as deprecated, do not delete (existing users depend on cached
# wheels; deletion would break their installs)
pip install pip-tools
pypi-cli deprecate autonomath-mcp \
  "Service discontinued 2026-MM-DD. See https://jpcite.com/succession.html"
npm deprecate autonomath-mcp \
  "Service discontinued 2026-MM-DD. See https://jpcite.com/succession.html"
```

### Step 5. GitHub repository

Set `bookyou/jpintel-mcp` to Archive (read-only). Do not delete — public
contributors / forks may exist.

### Step 6. Service accounts

Cancel monthly subscriptions:

- Postmark
- Sentry
- Cloudflare paid plan (if any beyond free)
- 1Password (transfer ownership to successor / lawyer)

Final spend should drop to ~¥150/month (R2 retention only) within 30 days.

---

## 7. 法人 (Bookyou株式会社) handling

Legal entity tracks parallel to service shutdown.

### Path A: Operator deceased

1. **法定相続**: 株式 (100%) → 法定相続人 (配偶者 / 子 / 父母 順)。
   遺言があれば 遺言執行 が優先。
2. **代表変更登記**: 14 日以内 (商業登記法 § 21)。司法書士 委任。
3. **取締役会 / 株主総会**: 1 名 取締役 が死亡したのみであれば、相続人
   が承継。代表 1 名のみ → 後任を 株主 (相続人) が選任。
4. **継続 vs 解散**: 相続人が事業継続を望まない → 解散決議 (特別決議
   = 議決権 2/3 以上)。AutonoMath の場合、サービス停止後の Bookyou は
   特商法 § 32 の連絡窓口維持以外に活動なし → 解散が現実的。

### Path B: 解散 (voluntary or post-shutdown)

1. **株主総会特別決議**: 解散議案 + 清算人選任 (通常は元代表の家族 or
   司法書士)。議事録作成。
2. **解散登記**: 解散日から 2 週間以内。司法書士 委任。
3. **官報公告**: 債権者保護のため 2 ヶ月以上 公告 (官報 1 回掲載 +
   既知債権者には個別通知)。
4. **清算結了登記**: 残余財産分配後、清算結了 を 株主総会で承認 →
   登記。
5. **税務署 / 都税事務所 / 年金事務所 廃業届**: 1 ヶ月以内。

Total cost: 司法書士 報酬 ~¥100,000 + 官報公告 ~¥40,000 + 登録免許税
~¥40,000 = 約 ¥180,000。

### Path C: 事業承継 (acquirer)

If a buyer acquires AutonoMath:

1. 株式譲渡 (個人 → 個人 or 個人 → 法人) → 株主名簿 更新。
2. 代表変更登記。
3. AutonoMath サービスは新代表が継続運営 → §3 の 30-day notice は
   不要 (運営継続)。ユーザーへの通知は「経営継承のお知らせ」テンプレ
   に切替。
4. 顧客名簿 + Stripe + 法人銀行口座 の 帰属変更 → 個人情報の譲渡 は
   APPI § 23 第三者提供 例外 (事業継承) 該当 → 通知のみで OK、同意
   不要。ただし Privacy Policy に「事業承継時に譲渡される場合がある」
   記載必須 (現 `privacy.html` に記載済か要確認)。

### Path D: Voluntary cessation (operator alive, no acquirer)

Same as Path B (解散) but operator handles all steps personally.
Recommended only if all other paths exhausted.

---

## 8. 特商法 § 32 maintenance during wind-down

Even after service shutdown, 特商法 obligation to provide contact info
to consumers continues for the duration of any outstanding consumer
liability (refund, dispute, complaint).

- `tokushoho.html` must remain accessible for **at least 12 months** after
  final paid customer's last transaction.
- Email `info@bookyou.net` must remain monitored (forward to successor /
  lawyer).
- 〒112-0006 東京都文京区小日向 2-22-1 (operator's residence) → if
  successor moves out, update `tokushoho.html` per
  `tokushoho_maintenance_runbook.md` to the new contact address (often
  the lawyer's office).

If 法人 解散 completes: 清算人 inherits 特商法 obligations until 清算結了。
After 清算結了: obligations extinguish. Document the date in
`docs/_internal/succession/wind_down_complete.md`.

---

## 9. Outstanding obligations checklist

Before declaring shutdown complete, verify each row:

- [ ] All paying customers received 30-day notice
- [ ] All paying customers received refund (or confirmed no refund owed)
- [ ] All Stripe subscriptions canceled
- [ ] All API keys revoked
- [ ] All APPI deletion requests resolved within 14-day window
- [ ] Final R2 backup snapshot taken (post-deletion DB)
- [ ] Fly.io app destroyed
- [ ] Cloudflare Pages destroyed (except `succession.html` mirror)
- [ ] PyPI / npm packages deprecated (not deleted)
- [ ] GitHub repo archived
- [ ] Postmark / Sentry / Cloudflare paid plans canceled
- [ ] R2 retention bucket lifecycle policy set (7-year)
- [ ] 法人 解散 / 代表変更 登記 完了 (per Path A/B/C/D)
- [ ] 税務署 / 都税事務所 廃業届 提出
- [ ] `tokushoho.html` 連絡窓口 forwarded to successor / lawyer
- [ ] Final cost report filed for 法人 清算

---

## 10. Successor onboarding shortcut

If a successor inherits an active operation (Path C: acquirer), they need
operational knowledge fast. Read in this order:

1. `CLAUDE.md` (this repo root) — product overview + non-negotiable
   constraints
2. `docs/_internal/operators_playbook.md` — daily operations
3. `docs/_internal/incident_runbook.md` — outage / leak response
4. `docs/_internal/dr_backup_runbook.md` — backup / restore
5. `docs/_internal/launch_compliance_checklist.md` — legal posture
6. `docs/_internal/operator_absence_runbook.md` — for vacation planning
7. `docs/_internal/stripe_webhook_rotation_runbook.md` — webhook secret
   rotation
8. `docs/_internal/tokushoho_maintenance_runbook.md` — contact info
   updates
9. This file — for their own succession planning

Estimated reading time: 4-6 hours. Allocate 1 full day for credentials
handover (1Password vault transfer, 2FA reset on every account, Yubikey
re-pairing).

---

## 11. Cross-references

- `operator_absence_runbook.md` — short-term absence (≤14d)
- `operators_playbook.md` — daily operations
- `incident_runbook.md` — outage / leak / DDoS / disk full
- `breach_notification_sop.md` — APPI / GDPR breach SOP
- `dr_backup_runbook.md` — backup + restore
- `tokushoho_maintenance_runbook.md` — 特商法 contact info
- `stripe_webhook_rotation_runbook.md` — webhook rotation
- `launch_compliance_checklist.md` — pre-launch legal gates
- `templates/succession_30day_notice.md` — user notice template (to be
  created on first invocation)

---

最終更新: 2026-04-26
責任者: 代表 梅田茂利 (Bookyou株式会社, T8010001213708, info@bookyou.net)
継承時責任者: 顧問弁護士 → 法定相続人 / 株主総会選任清算人 (順次)
