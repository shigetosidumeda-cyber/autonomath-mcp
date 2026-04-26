# loadtest/

k6 scripts that exercise `/v1/programs/search`, `/v1/programs/{id}`, and
`/v1/billing/webhook` under discovery-spike conditions. Launch target is
Fly.io nrt, one `shared-cpu-1x` machine, SQLite on a 1GB volume.

Capacity model is in [`docs/capacity_plan.md`](../docs/capacity_plan.md).

## Scripts

| File | What it tests | Executor | Duration |
|---|---|---|---|
| `programs_search.js` | 70/20/10 FTS / filter / get mix, 80% anon + 20% paid | ramping-vus 0→50→0 | 8 min |
| `webhook_stripe.js`  | Stripe invoice.paid retry storm (idempotency) | constant-arrival-rate 20 rps | 3 min |

Both scripts emit a `summary_*.json` next to themselves via `handleSummary`.
`.github/workflows/loadtest.yml` uploads those as build artifacts.

## Installing k6

k6 is NOT listed in `pyproject.toml` on purpose — it is a standalone Go
binary, not a Python dep. The CI workflow grabs it from
`grafana/setup-k6-action`. For local runs:

```bash
brew install k6           # macOS
# or
curl https://github.com/grafana/k6/releases/download/v0.51.0/k6-v0.51.0-linux-amd64.tar.gz | tar xz
```

Verify: `k6 version` should print `k6 v0.51+`.

## Running locally

```bash
# 1. Start the API locally
.venv/bin/uvicorn jpintel_mcp.api.main:app --reload --port 8080

# 2. In another terminal, hit it. Anon-only is fine for the programs script
#    because localhost has no real rate limit unless you set ANON_RATE_LIMIT_ENABLED=1.
BASE_URL=http://localhost:8080 k6 run loadtest/programs_search.js

# 3. Webhook script needs a signing secret. Use any string locally — start
#    uvicorn with the same value in STRIPE_WEBHOOK_SECRET.
STRIPE_WEBHOOK_SECRET=whsec_local_test \
  .venv/bin/uvicorn jpintel_mcp.api.main:app --port 8080

BASE_URL=http://localhost:8080 \
STRIPE_WEBHOOK_TEST_SECRET=whsec_local_test \
k6 run loadtest/webhook_stripe.js
```

## Running against staging

Point at the staging host. The paid-tier key must be a **test** key issued
against the staging Stripe account — never reuse prod keys here.

```bash
BASE_URL=https://jpintel-mcp-staging.fly.dev \
TEST_PAID_KEY=jpintel_staging_testkey_xxxx \
k6 run loadtest/programs_search.js
```

### Anon-rate-limit interaction (IMPORTANT)

`src/jpintel_mcp/api/anon_limit.py` gives each /32 (IPv4) or /64 (IPv6) a
daily quota — default **100 calls / JST-day**. A single k6 runner shares
one source IP, so a 7-minute 50-VU run WILL exhaust the anon bucket
within ~30 seconds and the remaining runs get 429.

Two options:

1. **Raise the limit on staging** — set `ANON_RATE_LIMIT_PER_MONTH=50000000`
   on the staging Fly app before the run, reset after:
   ```bash
   fly secrets set -a jpintel-mcp-staging ANON_RATE_LIMIT_PER_MONTH=50000000
   # …run test…
   fly secrets unset -a jpintel-mcp-staging ANON_RATE_LIMIT_PER_MONTH
   ```
2. **Route 100% through paid key** — pass `ANON_SKIP=1` to the script:
   ```bash
   ANON_SKIP=1 TEST_PAID_KEY=am_xxx k6 run loadtest/programs_search.js
   ```
   This bypasses anon bucketing and the paid tier has no hard cap (¥3/req
   tax-exclusive / ¥3.30 tax-inclusive, metered). WARNING: in staging this
   will report ~42,000 usage_records to
   test Stripe; purge the test customer after the run so the invoice is
   zeroed. In prod, never run this script.

For the real launch-readiness pass, option 1 is right: we want to measure
the backend, not the rate-limiter.

## Interpreting results

k6 prints a summary block to stdout. The critical lines:

```
http_req_duration..............: avg=xxx p(95)=yyy p(99)=zzz
http_req_failed................: rate=x.xx%
checks.........................: rate=xx.xx%
errors_5xx.....................: rate=x.xx%
✓ search_fts: status 200 or 429
```

A green run means **every threshold in `options.thresholds` held**. k6
exits non-zero if any threshold breached — CI fails the job in that case.

Common breach interpretations:

| Breach | Likely cause | Next step |
|---|---|---|
| `p(95)>300ms` on search | SQLite lock contention; uvicorn single worker | Scale to shared-cpu-2x, or run `--workers 2` |
| `p(95)>500ms` on webhook | Stripe retrieve() round-trip or DB write queue | Check Sentry for slow `stripe.Subscription.retrieve` |
| 429 rate > 0 on anon | anon_rate_limit triggered | See "Anon-rate-limit interaction" above |
| 5xx rate > 0 | sqlite busy-timeout exceeded OR unhandled exception | Tail Fly logs: `fly logs -a jpintel-mcp-staging` |
| checks rate < 99% | Body shape assertion failed | Diff a live response vs `docs/openapi/v1.json` |

The baseline in `research/perf_baseline.md` recorded **37 rps** from a
single uvicorn worker on laptop hardware. Fly's shared-cpu-1x is
comparable-to-slightly-slower. Expect ~30-40 rps ceiling on one machine
until we scale.

## Cost: VU count → ¥/min on Fly

Fly shared-cpu-1x costs ~$0.0000022 / second (US$0.0000022/s = ¥0.00033/s
at ¥150/$). One machine running 24/7 ≈ ¥855/month. The machine is NOT
load-proportional — it costs the same idle or saturated.

The variable cost during a load test is **egress bandwidth**. Fly gives
100 GB/month free, then $0.02/GB (≈¥3/GB).

Estimated payload sizes (measured against local bench 2026-04-22):
- `search?q=...&limit=20` `fields=default` → ~8 KB/response
- `search?q=...&limit=20` `fields=full` → ~60 KB/response (full enriched)
- `get_program/{id}` → ~12 KB/response

| VUs (scenario) | req/min (approx) | bytes/min @ 8KB avg | ¥/min (bandwidth only) | Notes |
|---:|---:|---:|---:|---|
|  10 |   600 |   4.8 MB |  0.014 | well under free tier |
|  50 | 3,000 |  24.0 MB |  0.072 | this script at hold phase |
| 100 | 6,000 |  48.0 MB |  0.144 | approx HN frontpage for 1 min |
| 500 |30,000 | 240.0 MB |  0.720 | approx Product Hunt #1 5-min surge |
|1000 |60,000 | 480.0 MB |  1.440 | sustained burst (would 429 everywhere) |

Machine time during an 8-minute test: **¥0.044**. Even a runaway load
test that streams 1GB total egress costs ~¥3. The Fly cost of k6 is
effectively noise — don't optimise for it.

### When ¥/min does matter

Two scenarios make bandwidth cost meaningful:

1. **`fields=full` responses under sustained 100+ req/s**: 60KB × 6000
   req/min = 360 MB/min, which at 1440 min/day = ~500 GB/day. That's
   ¥45k/month in bandwidth alone. Since we don't gate `fields=full`
   behind a tier (pure metered), a per-response size cap or response
   compression is the right control.
2. **Unbounded pagination** (`limit` uncapped): the code today caps at
   `limit ≤ 100` (see `programs.py:210` `Query(ge=1, le=100)`), so this
   is already mitigated. Watch the export endpoint if/when we add one.

## Artifacts

Both scripts write `summary_*.json` files into this directory. Those are
git-ignored — don't commit them. The CI workflow uploads them as build
artifacts with 30-day retention.

## What these scripts do NOT test

- **WAL checkpoint behavior under write load**. We have zero concurrent
  writes; all test traffic is read-heavy. When we add a write-hot path
  (e.g. ingest via API), write a third script.
- **Disk I/O saturation on the 1GB volume**. Current DB is ~180MB; we
  are nowhere near disk pressure.
- **Cold start / autostart**. `min_machines_running = 1` in fly.toml
  means we never cold-start. If that changes, add an autostart probe.
- **Email send latency**. The welcome email path runs best-effort inside
  the webhook handler (`_send_welcome_safe`); Postmark being slow slows
  the webhook response. Test with POSTMARK_API_TOKEN unset (→ no-op
  path) unless you specifically want to measure that.

## Safety rails

- Never point these scripts at a production URL without first taking the
  app offline from search (robots.txt + noindex) AND warning users via
  status page. 50 VU on a shared-cpu-1x will degrade the experience for
  concurrent real users.
- The webhook script writes `api_keys` rows on staging. Clean up after:
  ```bash
  fly ssh console -a jpintel-mcp-staging -C \
    "sqlite3 /data/jpintel.db \"DELETE FROM api_keys WHERE customer_id='cus_loadtest';\""
  ```
- `TEST_PAID_KEY` must be revocable. Issue → test → revoke via
  `/v1/billing/keys/revoke` (admin) or DB update.
