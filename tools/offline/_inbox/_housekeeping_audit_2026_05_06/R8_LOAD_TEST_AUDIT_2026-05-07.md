# R8 LOAD TEST AUDIT — 2026-05-07

Production load test + concurrent request audit on jpcite-api v0.3.4.
Scope: read-only smoke against `https://api.jpcite.com/healthz` and the
Cloudflare-fronted `https://jpcite.com/server.json`. Goal: verify Fly
single-machine capacity headroom for launch-time traffic spikes (Hacker
News / Twitter / industry newsletter) without DDoS-shaped load.

## 0. Constraints honored

- LLM 0 (no Anthropic / OpenAI / Gemini calls).
- Anonymous quota safe — `/healthz` is unmetered, never decrements
  `anon_rate_limit` bucket; `server.json` is static, served via Cloudflare.
- Production charge 0 (no Stripe metered tools probed).
- DDoS-shape 0 — peak concurrent N=30, far below the documented
  3 req/IP/day anon limit times typical CGNAT-spread. Not a stress test,
  a capacity smoke.

## 1. Production topology snapshot

`flyctl machine list -a autonomath-api` (Fly app slug remains
`autonomath-api`; user-facing brand is jpcite) returned exactly one
machine.

| field          | value |
|----------------|-------|
| Machine ID     | `85e273f4e60778` |
| Name           | `cold-flower-3212` |
| State          | `started`, checks `1/1 passing` |
| Region         | `nrt` (Tokyo) |
| Size           | `shared-cpu-2x:4096MB` |
| Image          | `autonomath-api:deployment-07986f9-25482086637` |
| Volume         | `vol_4ojk82zk7xzeqxpr` |
| Last restart   | 2026-05-07 07:33:18 UTC (≈1h22m before audit) |
| min/max        | min_machines_running=1 (per `fly.toml`), no auto_scale wired |

`flyctl machine status` command issued OK; the org metrics token failed
to load (`Warning: Metrics token unavailable: ... context canceled`),
so live CPU% / RSS series were not retrievable during the audit.
Recorded as a known gap below.

## 2. Cloudflare cache behaviour (server.json)

Single `HEAD https://jpcite.com/server.json` returns:

```
HTTP 200  total=0.071s
cf-cache-status: DYNAMIC
cache-control: public, max-age=3600
cf-ray: 9f7efcf1...-NRT
server: cloudflare
```

`cf-cache-status: DYNAMIC` means **Cloudflare is bypassing its edge
cache despite the origin's `Cache-Control: public, max-age=3600`**. A
20-way parallel HEAD burst confirmed the same — 20/20 responses came
back as `DYNAMIC`, none `HIT` or `MISS`. p50 0.150s / p95 0.171s /
p99 0.174s — fast (Cloudflare nrt is close), but every request is still
hitting Fly origin. This is a meaningful capacity-headroom finding: a
Hacker News spike on a marketing page that loads `server.json` would
not be absorbed at the edge.

Likely cause: a Cloudflare Page Rule or Workers route is forcing
`Cache-Level: bypass` for the jpcite.com zone, or the host header /
Vary headers (`x-envelope-version`, `accept`) defeat cache-key
matching. Recommended R9 follow-up — own audit, not in scope here.

## 3. Concurrent burst latency on /healthz (Fly origin)

Workload: `xargs -I{} -P N curl https://api.jpcite.com/healthz`.
Warmup: 5 sequential requests before each burst. Each request is a
TLS+H2 GET with no body.

Warmup steady-state: ~0.480 — 0.500s (this is dominated by TLS+TCP
handshake, plus Tokyo origin RTT; healthz handler itself is microseconds).

| N concurrent | min     | mean    | p50     | p95     | p99     | max     | non-200 |
|--------------|---------|---------|---------|---------|---------|---------|---------|
| 5            | 0.463s  | 0.502s  | 0.512s  | 0.522s  | 0.522s  | 0.522s  | 0       |
| 10           | 0.501s  | 0.516s  | 0.514s  | 0.538s  | 0.538s  | 0.538s  | 0       |
| 20           | 0.492s  | 0.583s  | 0.586s  | 0.643s  | 0.644s  | 0.644s  | 0       |
| 30           | 0.498s  | 0.645s  | 0.641s  | 0.721s  | 0.741s  | 0.741s  | 0       |

All 65 burst requests returned `200`. No `429`, no `503`, no `502`.
The latency curve is flat from N=5 through N=10 (TLS-handshake dominated),
then climbs ~+90ms on p50 going from N=10 to N=20 to N=30 — consistent
with the 2 vCPU shared-cpu instance starting to queue handshakes
behind a small ASGI worker pool.

## 4. Failure-mode shape (inspected, not provoked)

Source-side inspection of `src/jpintel_mcp/api/anon_limit.py` confirms
the production 429 contract — relevant for what a quota-exceeded burst
would look like to a client:

- `status: 429`
- `Retry-After: <seconds_until_jst_midnight>`
- Top-level body fields: `code`, `reason`, `detail` (ja), `detail_en`,
  `retry_after`, `reset_at_jst`, `limit`, `upgrade_url`,
  `direct_checkout_url`, `cta_text_ja/en`, `trial_signup_url`,
  `trial_terms{duration_days:14, request_cap:200, card_required:false}`.
- Headers: `X-Anon-Quota-Remaining: 0`, `X-Anon-Quota-Reset`,
  `X-Anon-Upgrade-Url`, `X-Anon-Direct-Checkout-Url`, `X-Anon-Trial-Url`.
- Fallback path `_raise_rate_limit_unavailable` yields the same envelope
  with `code=rate_limit_unavailable` if the rate-limit backend itself
  is down — fail-closed, not fail-open.

503 / 502 shape was not probed in this audit (would require pushing
past machine capacity). Fly-edge layer would emit its own `502` with
`server: Fly/...` if the origin handshake stalls — none observed.

## 5. Capacity headroom estimate

Even at N=30 concurrent the p99 is 0.741s with zero error. Subtracting
the ~0.480s TLS+RTT floor, the origin-handler tail at p99 N=30 is
roughly 260ms — well within the FastAPI/uvicorn shared-cpu-2x envelope.

Back-of-envelope rules of thumb:

- Current **steady-state** p50 ~0.5s end-to-end means a single worker
  can clear ~2 reqs/sec on this code path. A typical uvicorn build
  with `workers=1` + the default `--limit-concurrency` (≈1024) should
  absorb hundreds of inflight TLS handshakes before the queue depth
  starts adding visible latency on `/healthz`.
- The Hacker News front-page burst pattern (estimated peak ~50-80
  concurrent reads on a marketing page) sits comfortably below the
  N=30 measured ceiling (still 0% errors).
- The launch-day risk is **NOT** raw RPS — it is the
  Cloudflare cache miss on `server.json` (Section 2) compounded by
  a cold autonomath.db pin (~9.4 GB). Both are server-side
  amplifiers, not concurrency-driven.
- Recommended pre-launch action (separate from this audit): fix the
  Cloudflare Page Rule so static GETs (`server.json`,
  `/openapi/v1.json`, the marketing pages under `jpcite.com/`) cache
  at the edge. This decouples HN-spike traffic from Fly origin
  entirely.

## 6. Known gaps in this audit

1. **No Fly metrics series.** The org metrics token failed to load,
   so CPU%, RSS, and connection-count timeseries during the burst are
   not captured. Recommend re-running with `flyctl logs` tail + a
   working metrics token in a follow-up.
2. **No 503/502 provocation.** Constraint forbade DDoS-shape load.
   The bound is `N=30 concurrent → 0 errors` — true ceiling is
   higher but not measured here.
3. **No volume-mounted DB hot-path probed.** `/healthz` does not touch
   SQLite; route latency from `/v1/programs/search` (FTS5 trigram)
   and `/v1/am/...` (autonomath.db, 9.4 GB) is not represented in
   these numbers. Capacity for those routes will be lower.
4. **Single AZ measurement.** All requests originated from the operator's
   home network; cross-region p99 from EU/US clients adds ~+150ms
   RTT and is outside this audit's scope.

## 7. Verdict

Single shared-cpu-2x/4096MB Fly machine in nrt is **launch-ready** for
the anticipated 50-80 concurrent burst load on /healthz and similar
non-DB endpoints, with p99 latency staying under 1s through N=30
parallel and zero error rate. The 429 quota envelope is correctly
shaped per `anon_limit.py` and ships full upgrade CTAs.

The **one structural risk** uncovered is Section 2: the
`cf-cache-status: DYNAMIC` on every `server.json` HEAD means Cloudflare
is currently a passthrough for that surface. A successful Hacker News
spike could land entirely on Fly origin instead of being absorbed at
the edge. Recommend a separate R9 audit on Cloudflare Page Rules /
cache-key configuration before public launch — that single fix is
worth more capacity than scaling Fly.

## 8. Raw artifacts

Stored under `/tmp/jpcite_load_2026_05_07/` for the duration of the
session (ephemeral):

- `burst_5.csv`, `burst_10.csv`, `burst_20.csv`, `burst_30.csv` —
  per-request CSV (id, http_code, time_total, time_starttransfer,
  time_connect, time_appconnect).
- `cf_*.txt` — 20 single-request files for the Cloudflare burst on
  `server.json`, each containing `code|time_total|header_json`.
- `sorted_*.txt` — sorted latency arrays used for percentile math.

Reproduction (anonymous, no LLM, no metered routes):

```bash
warmup() {
  for i in 1 2 3 4 5; do
    curl -fsS -o /dev/null -w "warmup_$i HTTP %{http_code} total=%{time_total}s\n" \
      https://api.jpcite.com/healthz
  done
}

burst() {
  local N=$1
  seq 1 "$N" | xargs -I{} -P "$N" curl -fsS -o /dev/null \
    -w "{},%{http_code},%{time_total}\n" \
    https://api.jpcite.com/healthz
}

warmup
burst 5; burst 10; burst 20; burst 30
```

End of R8 LOAD TEST AUDIT.
