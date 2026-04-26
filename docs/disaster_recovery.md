# AutonoMath — Disaster Recovery Plan v2

Internal ops reference. Solo operator (梅田茂利, info@bookyou.net). Zero-touch, no 24/7 NOC.

最終更新: 2026-04-25 · Launch target: 2026-05-06 · App: `autonomath-api` (Fly.io nrt) · Pages: Cloudflare · Billing: Stripe live

For minute-by-minute playbooks see `docs/_internal/incident_runbook.md`.
For successor handoff see `docs/solo_ops_handoff.md`.

---

## 0. Scope and SLO alignment

This plan defines RPO (Recovery Point Objective — max data loss) and RTO (Recovery Time Objective — max user-visible downtime) for ten operational failure scenarios.

- **SLO target**: 99.5% monthly uptime once HA-ready (current SLA doc states 99.0% beta target — see `docs/sla.md`). At 99.5%, monthly downtime budget is **21.6 min**.
- All 10 scenarios are designed so that median observed downtime stays inside the budget. Scenarios 2 / 6 / 9 individually exceed the monthly budget if they fire — a single occurrence of those moves the month into SLA-miss territory and triggers a quarterly review.
- "Operator incapacity" (Scenario 10) is out of SLO — it is a business-continuity scenario, not a uptime scenario.

---

## 1. Scenario matrix (RPO / RTO formal)

| # | Scenario | RPO | RTO | Mechanism |
|---|---|---|---|---|
| 1 | VM crash (single Fly machine) | 0 | 30s | Fly auto-restart |
| 2 | Volume corruption (`/data/jpintel.db` malformed) | 24h | 30 min | R2 nightly snapshot restore |
| 3 | R2 outage (backup target unreachable) | N/A | instant | Read path served from Fly volume cache; backups queue and retry |
| 4 | Stripe outage (Checkout / webhook / API) | 0 | passive | Usage record queue replay (no user write loss) |
| 5 | Cloudflare Pages outage | 0 | 5 min | Cloudflare auto-recovery; static mirror via R2 fallback |
| 6 | DNS / domain expiry | 0 | 1-2 h | Auto-renew + DNSSEC + registrar alert |
| 7 | API key leak (single customer key on GitHub / X) | 0 | 5 min | Revoke + force rotate |
| 8 | PEPPER leak (server-side hashing secret) | 0 | 4-8 h | Re-hash all `api_keys` + force-rotate every customer |
| 9 | Fly nrt region outage | 0 | 1 h | Manual DNS flip to `fra` (Frankfurt) standby |
| 10 | Operator (梅田) incapacity | 0 | 30+ days | Deadman switch + handoff doc → successor |

Sub-5-minute scenarios: 1 / 3 / 4 / 5 / 7. Sub-2-hour: 2 / 6 / 9. Multi-day: 8 (operationally) / 10 (business).

---

## 2. Per-scenario detail

Each scenario lists: **Detection** (how we notice) / **Runbook** (numbered steps) / **Blast radius** (customers vs internal-only) / **Post-mortem** (template anchor).

### Scenario 1 — VM crash

- **Detection**: Sentry "Service unavailable" alert + UptimeRobot `/healthz` fail (1 min interval). Fly's own restart loop usually beats both.
- **Runbook**:
  1. `flyctl status --app autonomath-api` — confirm machine state (`stopped` or `crashed`).
  2. If Fly is mid-auto-restart: wait 60 s, re-check.
  3. If still down after 90 s: `flyctl machine restart <id> --app autonomath-api`.
  4. Re-smoke: `BASE_URL=https://api.autonomath.ai ./scripts/smoke_test.sh`.
- **Blast radius**: All customers, ~30 s. No data loss (SQLite WAL flush on graceful stop).
- **Post-mortem**: Template §A. Required if more than 2 occurrences in 30 d.

### Scenario 2 — Volume corruption

- **Detection**: Sentry `sqlite3.DatabaseError: database disk image is malformed`, or `/meta` returns 500, or `PRAGMA integrity_check` fails on cron.
- **Runbook**: see `_internal/incident_runbook.md` §(c) full steps. Summary:
  1. `flyctl scale count 0 --app autonomath-api` (stop writes).
  2. `flyctl volumes list --app autonomath-api` — note current volume id.
  3. Pull latest R2 snapshot: `aws s3 cp s3://autonomath-backups/jpintel.db/<latest>.db.gz . --endpoint-url $R2_ENDPOINT`.
  4. `shasum -a 256 -c <latest>.db.gz.sha256` (must verify).
  5. `gunzip` and SFTP to `/data/jpintel.db` on a fresh volume.
  6. `flyctl scale count 1 --app autonomath-api`.
  7. Verify `/meta.total_programs` matches pre-incident value within 1%.
- **Blast radius**: All customers, ~30 min. RPO 24 h means writes since last 04:00 JST snapshot are lost (anonymous quota counters + new api_keys signups + new stripe_events idempotency rows).
- **Post-mortem**: Template §A. Always required.

### Scenario 3 — R2 outage

- **Detection**: Backup cron `aws s3 cp` exits non-zero. Cloudflare R2 status page red.
- **Runbook**:
  1. Acknowledge: backups queue locally on Fly volume under `/data/backup_queue/` (capped at 7 d / 5 GB).
  2. Wait for R2 recovery (status page).
  3. On recovery, cron re-attempts queued uploads; verify next `aws s3 ls` shows the gap filled.
  4. If queue exceeds 5 GB: rotate to secondary R2 bucket in EU (`autonomath-backups-eu`) — see Scenario 9 cross-region detail.
- **Blast radius**: Internal-only. Customer reads / writes unaffected (DB lives on Fly volume; R2 is destination not source).
- **Post-mortem**: Template §B. Required if outage > 4 h.

### Scenario 4 — Stripe outage

- **Detection**: Stripe webhook 5xx from upstream, Stripe status page red, or `stripe events list` API hangs.
- **Runbook**:
  1. Existing customers with valid keys: continue serving (we don't gate per-request on Stripe).
  2. New signups: Checkout fails — site shows "Stripe is currently degraded" banner from `site/_data/stripe_health.json` (Cloudflare KV refresh every 5 min).
  3. Usage records: queued in `stripe_usage_queue` table, replayed by `scripts/replay_stripe_usage.py` post-recovery.
  4. Webhooks: Stripe retries automatically with exponential backoff for up to 3 days. We do not need to reconstruct.
- **Blast radius**: New signups blocked, existing customers unaffected. RPO=0 because we never lose usage records.
- **Post-mortem**: Template §B. Required if outage > 1 h or queue > 10k records.

### Scenario 5 — Cloudflare Pages outage

- **Detection**: UptimeRobot fail on `https://autonomath.ai/`. API may stay up via `api.autonomath.ai` direct.
- **Runbook**:
  1. Confirm Cloudflare status page.
  2. If Cloudflare-wide: nothing to do — recovery is upstream.
  3. If only Pages: switch DNS for `autonomath.ai` to a Cloudflare Worker that serves a cached `index.html` from KV.
  4. Post a pinned status note (no ETA) on X.
- **Blast radius**: Marketing + docs site only. API customers (using `api.autonomath.ai` directly) unaffected.
- **Post-mortem**: Template §B. Required if site > 30 min down.

### Scenario 6 — DNS / domain expiry

- **Detection**: Cloudflare Registrar email + UptimeRobot DNS-resolution failure + 30-day-prior calendar reminder.
- **Runbook**:
  1. Auto-renew is enabled on Cloudflare Registrar (annual). Verify card on file is current.
  2. If renewal failed: pay manually via dashboard within 30 d grace period.
  3. DNSSEC: re-publish DS record at registrar if rotated.
  4. If domain hijack suspected: file Cloudflare abuse + register `autonomath.com` / `.app` as defensive backup (Y2 budget).
- **Blast radius**: All customers (DNS resolution fail = total outage). RTO 1-2 h includes propagation.
- **Post-mortem**: Template §A. Always required.

### Scenario 7 — API key leak

- **Detection**: Operator sees `sk_live_…` on GitHub / X / Discord, or affected user emails.
- **Runbook**:
  1. Revoke: `UPDATE api_keys SET revoked_at = datetime('now') WHERE key_prefix = '<first_8_chars>'` via `flyctl ssh console`.
  2. Email customer with rotation link `/v1/me/rotate-key`.
  3. Audit `request_log` for the leaked prefix to estimate abuse window.
  4. Refund any abusive usage (prorated against month-to-date).
- **Blast radius**: Single customer. Internal-only unless customer reports public abuse.
- **Post-mortem**: Template §C. Required if > 5 leaks / quarter (signals UX bug).

### Scenario 8 — PEPPER leak (server-side hashing secret)

- **Detection**: PEPPER value spotted in a leak (e.g. `flyctl secrets` accidentally piped to a log; misconfigured CI). High-severity Sentry breadcrumb on any unexpected secret read.
- **Runbook**:
  1. Rotate PEPPER: `flyctl secrets set API_KEY_PEPPER=$(openssl rand -hex 32)`.
  2. Run `scripts/rehash_api_keys.py` — for each row, `key_hash_v2 = sha256(key + new_pepper)`. Old `key_hash` column kept for 7 d as `key_hash_v1`.
  3. Force every customer to rotate within 7 d (`/v1/me/rotate-key` mandatory; old keys 401 after grace).
  4. Email all active customers with subject "Security action required: rotate your API key by <date>".
  5. After 7 d: `ALTER TABLE api_keys DROP COLUMN key_hash_v1`.
- **Blast radius**: All customers, RTO 4-8 h depending on email response. RPO=0 (hashes survive rotation).
- **Post-mortem**: Template §A. Always required + lessons-learned blog post.

### Scenario 9 — Fly nrt region outage

- **Detection**: Fly status page red for nrt + UptimeRobot fail + `flyctl status` returns "no machines".
- **Runbook**:
  1. Confirm nrt-only (not Fly-wide) via status page.
  2. Bring up standby machine in `fra`: `flyctl machine clone <nrt-id> --region fra --app autonomath-api`. Volume is auto-replicated nightly via cross-region R2 snapshot (see §3).
  3. Restore latest R2 snapshot to fra volume (~5 min).
  4. DNS flip: Cloudflare dashboard → `api.autonomath.ai` A record → fra IP. TTL 60 s.
  5. Wait propagation, verify smoke test.
  6. On nrt recovery: flip DNS back, decommission fra clone (next quarterly drill rotation).
- **Blast radius**: All customers, ~1 h. RPO=0 if cross-region snapshot is fresh (< 24 h).
- **Post-mortem**: Template §A. Always required.

### Scenario 10 — Operator (梅田) incapacity

- **Detection**: Deadman switch — operator must check in via `scripts/deadman_checkin.sh` weekly. Missed 2 consecutive weeks → automated email to designated successor (see `docs/solo_ops_handoff.md` §Emergency contacts).
- **Runbook**:
  1. Successor receives deadman alert + 1Password emergency-access invite.
  2. Successor reads `docs/solo_ops_handoff.md` (1-day-readable runbook).
  3. Successor decides: continue ops / freeze billing / shut down with refund / sell to acquirer.
  4. If shut down: trigger `scripts/wind_down.py` — refunds month-to-date, exports customer data, posts shutdown notice, files Bookyou KK 解散 with 税理士.
- **Blast radius**: All customers + 法人 entity. RTO 30+ days reflects realistic successor onboarding + legal wind-down timeline.
- **Post-mortem**: N/A (terminal scenario).

---

## 3. Backup architecture

### 3.1 Daily R2 snapshot

- **Schedule**: 04:00 JST daily via GitHub Actions `.github/workflows/nightly-backup.yml` (Fly cron is unreliable for this).
- **Format**: `jpintel.db` is `VACUUM INTO`'d to a temp copy, `gzip -9`'d, `sha256sum`'d, then `aws s3 cp` to `s3://autonomath-backups/jpintel.db/YYYY-MM-DD.db.gz` + `.sha256` sidecar.
- **Retention**: 90 days (R2 lifecycle rule). Day 91+ moves to Infrequent Access tier; day 365+ deletes.
- **Verify**: SHA256 sidecar checked on every restore. Monthly random-pick verify by drill (see §4).
- **autonomath.db**: 8.29 GB unified primary — backed up weekly (Sunday 04:00 JST), not daily, due to size and read-only nature.

### 3.2 Weekly cross-region

- **Schedule**: Sunday 06:00 JST.
- **Source**: latest R2 nrt-region object.
- **Target**: `s3://autonomath-backups-eu/` (R2 EU jurisdiction) + `s3://autonomath-backups-na/` (R2 NA).
- **Purpose**: Region-level R2 outage survival (Scenario 3 worst case) + jurisdictional redundancy.

### 3.3 Monthly drill schedule

| Quarter | Scenarios drilled | Pass criterion |
|---|---|---|
| Q1 | 1 (VM crash) + 2 (volume restore) | RTO under target, smoke green |
| Q2 | 3 (R2 outage simulated by IAM revoke) + 5 (Pages mirror failover) | Queue replays cleanly |
| Q3 | 7 (API key leak end-to-end revoke) + 8 (PEPPER rotation on staging) | Customer email template verified |
| Q4 | 9 (DNS flip to fra) + 10 (handoff doc walkthrough by 3rd party) | Successor reads doc, simulates day-1 ops |

Each drill output goes to `docs/_internal/dr_drill_log.md` with date, scenario id, observed RTO, deviations, action items.

---

## 4. Post-mortem templates

### Template §A — Customer-facing scenarios (1, 2, 6, 8, 9)

```
# Post-mortem: <scenario-id> — <one-line summary>

Date: YYYY-MM-DD
Duration: HH:MM (start UTC) → HH:MM (recovery UTC)
Customers affected: <count> / <% of MAU>
RPO observed: <minutes>     (target: <table value>)
RTO observed: <minutes>     (target: <table value>)
SLO impact: <minutes consumed of monthly 21.6-min budget>

## What happened (timeline, UTC)

- HH:MM — first symptom
- HH:MM — operator paged
- HH:MM — root cause identified
- HH:MM — fix applied
- HH:MM — smoke green, customers restored

## Root cause

<2-3 paragraphs, blameless>

## Action items

- [ ] <runbook update> / owner: ops / due: D+7
- [ ] <code fix> / owner: ops / due: D+14
- [ ] <invariant test added> / owner: ops / due: D+30

## Customer comms

- [x] Status page note posted at HH:MM
- [x] Affected customer email sent at HH:MM
- [ ] Public retrospective blog post by D+30 (if customer-affecting > 1 h)
```

### Template §B — Internal-only scenarios (3, 4, 5)

Lighter format: 1 paragraph what / 1 paragraph why / action items list. No customer comms section.

### Template §C — Per-incident scenarios (7)

Single line in `docs/_internal/leak_log.md`: date, prefix, customer_id, abuse window, refund amount, source (where leaked).

---

## 5. References

- `docs/sla.md` — public SLA (99.0% beta target)
- `docs/_internal/incident_runbook.md` — minute-by-minute playbooks
- `docs/solo_ops_handoff.md` — Scenario 10 successor doc
- `docs/_internal/observability_dashboard.md` — Sentry / UptimeRobot config
- `.github/workflows/nightly-backup.yml` — backup cron source-of-truth
