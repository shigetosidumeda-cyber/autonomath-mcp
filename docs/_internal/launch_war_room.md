# Launch war room — jpcite

**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26

**Launch: 2026-05-06 (Wed) 09:00 JST.** Solo on-call. Read this once at T-24h, re-skim at T-1h.

All times JST. `<DOMAIN_PLACEHOLDER>` = final domain (rebrand pending).

---

## Dashboards (open all in tabs before T-1h)

Pin these five in a dedicated browser window and leave it on a second screen.

| # | What | URL |
|---|---|---|
| 1 | Fly metrics (app `autonomath-api`) | `https://fly.io/apps/autonomath-api/metrics` |
| 2 | Sentry issues (project `jpintel-mcp`) | `https://sentry.io/organizations/<org>/issues/?project=<id>` |
| 3 | Stripe webhooks / events | `https://dashboard.stripe.com/webhooks` |
| 4 | Cloudflare analytics (zone `<DOMAIN_PLACEHOLDER>`) | `https://dash.cloudflare.com/<account>/<DOMAIN_PLACEHOLDER>/analytics/traffic` |
| 5 | UptimeRobot status | `https://uptimerobot.com/dashboard` |

---

## Timeline

### T-1h (08:00) — Smoke + staging

```bash
# Local staging smoke (expect all green)
BASE_URL=https://api.jpcite.com ./scripts/smoke_test.sh

# Confirm prod DB populated
curl -s https://api.jpcite.com/meta | jq .total_programs
# Expect: 6771 (non-zero at minimum)

# Latest release recorded
flyctl releases --app autonomath-api | head -5
```

If any smoke probe fails or `/meta.total_programs == 0`: **stop**. Do not announce. Fix or postpone.

Open all five dashboards. Confirm Sentry is quiet (< 5 errors/hr baseline). Confirm Stripe webhook endpoint `Status: Enabled`.

### T-0 (09:00) — JP-side announce

Post in this exact order, 2 minutes apart. **Note: HN is shifted to 22:30 JST** (09:30 ET = HN morning peak window). Canonical timeline lives in `docs/_internal/launch_dday_matrix.md` §0 Firing order summary.

| Channel | Link / ID | Status |
|---|---|---|
| Zenn article (AutonoMath intro) | `https://zenn.dev/<user>/articles/________` | [ ] |
| X thread (tweet ID of first post) | `https://x.com/<user>/status/________` | [ ] |
| LinkedIn post (English, 09:00 JST) | `https://www.linkedin.com/posts/________` | [ ] |

### T+13.5h (22:30) — HN announce (lead channel)

| Channel | Link / ID | Status |
|---|---|---|
| Hacker News (Show HN: ...) | `https://news.ycombinator.com/item?id=________` | [ ] |
| HN first comment (post within 60s of submission) | `<comment id>` | [ ] |
| X reply with `Also on HN: [URL]` (1 reply only) | `https://x.com/<user>/status/________` | [ ] |

After posting, DO NOT refresh HN frontpage repeatedly. Active monitoring window is 22:30-25:00 JST (90 min); after 25:00 sleep is non-negotiable.

### T+1h (10:00) — First health check

Check, in order, and note values:

- Sentry: new issues in last hour? Any `event_level >= error`? Any Stripe / DB error?
- Fly metrics: p95 latency on `/v1/programs/search` (target < 400 ms). CPU (< 60%). Memory (< 400 MB of 512).
- UptimeRobot: uptime still 100% since T-0.
- 401 rate: expected during HN rush (people hitting paid endpoints unauth'd). If > 30% of total → likely docs confusion, not abuse.
- 500 rate: target **0**. Any single 5xx → read Sentry, decide.
- Newsletter signups (`/v1/subscribers`): record count. Expect 5-50 in first hour.

```bash
flyctl logs --app autonomath-api | grep -E 'status=5|status=401' | tail -50
```

### T+6h (15:00) — Support triage

Open support inbox (`support@<DOMAIN_PLACEHOLDER>`). Triage rules below. Update the HN thread with one top-level comment if there are meaningful questions — do not reply to every comment.

Tag each Sentry issue with `launch-day` so next week's retro can filter.

### T+24h (D+1, 09:00) — Retro

Write a 10-line retro into `docs/launch_retro_2026_05_06.md`. Numbers: signups, paid conversions (Stripe), total requests, 5xx count, worst Sentry issue, worst support email. One line: what I'd do differently.

---

## Roll-back

Staging smoke flagged an issue post-deploy, or prod 5xx rate > 2% for > 5 min:

```bash
# List recent releases — find the last-known-good version id
flyctl releases --app autonomath-api

# Roll back to that id
flyctl releases rollback <id> --app autonomath-api

# Confirm
flyctl status --app autonomath-api
BASE_URL=https://api.jpcite.com ./scripts/smoke_test.sh
```

If rollback itself fails, see `docs/incident_runbook.md` §(f) — DNS flip to Cloudflare Pages static mirror.

---

## Support inbox triage

Single inbox: `support@<DOMAIN_PLACEHOLDER>`. Check at T+1h, T+3h, T+6h, T+12h, then daily.

**Priority rules:**

- **P0 (respond < 1h):** paid user reports 500 / data wrong / cannot authenticate. Billing disputes.
- **P1 (< 12h):** free-tier auth issue, onboarding blocker, broken doc link.
- **P2 (< 72h):** feature requests, nice-to-have fixes, general questions.
- **Ignore:** "can you integrate with X" without use case, marketing pitches, spam.

For P0 with no clear fix: acknowledge in < 15 min, investigate, reply with ETA. Never leave a paid user without a human reply on day 1.

### Auto-responder template

Configure in Fastmail / ImprovMX on `support@<DOMAIN_PLACEHOLDER>`. Send once per sender per 24h.

```
件名 / Subject: Re: [auto] jpintel-mcp サポート受領 / support received

お問い合わせありがとうございます。24時間以内に返信します。緊急の場合は https://<DOMAIN_PLACEHOLDER>/status をご確認ください。
Thanks for reaching out. I'll reply within 24h. For outages see https://<DOMAIN_PLACEHOLDER>/status.
```

---

## D-4 CDN fallback plan (static mirror)

Built at T-4 days, verified once, left cold:

- `site/` mirrored to Cloudflare Pages project `jpintel-mirror` (free tier).
- Current DNS: `<DOMAIN_PLACEHOLDER> A -> fly-ip` (TTL 300).
- Fallback DNS: `<DOMAIN_PLACEHOLDER> CNAME -> jpintel-mirror.pages.dev` (change via Cloudflare UI).
- The mirror serves `index.html` + `pricing.html` + a static `/status` page. API routes return HTTP 503 with a JSON body pointing at the incident page.

Full flip procedure: `docs/incident_runbook.md` §(f).

---

## Status cadence

- T+0 through T+6h: passive monitoring, reply to support.
- Any P0 incident: open a status note in pinned HN comment + X thread update.
- D+1 retro: post numbers publicly if anything interesting.
