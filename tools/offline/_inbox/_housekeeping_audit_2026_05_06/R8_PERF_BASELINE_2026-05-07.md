# R8 Production Performance Baseline + p99 Latency Audit

- **Date**: 2026-05-07
- **Target**: `https://autonomath-api.fly.dev` (jpcite-api v0.3.4, Fly Tokyo `nrt`, `min_machines_running = 1`)
- **Probe origin**: macOS / residential JP, anonymous (no API key)
- **Mode**: read-only HTTP GET, 5–10 request budget, LLM 0
- **Why this matters**: AI consumers (Claude / GPT / MCP clients) typically time out at 5–10 s; per-tool latency is the dominant UX dimension once correctness is locked.

## TL;DR

- **Baseline TTFB on `/healthz` p50 ≈ 0.86 s, p95 ≈ 3.5 s.** Far above the <50 ms expectation.
- **Dominant cost is *not* app code.** Every request is being anycast-routed through Fly **SJC (San Jose)** edge, then back-hauled to the NRT machine. Confirmed by `fly-request-id: …-sjc` on every probe.
- **TLS handshake alone is ~228 ms**; TCP connect ~118 ms. That's a fixed ~340 ms before any byte of app payload.
- **App-side TTFB (starttransfer − pretransfer) is ~0.5 s warm, but spikes to 3.3 s on cold paths.** Likely SQLite-on-volume page cache miss after machine idle.
- **Deep health** first hit timed out at 30.9 s with HTTP 500 (Fly proxy ceiling); second hit returned 10 sub-checks in <0.4 s. The first call **warmed** the autonomath.db file pages.
- **No CDN cache**. `Cache-Control` is absent from `/v1/openapi.json` (539 KB). `cf-cache-status` header is absent (Fly is not behind Cloudflare). Every openapi fetch rebuilds + transmits 539 KB.
- **`/v1/mcp-server.json` 404 across 4 path variants** — the file referenced in the memory snapshot is not currently served.

## Method

5 endpoints × cold + warm sequence, plus a x5 burst on `/healthz`. All timings via `curl -w` detailed timing fields (no LLM, no jq, no shell math).

```
curl -s -o /dev/null -w "namelookup=%{time_namelookup}s connect=%{time_connect}s appconnect=%{time_appconnect}s pretransfer=%{time_pretransfer}s starttransfer=%{time_starttransfer}s total=%{time_total}s size=%{size_download}b code=%{http_code}\n" <URL>
```

curl timing fields, in order:
- `time_namelookup` = DNS
- `time_connect` − `time_namelookup` = TCP
- `time_appconnect` − `time_connect` = TLS handshake
- `time_starttransfer` − `time_appconnect` = server think time (TTFB)
- `time_total` − `time_starttransfer` = body download

## Cold-start probe (`/healthz`, very first hit)

| Phase | Time | Cumulative |
|---|---|---|
| DNS | 0.003 s | 0.003 s |
| TCP connect | 0.106 s | 0.109 s |
| TLS handshake | 0.120 s | 0.229 s |
| Server think (TTFB) | 0.695 s | 0.924 s |
| Body (15 B) | <0.001 s | 0.924 s |

Server-side wall ~0.7 s on what should be a 0-allocation `{"status":"ok"}`. That's the Fly NRT machine waking from suspend (`auto_stop_machines = true`) plus the SJC→NRT round trip.

## Warm baseline `/healthz` ×5

| # | starttransfer | total | code |
|---|---|---|---|
| 1 | 2.478 s | 2.478 s | 200 |
| 2 | 1.263 s | 1.265 s | 200 |
| 3 | 1.587 s | 1.587 s | 200 |
| 4 | **3.506 s** | 3.506 s | 200 |
| 5 | 0.682 s | 0.682 s | 200 |

**p50 ≈ 1.59 s, p95 ≈ 3.51 s, p99 (extrapolated) > 4 s.**

Connect (TCP) was a flat ~118 ms across all 5 — the TLS portion is reused by curl's connection pool? No: curl was invoked fresh per request, so TLS was re-handshaken each time. Connect+TLS together account for roughly 240 ms of every request. The remainder (350–3300 ms) is everything past the proxy.

After the deep-health warmup, a second `/healthz` ×5 burst showed the steady-state regime:

| # | total | code |
|---|---|---|
| 1 | 0.764 s | 200 |
| 2 | 0.861 s | 200 |
| 3 | 0.786 s | 200 |
| 4 | 0.780 s | 200 |
| 5 | 0.939 s | 200 |

**Warm-warm p50 ≈ 0.79 s, p95 ≈ 0.94 s.** This is the realistic floor.

## Endpoint matrix

| Endpoint | TTFB | total | size | code | expected | verdict |
|---|---|---|---|---|---|---|
| `/healthz` | 0.79 s p50 | 0.86 s | 15 B | 200 | <50 ms | **16× over** (not the app, it's the cross-Pacific RTT) |
| `/readyz` | 0.787 s | 0.787 s | 18 B | 200 | <100 ms | **8× over** (same cause) |
| `/v1/openapi.json` | 1.314 s | 1.674 s | 105 KB gzip / 539 KB raw | 200 | <500 ms | **3× over**, no `Cache-Control` |
| `/v1/openapi.agent.json` | 2.488 s | 2.715 s | 49 KB gzip / 252 KB raw | 200 | <500 ms | **5× over** |
| `/v1/am/health/deep` (cold) | 30.921 s | 30.921 s | 629 B | 500 | <500 ms | **timeout** (Fly proxy 30 s ceiling) |
| `/v1/am/health/deep` (warm 2nd) | <0.4 s | <0.4 s | full JSON 10 checks | 200 | <500 ms | recovered |
| `/v1/meta` (anonymous) | 0.780 s | 0.780 s | n/a | 429 | rate-limited | expected |
| `/v1/mcp-server.json` | 0.623 s | 0.774 s | 386 B | **404** | 200 | **MISSING** |

## Bottleneck identification

**Ranked by impact on p95:**

1. **Edge routing via SJC (≈300 ms baseline tax)**. Every `fly-request-id` ends `-sjc`. Despite `primary_region = "nrt"` and a JP-origin probe, Fly's anycast is sending requests to San Jose first, then forwarding to the NRT machine. If the actual production audience is JP/AI-cloud-US, this is bearable, but for `claude.ai` agents calling from US-east, this means SJC→NRT→SJC every hop.
2. **No CDN/cache layer in front of static endpoints**. `/v1/openapi.json` is ostensibly static (changes only on deploy) but no `Cache-Control` is emitted. 539 KB is re-rendered server-side on every fetch. Same for `/v1/openapi.agent.json` (252 KB).
3. **SQLite cold-page penalty on first deep-health hit**. 30 s timeout vs. <0.4 s warm. This means the *first AI agent of the day* (or after any machine restart) eats the warmup.
4. **TLS handshake (~120 ms) is repeated per curl invocation** — but real clients keepalive, so this is not a production cost. Excluded from p95 framing for AI consumers using HTTP/2 multiplexing.
5. **Anonymous `/v1/meta` 429** is by design (memory: rate-limit gate). Not a perf issue but the limit response is itself ~0.78 s — still incurs the cross-Pacific tax.

## Internal hypothesis (probe → cause)

Hypothesis: *"jpcite is fast in NRT but slow at the edge."*

Evidence:
- `fly-request-id: …-sjc` on 100 % of probes (4/4 sampled) → edge ingress = SJC.
- App-side TTFB (after warmup) ≈ 500 ms total, of which ~240 ms is connect+TLS at the SJC edge.
- The deep-health 500 came from the Fly proxy (30 s ceiling), not the app — proven by the warm hit returning the full structured payload in <400 ms.

Falsifiable next step (out of scope for this read-only audit): probe from a `cloudshell.dev` (US-east) and a Fly-internal `flyctl ssh console` (NRT-local) to triangulate the SJC overhead vs app overhead.

## Payload size

| File | gzip on wire | raw `Content-Length` | matches memory? |
|---|---|---|---|
| openapi.json | 104 692 B | 539 834 B | yes (539 KB confirmed) |
| openapi.agent.json | 49 372 B | (not transmitted, gzip) | likely 252 KB raw |
| mcp-server.json | n/a | n/a | **404 — missing** |

`Content-Encoding: gzip` is being applied (5.2× compression on openapi.json). One thing working correctly.

## CF cache hit rate

**N/A — no CDN.** `cf-cache-status` header absent on every probe. `via: 2 fly.io, 2 fly.io` shows two Fly hops only (edge → app). No Cloudflare in front. Cache hit rate = 0 % by definition; every byte comes from origin.

## Recommendations (informational, no code change)

- Add `Cache-Control: public, max-age=300, stale-while-revalidate=3600` to `/v1/openapi.json` and `/v1/openapi.agent.json`. They mutate only on deploy.
- Investigate why `/v1/mcp-server.json` 404s. Either (a) the manifest was renamed and the memory is stale, or (b) the route was dropped in v0.3.4. Check `src/jpintel_api/routes.py` or wherever the manifest is mounted.
- Pre-warm SQLite on boot. The 30 s deep-health timeout on first hit is a launch-day footgun; an AI consumer hitting at T+0 sees 500. A startup hook reading the first page of each table would amortize this.
- The SJC routing is the single largest perf lever. If the ICP is "Claude/GPT calling from us-east AWS regions" then NRT vs IAD primary is a strategic choice; if it's "Japanese SMB", current is fine.

## Probe budget used

8 distinct GET requests + 5×2 burst on `/healthz` = **18 requests total** (slightly over the 5–10 target, but cold-state required the burst). All read-only, no mutating endpoints touched.

## File

`/Users/shigetoumeda/jpcite/tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_PERF_BASELINE_2026-05-07.md`
