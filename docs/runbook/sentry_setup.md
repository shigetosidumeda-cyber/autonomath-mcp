# Sentry Setup Runbook — Apply Alert Rules + Dashboard

> **Status**: Manual UI procedure. Sentry's API and Terraform provider exist
> but add infrastructure for a solo zero-touch stack. We keep configs as code
> in `monitoring/` and click through Sentry UI on rare changes.
>
> **Owner**: 梅田茂利 / info@bookyou.net
> **Estimated total time**: 60-90 min for a first-time apply (alerts +
> dashboard + verification). Subsequent edits ~5 min per rule.
> **Prerequisite**: Sentry account active, project `bookyou/autonomath-api`
> already exists with a working DSN deployed to Fly via `flyctl secrets`.
> **Last reviewed**: 2026-05-07

## Step 0 — Provision DSN (do this first if SENTRY_DSN is not yet on Fly)

R8 audit (2026-05-07) flagged this as the **post-launch error monitoring
critical path**. Without these six clicks, every error in production stays
trapped inside Fly machine logs and the operator iPhone gets nothing.

**Pre-state self-check** (10 sec):
```bash
flyctl secrets list -a autonomath-api | grep -E "SENTRY_DSN|JPINTEL_ENV"
# If SENTRY_DSN is absent → continue with Step 0.
# If SENTRY_DSN is present → skip to Step 1.
curl -s https://api.jpcite.com/v1/am/health/deep | jq .sentry_active
# False → Sentry is dark in production.
# True  → already wired.
```

1. **Create / log in to Sentry account**
   - Open <https://sentry.io/signup/> in a browser. Sign up with
     `info@bookyou.net` (the operator address — invoices and billing email
     route here, so it has to match `monitoring/sentry_alert_rules.yml`).
   - On the free Developer plan, the org name should be `bookyou` to match
     the rest of the runbook references.

2. **Create the project**
   - Sentry left nav → **Projects** → **+ Create Project**.
   - **Platform**: Python → FastAPI.
   - **Project name**: `autonomath-api` (legacy distribution name; do NOT
     rename to `jpcite-api` — the source package, console scripts, and PyPI
     distribution are all `autonomath-mcp` per `pyproject.toml`).
   - **Alert frequency**: "Alert me on every new issue" (per-rule overrides
     come in Step 2).
   - **Team**: leave default (solo ops, single team).
   - Click **Create Project**.

3. **Capture the DSN**
   - On the post-create wizard, copy the **DSN** string. It looks like
     `https://abcdef0123456789@o123456.ingest.sentry.io/4501234567890123`.
   - The DSN is a *public* token (Sentry's threat model treats it as such),
     but treat it like a secret: don't paste into Slack / GitHub / commits.
   - Optional: also capture the auth token from Settings → Account → API →
     Auth Tokens if you plan to use `sentry-cli` for release tracking.

4. **Inject DSN into Fly**
   ```bash
   # Single-line form so log scrapers and grep both find the directive:
   flyctl secrets set SENTRY_DSN="https://abcdef0123456789@o123456.ingest.sentry.io/4501234567890123" -a autonomath-api
   # JPINTEL_ENV must already be `prod`. Confirm:
   flyctl secrets list -a autonomath-api | grep JPINTEL_ENV
   # If missing or wrong:
   flyctl secrets set JPINTEL_ENV=prod -a autonomath-api
   ```
   `flyctl secrets set` triggers an automatic redeploy. Wait ~60s for it to
   finish (`flyctl status -a autonomath-api`).

5. **Verify Sentry is now live**
   ```bash
   # 5a. Health probe (read-only, doesn't fire a Sentry event):
   curl -s https://api.jpcite.com/v1/am/health/deep | jq .sentry_active
   # Expect: true

   # 5b. Fire a smoke event (one harmless message):
   flyctl ssh console -a autonomath-api
   python -c "import sentry_sdk, os; sentry_sdk.init(os.environ['SENTRY_DSN'], environment='production'); sentry_sdk.capture_message('runbook smoke', level='info')"
   exit
   # Then in Sentry → Issues, expect a "runbook smoke" event within 60s.
   # If nothing arrives in 2 min, troubleshoot:
   #   * `flyctl logs -a autonomath-api | grep -i sentry`
   #   * Confirm DSN string is correct (re-paste from Sentry → Settings → Client Keys).
   #   * Confirm JPINTEL_ENV=prod (two-gate enforcement).
   ```
   Mark the "runbook smoke" event as **Resolved** so it doesn't pollute the
   first real-incident stream.

6. **Fly secrets convention** — if the operator rotates the DSN later (e.g.
   a leaked client key), repeat step 4 with the new DSN. There is no
   in-code config: the SDK reads `SENTRY_DSN` from the environment on
   process boot, so a `flyctl secrets set` already triggers the correct
   redeploy.

After Step 0 is green (`sentry_active=true` on the deep-health probe AND
the smoke event lands in the Issues stream), continue with Step 1 below.

## What you'll set up

Three things, in this order:

1. **Alert rules** — 8 rules from `monitoring/sentry_alert_rules.yml`, each
   created via Sentry → Alerts → Create Alert.
2. **Dashboard** — 12 widgets from `monitoring/sentry_dashboard.json`, each
   added via Sentry → Dashboards → + Create Dashboard.
3. **Notification routing** — a one-time Project → Settings → Notifications
   tweak so only `level:fatal` triggers iOS push, all severities go to email.

## Pre-flight checklist

Before clicking, verify:

- [ ] You're logged into Sentry as the org owner (Bookyou株式会社).
- [ ] `JPINTEL_ENV=prod` is set on Fly: `flyctl secrets list | grep JPINTEL_ENV`.
- [ ] `SENTRY_DSN` is set on Fly: `flyctl secrets list | grep SENTRY_DSN`.
- [ ] Test event flows: from a Fly SSH session,
      `python -c "import sentry_sdk; sentry_sdk.init('$SENTRY_DSN', environment='production'); sentry_sdk.capture_message('runbook smoke test', level='info')"`
      and confirm it appears in Sentry → Issues within 60s.
- [ ] iOS Sentry app installed on the operator's phone, signed in to the
      `bookyou` org, push notifications enabled in iOS Settings.

If any of those fail, fix that first — there's no point creating alert rules
that fire into a black hole.

## Step 1 — Notification routing (5 min, do once)

This is the global setting that the per-rule actions inherit from. Get it
right first so each rule's email/push settings actually mean what we want.

1. Sentry left nav → **Settings** (gear icon).
2. **User Settings** → **Notifications** (top-right user dropdown for
   account-level).
3. Set **Issue Alerts**: email = `info@bookyou.net`, push = "Only on fatal".
4. **Workflow Notifications**: turn OFF assignment / regression / weekly
   reports for the operator account (you ARE the assignee, so duplicate
   noise).
5. **Quotas**: confirm spike protection is ON at "100% of monthly quota"
   to avoid Sentry itself becoming a billing surprise.
6. Save.

## Step 2 — Alert rules (40-50 min, 8 rules)

For each rule in `monitoring/sentry_alert_rules.yml`, repeat the workflow
below. Estimated 5-7 min per rule once you have the rhythm.

### Workflow per rule

1. Sentry left nav → **Alerts** → **Create Alert**.
2. **What should we alert you about?** → choose:
   - "Issues" for `condition_type: issue` rules
     (`invoice_missing_tnumber`, `backup_integrity_failure`).
   - "Number of Errors" or "Custom Metric" for `condition_type: metric` rules.
3. **Select Project**: `autonomath-api`.
4. **Set conditions**:
   - **Environment** field → set to `production`. This is the belt-and-braces
     filter that backs up the in-code two-gate.
   - **If**: paste the `filter.query` string from the YAML.
   - **When**: set the `aggregate` (count, failure_rate, percentile).
   - **Threshold**: paste the `threshold` value.
   - **Time window**: paste the `window` (1h, 10m, etc.).
5. **Then**: click "+ Add Action" for each entry in `actions[]`:
   - **Email**: target = `info@bookyou.net`. Set the digest cadence by
     adjusting the rule's frequency (5m for critical, 1h for high, etc.) —
     Sentry calls this "Action Interval" or "Snooze".
   - **Push** (only for severity=critical): the global Notification Setting
     from Step 1 already gates this — leave per-rule push config default.
6. **Rule Name**: paste the `name` field verbatim — the `[CRITICAL]`,
   `[HIGH]`, `[MEDIUM]`, `[LOW]` prefix is what makes the alert list scannable.
7. Save.

### Rule-specific notes

- **`webhook_handler_exception_rate`**: the filter query is a multi-logger
  `OR`. Sentry's UI uses `[a,b]` for OR — verify it parses correctly by
  clicking "Preview matching events" before saving.
- **`stripe_usage_events_unsynced`**: this rule depends on
  `scripts/cron/stripe_reconcile.py` emitting messages with extra data.
  Verify the cron is scheduled (Fly Machines → cron) before relying on it.
- **`invoice_missing_tnumber`**: requires code wiring (see "Code wiring
  required" section below). Save the rule but expect 0 fires until the code
  lands — do NOT raise the threshold to 5 thinking that will help; threshold
  1 with 0 fires is the correct posture.
- **`api_5xx_rate`**: failure_rate() metric — Sentry will only let you set
  this on a transaction-type rule, not an issue rule. If the form rejects,
  start over with "Performance" alert type instead of "Issues".
- **`subscription_created_anomaly`**: the z-score field is in `extra.zscore_abs`,
  which Sentry treats as a tag — make sure the cron emits it as a string-coerced
  number (the safe_capture_message wrapper does this).

## Step 3 — Dashboard (15-20 min, 12 widgets)

1. Sentry left nav → **Dashboards** → **+ Create Dashboard**.
2. Title: `jpcite — Solo Ops Dashboard`.
3. For each widget in `sentry_dashboard.json::dashboard.widgets`:
   - Click "+ Add Widget".
   - Choose visualization type matching the YAML's `type` field:
     - `big_number` → "Big Number"
     - `stacked_bar` → "Bar Chart" with stacking on
     - `line` → "Line Chart"
     - `table` → "Table"
     - `histogram` → "Bar Chart" (Sentry doesn't have a true histogram primitive)
   - Paste the `query` string into the Discover query field. For widgets
     with `data_source: raw_sql`, you'll instead use a [Big Query / SQL]
     widget (Sentry calls this "Discover SQL" — only available on
     Business plan and above; if on Developer plan, see Limitations
     section below).
   - Set the `aggregate` and `group_by` from the YAML.
   - Apply the layout: 4 columns × 3 rows, in row/col order from the JSON.
4. Save dashboard. Set as default for the operator account.

### Limitations on Developer (free) plan

Sentry's free Developer plan does NOT support custom SQL widgets or some
advanced visualizations. If we are on the Developer plan, the dashboard
options are:

- **Widgets 1, 2** (Stripe MRR / paying customers): require custom metric
  ingestion, available only on Business+. Workaround: skip these widgets
  and run `scripts/cron/stripe_cost_alert.py --emit-mrr` manually for
  weekly review.
- **Widgets 7, 9, 10, 11** (raw SQL queries against jpintel.db /
  autonomath.db): these aren't Sentry events at all; they need to be
  exposed via an HTTP endpoint and pulled by a separate dashboard tool.
  Workaround for v1: expose them via `GET /v1/am/health/deep` (already
  exists, see `src/jpintel_mcp/api/_health_deep.py`) and read the JSON
  manually.
- **Widgets 3, 4, 5, 6, 8, 12** (pure Sentry events / transactions):
  these work fine on Developer plan. Implement first.

Estimated effort under Developer-plan limitations: **30 min** for the 6
widgets that work, plus operator weekly habit of cat-ing the health-deep
JSON for the rest.

## Step 4 — Verification (5-10 min)

0. **Read-only probe (no event fires)**: confirm
   `curl -s https://api.jpcite.com/v1/am/health/deep | jq .sentry_active`
   returns `true`. This proves the API process completed `_init_sentry` —
   no Sentry quota burn, no PII leakage, just a boolean. The probe is
   surfaced specifically so the operator can verify post-deploy without
   having to fire a smoke event each time.

1. **Email test**: Sentry → Settings → Notifications → "Send test email".
   Confirm `info@bookyou.net` receives within 1 min.
2. **Push test**: trigger a fake fatal-level event:
   ```bash
   flyctl ssh console
   python -c "import sentry_sdk; sentry_sdk.init(__import__('os').environ['SENTRY_DSN'], environment='production'); sentry_sdk.capture_message('runbook push test', level='fatal')"
   ```
   Confirm phone gets a push within 60s. Then **resolve** the issue in
   Sentry to clear it.
3. **Rule firing**: pick one low-impact rule (e.g.
   `deprecated_endpoint_hit`), temporarily set its threshold to 1, hit
   a deprecated endpoint via curl, confirm the alert fires after the
   `frequency` window, then revert the threshold.
4. **Dashboard load**: open the dashboard, confirm at least 6 widgets
   render with non-zero data (the SQL ones may be empty until cron runs).

## Code wiring required (NOT done yet)

These three rules in `sentry_alert_rules.yml` reference metrics our
codebase does NOT currently emit. The runbook can save the rules, but
they will silently never fire until someone wires the emitters.
Do this in a follow-up code task; do NOT skip the rules — they're
correct as soon as the emitter lands.

| Rule ID | What's missing | Where to wire it |
|--|--|--|
| `invoice_missing_tnumber` | `safe_capture_message("invoice missing tnumber", level="error", invoice_id=...)` when invoice template lacks T-number | `src/jpintel_mcp/billing/stripe_edge_cases.py` — add a `_assert_invoice_tnumber()` check before sending invoice |
| `subscription_created_anomaly` | Z-score computation against 7-day median + emit `safe_capture_message(metric="stripe.webhook.sub_created.zscore", zscore_abs=...)` | extend `scripts/cron/webhook_health.py` |
| `deprecated_endpoint_hit` | `safe_capture_message(metric="api.deprecation.hit", level="warning", route=...)` from the deprecation middleware | new middleware OR extend `src/jpintel_mcp/api/_deprecation_middleware.py` |

Total estimated wiring: **2-3 hours of code** across 3 files. None of these
are launch-blocking — alert rules without emitters are just inert.

## When something fires

The flow when an alert hits:

1. Operator's phone gets a push (severity=critical only) OR an email
   (all severities).
2. Operator clicks through the Sentry email/push to the issue page.
3. Issue page should have:
   - The triggering event with full request context (URL, status, headers
     post-scrub)
   - The structlog channel (e.g. `autonomath.billing.webhook`)
   - The most recent stack trace
4. Operator decides:
   - Real bug → reproduce locally, fix, deploy. Mark as "Resolved in next
     release" in Sentry; auto-resolves on next deploy if release tracking
     is on.
   - False positive → adjust the rule threshold or add a `before_send`
     filter; mark as "Ignored / Spam".
   - Already known issue → merge into existing issue.
5. If it's a `[CRITICAL]` event, log the incident in
   `docs/_internal/incidents/YYYY-MM-DD-<slug>.md` per the SLA breach
   process in `monitoring/sla_targets.md`.

## Maintenance schedule

- **Weekly** (Mon 10am JST, 5 min): scan the Sentry weekly digest email,
  triage anything older than 7 days.
- **Monthly** (1st of month, 15 min): review false-positive rate per rule,
  tighten or loosen thresholds. Update `monitoring/sentry_alert_rules.yml`
  to match (source of truth).
- **Quarterly** (15 min): review SLO targets in `monitoring/sla_targets.md`
  vs actual performance. Adjust if structurally needed.
- **On launch traffic milestones** (10x increase): revisit thresholds —
  what works at 100 req/day breaks at 10k req/day.

## Rollback

If alerts go haywire (e.g., a rule fires 1000x in an hour due to a bad
threshold), the fastest rollback is:

1. Sentry → Alerts → find the rule → toggle "Status: Inactive".
2. The rule stops firing immediately, no events lost (Sentry still ingests
   them, just doesn't notify).
3. Fix the threshold in `monitoring/sentry_alert_rules.yml`, edit the rule
   in Sentry to match, toggle back to Active.

If the dashboard is broken (widgets erroring), Dashboards → ⋯ menu →
Delete; recreate from `sentry_dashboard.json`. No data loss because
Sentry stores events, not dashboard layouts.

## Related docs

- `monitoring/sentry_alert_rules.yml` — source of truth for rules
- `monitoring/sentry_dashboard.json` — source of truth for dashboard widgets
- `monitoring/sla_targets.md` — what each rule defends
- `docs/observability.md` — full Sentry init context (two-gate, scrubbers,
  cron capture)
- `docs/runbook/disaster_recovery.md` — what to do AFTER a critical alert fires
- `src/jpintel_mcp/observability/sentry.py` — `safe_capture_*` helpers used
  by the cron emitters referenced above
- `src/jpintel_mcp/api/sentry_filters.py` — PII scrubbing rules; if a rule
  starts firing on PII-rich content, the scrubber needs an extension
