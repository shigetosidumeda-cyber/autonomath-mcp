# Chaos engineering runbook (Wave 18 E3)

The jpcite API is exercised weekly by a Toxiproxy-driven fault-injection
suite (`tests/chaos/`) that validates resilience to latency, connection
resets, TCP timeouts, and bandwidth caps. This runbook covers the
failure modes the suite exercises, the expected recovery behavior, and
the on-call response when the weekly score drops below target.

Cron: `.github/workflows/chaos-weekly.yml` — Sat 04:00 UTC (Sat 13:00
JST). Target resilience score: **≥ 4.5 / 5**.

## Failure modes exercised

| Scenario | Toxic | Expected behavior |
| --- | --- | --- |
| 500 ms upstream latency | `latency=500` | `/healthz` succeeds in ≤ 8 s; `x-request-id` round-trips intact |
| 1 s upstream latency | `latency=1000` | `/healthz` succeeds in ≤ 12 s |
| 3 s upstream latency | `latency=3000` | `/healthz` succeeds in ≤ 30 s |
| 1 KB/s bandwidth cap | `bandwidth=1` | JSON body fully delivered; no truncation |
| TCP RST mid-flight | `reset_peer=100` | Client raises `httpx.HTTPError` within 5 s — no hang |
| Held connection 5 s | `timeout=5000` | Client-side 1 s read-timeout fires within ~2 s |
| 32-byte data cap | `limit_data=32` | Client surfaces error OR receives truncated body |
| Toxic removal | (clear all) | Baseline returns; `/healthz` < 2 s |

## Recovery patterns

### Pattern A — latency injection

The API uses uvicorn's default keep-alive + workers; slow upstream
adds wall-clock cost but does NOT exhaust the worker pool unless the
toxic exceeds the worker count × per-request budget. Recovery is
automatic on toxic removal.

**On-call action**: none. If the latency scenario fails, root-cause is
either (a) the API process has hung, (b) Toxiproxy never wired the
toxic, or (c) the upstream port (`CHAOS_UPSTREAM=127.0.0.1:8080`) is
not where the test API is listening. Re-check the workflow logs for
"Start API under test" passing the curl probe.

### Pattern B — connection reset

`httpx` surfaces a `RemoteProtocolError` / `ConnectError` / `ReadError`
on RST. Application code that catches `httpx.HTTPError` (the parent
class) handles all three; code that catches only `httpx.HTTPStatusError`
is wrong and will let RSTs escape as 500s.

**On-call action**: if `test_reset_peer_raises_connection_error` fails,
audit the call site for narrow exception types. The chaos suite is
the canary for too-narrow exception handlers.

### Pattern C — bandwidth cap

A 1 KB/s pipe should not crash the client. If `test_bandwidth_cap`
fails, the JSON body is being parsed incrementally and the parser is
unhappy with the stalled stream — check `httpx` version and any
custom `content-encoding` middleware.

### Pattern D — request-id propagation

`_RequestContextMiddleware` echoes the client-supplied `x-request-id`
back on the response. If `test_request_id_propagation_under_latency`
fails under load, the middleware order has been disturbed (the context
middleware must run inside `SecurityHeadersMiddleware` so the response
headers are set before the security middleware seals them).

### Pattern E — bandwidth + RST + recovery interplay

Toxiproxy clears all toxics on session teardown via
`toxiproxy_client.reset()`. If a test leaves a toxic behind (because
the proxy fixture crashed mid-teardown), subsequent tests will see
spurious latency. The `test_recovery_after_toxic_clear` guard catches
this — its failure means the proxy teardown is leaking state.

## Triage when the weekly score drops

1. Pull `chaos-results.xml` from the workflow run's artifacts.
2. Identify which scenario(s) failed — each test is a separate
   `<testcase>` element.
3. Match against the failure-mode table above; pick the corresponding
   pattern.
4. Reproduce locally:
   ```bash
   docker run -d --name toxiproxy -p 8474:8474 -p 18001:18001 \
       ghcr.io/shopify/toxiproxy:2.9.0
   .venv/bin/uvicorn jpintel_mcp.api.main:app --port 8080 &
   pytest tests/chaos/ -v -k <scenario>
   ```
5. Fix or file an issue. Aim to restore the weekly score to 5/5 before
   the next Saturday run.

## Skipping the suite

The suite is **opt-in**. Running `pytest` on a developer machine without
Toxiproxy hits the `_toxiproxy_available` check in `conftest.py` and
returns "skipped" for every test in the package. This is by design —
mandating Toxiproxy for every local pytest run would slow the inner
dev loop without buying real coverage (the production cron catches
regressions before they ship).

Force-skip in CI by removing the cron + workflow_dispatch trigger from
`.github/workflows/chaos-weekly.yml` — but do this only with a
recorded sign-off, since the suite is the production gate for
upstream-fault resilience.
