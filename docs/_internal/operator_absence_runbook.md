# Operator Absence Runbook (1-14 day)

**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26

Operator-only — do not link from public docs. Excluded from mkdocs build via
`exclude_docs: _internal/` (`mkdocs.yml`).

**Scope**: Planned or unplanned absence of the sole operator (Bookyou株式会社
代表 梅田茂利) for 1-14 consecutive days. Typical triggers: domestic travel,
short hospitalization, family emergency, conference / off-grid period.

For absences > 14 days or unrecoverable scenarios (long-term unconsciousness,
death, business cessation) follow `operator_succession_runbook.md` instead.

---

## 1. What keeps running automatically

The product is engineered for zero-touch operation precisely so the operator
can leave for ≤ 14 days without service degradation. All of the following
continue without operator action:

| Surface | Mechanism | Failure mode |
| --- | --- | --- |
| API / MCP request serving | Fly.io Tokyo machine + auto-restart (3 retries / 10 min) | Auto-restart loop → §6 escalation |
| `/v1/billing/webhook` (Stripe) | Fly endpoint + signature verification (`api/billing.py`) | See `stripe_webhook_rotation_runbook.md` |
| Stripe metered usage reporting | `billing/usage_reporter.py` cron (hourly) | Backlog accrues; reconciles automatically on resume |
| Anonymous IP rate limit reset | JST 月初 00:00 cron (`anon_rate_limit` table) | None — pure DB write |
| Cloudflare Pages static site | Auto-deploy from `main` branch on push | None during absence (no pushes expected) |
| Cloudflare DNS / TLS / WAF | Cloudflare-managed, no operator action needed | TLS auto-renew via Cloudflare; no manual cert rotation |
| Nightly DB backup (jpintel.db) | GHA `nightly-backup.yml` (18:17 UTC) | See `dr_backup_runbook.md` |
| Weekly DB backup (autonomath.db) | GHA `weekly-backup-autonomath.yml` (Sun 19:00 UTC) | Same |
| Health probe (`/v1/am/health/deep`) | Cloudflare Health Check (60s interval) | Email alert to `info@bookyou.net` |
| Sentry error capture | SDK in `api/main.py` | Issues queue; review on return |

The absence runbook concerns the surfaces that **do** require operator
attention. Those are listed in §3.

---

## 2. Pre-departure checklist (T-24h before leaving)

Run these in order. Estimated total: 30-45 min.

### Step 1. Verify health probe is green

```bash
curl -sS https://api.autonomath.ai/v1/am/health/deep | jq '.overall.status'
# expected: "healthy"
```

If `degraded` or `unhealthy`, do **not** leave until resolved. Follow
`health_monitoring_runbook.md`.

### Step 2. Verify backup ran in the last 24h

```bash
gh run list --workflow nightly-backup.yml --limit 1
# expected: status=completed, conclusion=success
```

If failed, manually trigger:

```bash
gh workflow run nightly-backup.yml
```

Wait for completion. Do not leave with a stale backup.

### Step 3. Check Stripe webhook delivery success rate (last 7 days)

Stripe Dashboard → Developers → Webhooks → endpoint → "Recent events" tab.
Failure rate must be < 1%. If higher, follow
`stripe_webhook_rotation_runbook.md` §3.

### Step 4. Check Fly.io machine restart count (last 7 days)

```bash
flyctl status -a autonomath-api
# expected: "started" + uptime > 24h
```

If recent restarts > 1, investigate root cause via `flyctl logs` before
leaving.

### Step 5. Confirm pending APPI / data deletion requests are resolved

Open `research/data_deletion_log.md` and `research/consumer_inquiries/`.
Any open ticket with SLA expiring during absence window → resolve before
departure or send 1次応答 with extension notice (§3.4 below).

### Step 6. Toggle status page banner: 「対応遅延」mode

Edit `site/status.html`:

```html
<!-- Before: -->
<div class="status-banner status-ok">通常稼働中</div>

<!-- After: -->
<div class="status-banner status-degraded">
  対応遅延中: {{ absence_start }} 〜 {{ absence_end }} の間、お問い合わせ
  への一次応答は最大 72 時間 (営業日基準) でお返しします。緊急の場合は
  info@bookyou.net 件名に [URGENT] を付けてください。
</div>
```

Commit + push. Cloudflare Pages auto-deploys in 30-60s. Verify:

```bash
curl -sS https://autonomath.ai/status.html | grep -o 'status-degraded'
```

### Step 7. Set Postmark / Gmail auto-responder

Postmark dashboard → Servers → Outbound → Templates →
**operator-absence-autoresponse**. Activate via inbound rule that matches
all `info@bookyou.net` mail not already auto-responded in 24h.

Body (Japanese, brief):

```
お問い合わせありがとうございます。

代表者不在 ({{ start }} 〜 {{ end }}) のため、ご返信に最大 72 時間
(営業日基準) お時間を頂戴いたします。

決済・サービス停止に関わる緊急のご用件の場合は、件名に [URGENT] を
付けて再送信いただけますと、復帰後最優先で対応いたします。

なお、API・MCP サーバーは通常稼働しております。
ステータス: https://autonomath.ai/status.html

Bookyou 株式会社
```

### Step 8. Defer fetch / ingest crons that are safe to skip

These crons are scheduled but their absence for ≤14 days does not affect
production correctness:

| Cron | Effect of skipping |
| --- | --- |
| `scripts/refresh_sources.py` (URL liveness) | Stale `source_fetched_at` timestamps; not user-visible |
| `scripts/cron/precompute_refresh.py` | Materialized views drift; re-runs on resume |
| New `programs` / `case_studies` ingest | Coverage stagnant (acceptable) |
| 法令年次更新 fetch (e-Gov diff) | Laws rev marker stale; manual re-pull on resume |
| New `enforcement_cases` ingest | Same |

**Do nothing** to disable them — they will auto-skip if their input is
stale. The point is to know they will not run successfully and not panic
when GHA emails an "exit 0 with warning" notice.

### Step 9. Verify monitoring alert routing reaches a phone

Cloudflare Health Check notification → email → Gmail mobile push enabled.
Sentry → email → same. UptimeRobot → email → same. Phone must be charged
+ on cellular data + push notifications enabled.

### Step 10. Document the absence window

Create `docs/_internal/absences/YYYY-MM-DD-<reason>.md`:

```markdown
# Absence: YYYY-MM-DD to YYYY-MM-DD

- **operator**: 梅田茂利
- **reason**: <travel | hospitalization | conference | other>
- **reachability**:
  - email: info@bookyou.net (72h SLA, [URGENT] = best-effort 24h)
  - phone: 不可 / 限定的 / 通常 (select one)
- **departure_check**: all 10 steps above completed at YYYY-MM-DDTHH:MMSS+09:00
- **return_check**: TBD on resume
```

Commit + push.

---

## 3. What slows down or stops during absence

These surfaces accumulate backlog. Customers see degraded responsiveness;
nothing breaks irreversibly.

### 3.1 First-line support response

- Normal SLA: 24h JST business day for first response (per
  `operators_playbook.md` §1.1).
- During absence: extended to **72h business day** via status banner +
  auto-responder.
- Justification: APPI § 35 allows 2 weeks for disclosure / deletion
  requests. 特商法 § 32 has no fixed response SLA — 「合理的期間」 is
  the standard. 72h is well within both.

### 3.2 Data correction requests

Auto-responder acknowledges receipt. Actual correction (§4 of
`operators_playbook.md`) defers to resume. Customer does not see incorrect
data removed during absence — log entry remains.

### 3.3 Refund requests

Auto-responder acknowledges receipt. Refund judgement requires manual
review (§3 of `operators_playbook.md`); processed on resume. Stripe's
chargeback window is 60 days, so a 14-day delay does not push customers
into chargeback territory.

If a customer issues a chargeback during absence:

- Stripe gives 20 days to submit evidence.
- Even a 14-day absence leaves 6 days post-resume — still feasible.
- If absence overlaps with chargeback day-15+ → treat as critical, see §6.

### 3.4 APPI deletion requests (§35) — SLA extension

APPI § 35 requires response within "delay-free" reasonable time (実務上
最大 2 週間). During absence:

1. Auto-responder triggers (§7 of pre-departure).
2. On resume, send extended response within 7 days of return.
3. Total = absence (≤14d) + 7d = ≤21d. Still within 2-week reasonable
   doctrine if absence is ≤7d; needs explicit 延長通知 if absence > 7d.
4. Extended response template: `templates/appi_deletion_extension.md`
   (TODO: create on first use; for now, copy from `consumer_inquiries`
   examples and adapt).

**Reasonable extension is allowed under APPI** when the operator provides
notice of the delay and a revised completion estimate. Do **not** silently
miss the SLA — the auto-responder fulfills the notice obligation, but a
manual extension notice is best on the day of return for any open ticket.

### 3.5 Stripe payout reconciliation review

Stripe payouts continue automatically (T+4 business day for JPY).
Reconciliation against `usage_events` cannot be done during absence.
Backlog up to 14 days is trivial; review on resume.

### 3.6 New customer onboarding

Self-service. The signup → Stripe Checkout → API key issuance flow runs
without operator. Welcome email is automatic. Operator only touches
onboarding when a customer explicitly contacts support.

### 3.7 New ingest / enrichment work

Stops entirely. Coverage stays at the pre-absence snapshot. Business
impact: nil for ≤14d (existing data is current to 2026-04-25 baseline).

---

## 4. Operator-touchable monitoring during absence

Even on vacation the operator should glance at these once per 24h. Total
touch time: 2-3 minutes.

### 4.1 Single-glance health check

```
https://autonomath.ai/status.html
```

If banner shows red / unreachable, escalate to §6.

### 4.2 Email triage rule

In Gmail, set a filter:

- From: `*@stripe.com`, subject contains `dispute`, `chargeback`,
  `refund.failed`, `payout.failed` → label "STRIPE-URGENT"
- From: `*@cloudflare.com` subject contains `Health Check` and `down` →
  label "INFRA-URGENT"
- From: customer (info@ inbox) subject contains `[URGENT]` → label
  "CUSTOMER-URGENT"

Check labels once per 24h on mobile. Anything in those labels → §6.

### 4.3 Sentry critical-only filter

Sentry → Alerts → Issue Alert: only fire push notification on
`level:fatal`. Other levels accumulate silently.

---

## 5. What to **not** do during absence

- Do not attempt deploys or migrations from mobile (high error rate, no
  rollback capacity if device dies). Defer to resume.
- Do not silently let the auto-responder lapse > 14 days. If absence
  exceeds 14 days mid-trip, send a manual extension notice from mobile to
  every open ticket and consider invoking `operator_succession_runbook.md`
  bridging measures.
- Do not commit to refunds, data corrections, or contractual changes via
  mobile email. Acknowledge receipt only; defer judgment to resume.
- Do not push to `main` (auto-deploys). One-line typos can take down
  Cloudflare Pages until resume.
- Do not rotate Stripe / Cloudflare / Fly.io credentials from mobile.
  Token + 2FA flows on mobile are error-prone. See
  `stripe_webhook_rotation_runbook.md` for the desktop flow on resume.

---

## 6. Escalation triggers (interrupt vacation)

The following events demand immediate operator action regardless of
absence status. Each one is an actual SLA / legal risk that absence
cannot excuse.

| Trigger | Why it cannot wait | Action |
| --- | --- | --- |
| Stripe webhook failure rate > 5% sustained 30 min | Customers paying without receiving API keys | Open Stripe dashboard from mobile → confirm; if confirmed, follow §3.4 of `incident_runbook.md` from any laptop within 4h |
| Health probe `unhealthy` for > 15 min | Service is genuinely down | `flyctl status` from mobile; if Fly.io outage → follow §(f) of `incident_runbook.md` |
| Personal data breach signal (Sentry pattern, R2 ACL change, etc.) | GDPR Art. 33 = 72h hard window; APPI § 26 速やか | Follow `breach_notification_sop.md` from any laptop within 24h |
| API key leaked publicly | Credentials in the wild | Revoke from any sqlite-capable shell within 1h. See `incident_runbook.md` §(d) |
| 消費生活センター inquiry received | 3 営業日応答 SLA | Acknowledge from mobile; full response within 3 business days even if it means returning early |
| Stripe chargeback day 15+ overlap | 20-day response window closing | Cut absence short to submit evidence |

If any of these fire, execute the relevant runbook from any laptop with
internet. Do not attempt from phone alone — the keystrokes for SQL +
flyctl will lead to typos.

---

## 7. Return checklist (T+0 on resume)

Run in order. Estimated total: 60-90 min depending on backlog size.

### Step 1. Restore status banner

Edit `site/status.html` back to `status-ok` 通常稼働中. Commit + push.
Wait for Cloudflare Pages deploy (~60s). Verify:

```bash
curl -sS https://autonomath.ai/status.html | grep -o 'status-ok'
```

### Step 2. Disable auto-responder

Postmark → Servers → Outbound → Templates → operator-absence-autoresponse
→ Deactivate. Verify by sending self a test email and confirming no
auto-response.

### Step 3. Verify health probe is still green

```bash
curl -sS https://api.autonomath.ai/v1/am/health/deep | jq
```

Drill into any `degraded` check before opening backlog.

### Step 4. Process customer email backlog

Sort `info@bookyou.net` by date ascending. For each:

1. If acknowledged-only by auto-responder → send full response with
   apology for delay.
2. Apply normal `operators_playbook.md` §3 / §4 / §5 / §6 procedures.
3. Update `research/<appropriate_log>.md` with each resolution.

Target: clear backlog within 7 days of return. Send extension notices
for any APPI § 35 ticket > 7d old at this point.

### Step 5. Reconcile Stripe usage backlog

```bash
flyctl ssh console -a autonomath-api -C \
  '/app/.venv/bin/python -m jpintel_mcp.billing.usage_reconcile --since <departure_date>'
```

Verify all paid subscriptions show usage records consistent with
`usage_events` for the absence window.

### Step 6. Re-enable deferred crons + ingest

Resume manually for the first run to verify:

```bash
.venv/bin/python scripts/refresh_sources.py --tier S,A
.venv/bin/python scripts/cron/precompute_refresh.py
```

Then let the GHA / cron schedule pick up subsequent runs.

### Step 7. Review Sentry backlog

Sentry → Issues → unresolved during absence window. Triage:

- Fatal: should already have been escalated; verify root cause is fixed.
- Error: investigate, fix, deploy.
- Warning: log for batch fix in next maintenance window.

### Step 8. Update absence record

Edit `docs/_internal/absences/YYYY-MM-DD-<reason>.md`:

```markdown
- **return_check**: completed at YYYY-MM-DDTHH:MMSS+09:00
- **backlog_summary**:
  - customer emails: <count> processed
  - APPI requests: <count> resolved (extension notices: <count>)
  - Sentry issues: <count> resolved
  - chargebacks: <count> defended
- **lessons_learned**: <free text — fold into next absence's pre-departure>
```

Commit + push.

### Step 9. Run a single end-to-end smoke test

```bash
BASE_URL=https://api.autonomath.ai ./scripts/smoke_test.sh
```

All checks must pass. Investigate any failure before declaring resume
complete.

---

## 8. Cross-references

- `operators_playbook.md` — daily operations, all SLAs and procedures
- `incident_runbook.md` — outage / leak / DDoS / disk full
- `stripe_webhook_rotation_runbook.md` — webhook secret rotation
- `tokushoho_maintenance_runbook.md` — contact info update
- `operator_succession_runbook.md` — long-term incapacity / death
- `breach_notification_sop.md` — APPI / GDPR breach SOP
- `health_monitoring_runbook.md` — uptime probe wiring
- `dr_backup_runbook.md` — backup + restore

---

最終更新: 2026-04-26
責任者: 代表 梅田茂利 (Bookyou株式会社, T8010001213708, info@bookyou.net)
