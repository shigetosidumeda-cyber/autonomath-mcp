---
title: Sentry Alert Escalation Runbook
updated: 2026-05-07
operator_only: true
category: monitoring
---

# Sentry Alert Escalation Runbook (G4)

**Owner**: 梅田茂利 (info@bookyou.net) — solo zero-touch
**Operator**: Bookyou株式会社 (T8010001213708)
**Last reviewed**: 2026-05-07
**Related**: `docs/runbook/sentry_setup.md` (account setup + DSN provisioning), `monitoring/sentry_alert_rules.yml` (the rule definitions this runbook routes), `docs/runbook/db_corruption_recovery.md` / `docs/runbook/fly_machine_oom.md` / `docs/runbook/stripe_chargeback_response.md` / `docs/runbook/cloudflare_abuse_mitigation.md` (the four escalation destinations).

This runbook defines **what the operator does, in what order, when a Sentry
alert fires**. It exists because the jpcite stack is solo + zero-touch —
there is no on-call rotation, no PagerDuty, no team Slack. The alert IS the
operator action.

## 1. Solo + zero-touch policy

The CONSTITUTION-level constraint:

* **No team to escalate to.** "Escalation" in this codebase means picking
  the right destination runbook from §4 and executing it.
* **No paging service.** Sentry → email → operator iPhone (push notification
  enabled) is the entire signal path. Do not introduce PagerDuty, OpsGenie,
  or BetterStack — they violate solo + zero-touch ops.
* **No silent dismissal.** Every alert must end in either Resolved (with
  a root-cause note) or Ignored (with a justified rule weakening in
  `monitoring/sentry_alert_rules.yml` and a CHANGELOG line). "I'll deal
  with it later" is not a state.

## 2. Alert severity SLA

| Severity   | Time-to-ack | Time-to-mitigation | Action shape                              |
|------------|-------------|---------------------|-------------------------------------------|
| `critical` | 5 min       | 30 min              | Drop everything; execute the matching §4 destination runbook. |
| `high`     | 1 hour      | 4 hours             | Same destination runbook, but re-orderable around current task. |
| `warning`  | 1 business day | next maintenance window | Triage; usually a code-fix PR rather than ops action. |
| `info`     | best effort | n/a                 | Read the issue; no action required unless it surfaces a pattern. |

Time-to-ack means **operator opens the Sentry issue and writes a one-line
comment** ("triaging" / "deferring" / "false positive — see <ref>"). Sentry
events stay in `Unresolved` until ack — the iPhone push reminder repeats
every 60 min (Sentry default for unresolved critical) until ack.

The 5-min critical ack window is a **hard discipline target**, not a hosted
guarantee. The operator iPhone is on Do Not Disturb 23:00-07:00 JST except
for Sentry critical (configured in iOS Notifications → Sentry → "Time
Sensitive"). Outside DnD, 5 min is realistic; inside DnD, the realistic
floor is the time it takes the iPhone to wake the operator (often 5-10 min).

## 3. Pre-state self-check (every alert)

Before opening any destination runbook, **30 seconds of triage** to confirm
the alert is real and disambiguate the destination:

```bash
# 3a. Confirm the alert isn't a known false positive (e.g. a deploy in
#     flight, a CI smoke test, a cron probe).
gh run list -R shigetosidumeda-cyber/autonomath-mcp --limit 5
# Active deploy / smoke run within ±5 min of the alert ⇒ likely correlated.

# 3b. Production health.
curl -fsS --max-time 30 https://api.jpcite.com/v1/am/health/deep | jq .
# 200 + all "ok" ⇒ the alert is component-local, not whole-stack.
# 5xx ⇒ at least one component is hard-down.

# 3c. Fly machine status.
flyctl status -a autonomath-api
# state="started" + healthy ⇒ infra is up.
# state="stopped" or restart_count > 1 ⇒ jump to fly_machine_oom.md.

# 3d. UptimeRobot history (browser, no CLI).
#     Visit https://stats.uptimerobot.com/<jpcite-public-page>
#     If 5+ consecutive failures across 5 monitors ⇒ whole-stack outage,
#     widen scope to disaster_recovery.md.
```

## 4. Alert → destination runbook mapping

Sentry alert rule names map 1:1 to destination runbooks. The rule names
below match `monitoring/sentry_alert_rules.yml` exactly so a CTRL-F from
the alert email finds the runbook.

### 4.1 Critical alerts (5 min ack / 30 min mitigation)

| Rule name                       | Destination runbook                              | Why critical                                      |
|---------------------------------|--------------------------------------------------|---------------------------------------------------|
| `database_corruption_detected`  | `docs/runbook/db_corruption_recovery.md`         | Customer data integrity at risk; every minute the API serves on a corrupt DB compounds bad rows. |
| `machine_oomkill`               | `docs/runbook/fly_machine_oom.md`                | API is dark until Fly auto-restart finishes.      |
| `stripe_dispute_received`       | `docs/runbook/stripe_chargeback_response.md`     | 7-day SLA starts the moment the webhook fires.    |
| `cloudflare_ddos_detected`      | `docs/runbook/cloudflare_abuse_mitigation.md`    | Origin (Fly) saturation imminent; CF protection in front but rate-limits unguarded. |
| `boot_gate_fail`                | `docs/runbook/secret_rotation.md` Verify section | Production refusing connections post-deploy.      |
| `sentry_dsn_dark`               | `docs/runbook/sentry_setup.md` Step 0            | Self-referential: this runbook is dark.           |

### 4.2 High alerts (1 hour ack / 4 hours mitigation)

| Rule name                          | Destination                                         |
|------------------------------------|------------------------------------------------------|
| `cron_job_failed`                  | `docs/runbook/disaster_recovery.md` §3.5 (drill failure) — replay the cron, capture stderr, file an issue if it repeats. |
| `backup_integrity_drift`           | `docs/runbook/disaster_recovery.md` §3.5            |
| `litestream_replication_lag`       | `docs/runbook/litestream_setup.md` §"verify"        |
| `r2_bucket_403`                    | `docs/runbook/disaster_recovery.md` §3.3 (R2 token compromise / accidental revoke) |
| `cors_403_surge`                   | `docs/runbook/cors_setup.md` §"add origin"          |
| `cloudflare_abuse_pattern`         | `docs/runbook/cloudflare_abuse_mitigation.md`       |
| `audit_seal_verification_failure`  | this runbook §6 (special case)                      |

### 4.3 Warning alerts (1 business day)

| Rule name                       | Action                                              |
|---------------------------------|------------------------------------------------------|
| `unhandled_exception_uncategorized` | Open the Sentry issue; if reproducible, file a code-fix PR. |
| `deprecated_route_5xx_below_threshold` | Note in CHANGELOG; consider sunsetting the route. |
| `slow_query_log_p99_regression` | Run EXPLAIN QUERY PLAN; index if appropriate.       |

### 4.4 Info alerts

No action required. Sentry → Resolve → Sentry tags the issue as historical
context for future pattern detection.

## 5. Ack workflow (every alert)

```text
1. Open the Sentry issue from the email link.
2. Add a comment within the §2 SLA. Template:
       triaging — <yyyy-mm-dd HH:MM JST> — destination: docs/runbook/<file>.md
3. Execute the destination runbook.
4. Resolve the Sentry issue with a final comment naming the root cause + fix.
       resolved — <yyyy-mm-dd HH:MM JST> — root cause: <one line> — fix: <one line>
       evidence: <link or commit hash>
5. If the alert was a false positive, edit
   `monitoring/sentry_alert_rules.yml` to tighten the rule (or add a
   condition exclusion) and commit + deploy. Open the editor at the
   exact rule by rule name.
```

## 6. Special cases

### 6a. Audit-seal verification failure (`audit_seal_verification_failure`)

Triggers when `GET /v1/me/audit_seal/{call_id}` returns 4xx for a recent
seal. Two real causes (most are key rotation race):

```bash
# 6a-1. Check current key set.
flyctl secrets list -a autonomath-api | grep JPINTEL_AUDIT_SEAL_KEYS
# Expect: leftmost key signs new seals; trailing keys verify older seals.

# 6a-2. If a key was rotated within the last 90s, this is a deploy race —
#       the new key landed but Fly hasn't propagated to the verifier
#       machine yet. Wait 60s, retry.
sleep 60
curl -fsS https://api.jpcite.com/v1/me/audit_seal/<call_id> | jq .

# 6a-3. If a key was prematurely dropped from the rotation list, append the
#       previous key back per docs/runbook/secret_rotation.md.
```

### 6b. Sentry DSN dark (`sentry_dsn_dark`)

This rule is self-referential — if Sentry DSN is unset or invalid,
`sentry_dsn_dark` cannot fire by definition. The detection pivot is the
`/v1/am/health/deep` `sentry_active` field, polled by UptimeRobot. If
UptimeRobot's "Sentry DSN active" monitor flatlines, treat that as the
critical alert and execute `docs/runbook/sentry_setup.md` Step 0.

### 6c. Multiple critical alerts within 5 min

If 2+ critical alerts fire within 5 min, **batch the ack** (one comment
per issue is fine, but write them in fast succession — < 5 min cumulative)
and then prioritize destination runbooks in this order:

1. `database_corruption_detected` (data integrity)
2. `machine_oomkill` (uptime)
3. `cloudflare_ddos_detected` (uptime + cost)
4. `stripe_dispute_received` (billing — 7-day SLA, more headroom)
5. `boot_gate_fail` (uptime, but usually self-mitigates if Fly rolls back)
6. `sentry_dsn_dark` (observability — important but not customer-facing)

## 7. Verify (every alert response must complete this)

```text
A. Sentry issue is Resolved (not Ignored unless §5 step 5 followed).
B. The destination runbook's own Verify section is complete.
C. UptimeRobot has a clean 60-min window post-mitigation.
D. CHANGELOG.md has a one-liner if the response involved a code change
   or a Sentry rule edit.
E. `analytics/incidents.jsonl` (operator-private, off-Fly) has a row.
   Schema:
       {ts_jst, alert_rule, ack_latency_min, mitigation_latency_min,
        runbook, root_cause, fix_kind, customer_facing}
   This drives the quarterly DR drill review.
```

## 8. Rollback

If the alert was a false positive and the rule was tightened in §5 step 5,
the rollback is reverting the `monitoring/sentry_alert_rules.yml` commit
and redeploying. **Do NOT** widen rules to "warn but continue" silently —
every loosening must have an attached commit message explaining why and
must be on the next quarterly DR drill review list.

## 9. Failure modes

* **Operator unavailable (illness, travel without coverage)**: solo +
  zero-touch has no fallback. The contractual obligation is the §S2 boot
  gate — `boot_gate_fail` self-mitigates by Fly rolling back to the prior
  green machine. `database_corruption_detected` and `machine_oomkill`
  degrade to whole-API outage; UptimeRobot SMS alerts the operator's
  partner contact (if configured) but no one else has Fly access. Mitigate
  via the planned-absence policy: pre-stop the API for known-coverage
  windows (`flyctl scale count 0`) rather than risk an unattended outage.
* **Sentry itself is down**: rare but possible. Detection collapses to
  UptimeRobot. Treat all UptimeRobot 502 / 5xx alerts as `critical` until
  Sentry returns and the back-fill catches up.
* **iPhone Notifications muted (DnD misconfigured)**: weekly self-check —
  send an `info`-level Sentry test event and confirm push within 60s. If
  fail, rebuild the iOS notification config per `docs/runbook/sentry_setup.md`.
* **Email delivery to `info@bookyou.net` lapsed**: SES bounce / DMARC
  drift. The `tls-check.yml` workflow verifies MX + DMARC weekly; if it
  fails for `bookyou.net` MX, all Sentry email + Stripe dispute email
  collapse simultaneously. Fix DMARC + re-verify per the email provider.

## 10. Items needing user action (one-time prerequisites)

* Sentry DSN provisioned per `docs/runbook/sentry_setup.md` Step 0.
* Sentry alert rules registered per `monitoring/sentry_alert_rules.yml`
  (the rule names in §4 must match exactly).
* iPhone Sentry app installed + push notifications enabled + Time
  Sensitive flag set on the Sentry app (overrides Do Not Disturb for
  critical only).
* `JPINTEL_OPERATOR_KEY` (an unrestricted self-issued API key for the
  operator) saved in 1Password — used in §3, §6a, and §7 verifies.
* UptimeRobot monitors for `api.jpcite.com/v1/health` and the
  `sentry_active` deep-health field, alerting `info@bookyou.net`.
* Calendar reminder for the weekly Sentry test-event self-check (§9).
