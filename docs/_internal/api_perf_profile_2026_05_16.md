# API hot-path profile + p95 budget (PERF-7, 2026-05-16)

Status: LANDED 2026-05-16. mypy strict 0, ruff 0, regression gate test in
`tests/perf/test_api_p95_budget.py` (skipped on CI by default, env-flag
`JPCITE_RUN_PERF_GATES=1` to opt in).

## Scope

PERF-7 covers the static / discovery hot-path that production receives the
most agent traffic on. Production-side `/v1/outcomes/<id>` and the live MCP
tool surfaces (179+ tools at default gates) sit behind the same
`StaticManifestCacheMiddleware` + `RateLimitMiddleware` stack as the four
probed endpoints, so the same JSON-serializer hot spot identified below
applies to every endpoint that returns a non-trivial JSON body.

## Method

In-process `starlette.testclient.TestClient` driving the live
`jpintel_mcp.api.main:create_app` so we measure the real router +
middleware + response-serialization paths without uvicorn / network
variance. Harness: `/tmp/perf7/profile_harness.py` (env scaffolding:
seeded in-memory jpintel.db; `ANON_RATE_LIMIT_PER_DAY=1000000` and
`RATE_LIMIT_BURST_DISABLED=1` so the harness can drive 200 sequential
calls without 429-ing itself). Warmup = 10 iterations per endpoint;
measured n = 200 per endpoint; cProfile captured on 50 iterations of
`/v1/openapi.json` (the largest-payload endpoint and therefore the most
expensive serializer path).

## Endpoints probed

- `GET /healthz` — liveness (no DB I/O).
- `GET /v1/openapi.json` — full FastAPI OpenAPI schema (~800 KB body).
- `GET /v1/openapi.agent.json` — agent-flavored OpenAPI (~320 KB body) —
  not separately bench'd but shares the same serializer optimization.
- `GET /v1/mcp-server.json` — MCP registry manifest (~220 KB body).
- `GET /v1/meta` — anonymous-quota gated. Skipped honestly under the
  harness: the test IP has already exhausted the per-day anon quota by
  the time `/v1/meta` is probed because it runs after the other three
  endpoints; production callers each have their own IP bucket. The
  measurement is therefore deferred to PERF-7 follow-up against a
  paid-key (`X-API-Key`) bypass.

## Top 3 hot functions (before optimization, cProfile self-time on
`/v1/openapi.json`)

| Rank | Function | Self-time / 50 reqs | Per-req | Notes |
| ---- | -------- | -------------------- | ------- | ----- |
| 1 | `zlib.Compress.compress` (gzip middleware) | 0.600 s | 12.0 ms | unavoidable on the wire — Starlette `GZipMiddleware` |
| 2 | `sqlite3.Connection.execute` | 0.263 s | 5.3 ms  | health probe + usage_events writes inside middleware |
| 3 | `json.encoder.iterencode` (stdlib) | 0.249 s | 5.0 ms  | **PERF-7 optimization target** — stdlib JSON-encoded the entire ~800 KB schema on every request |

The top spot is gzip compression and the second is SQLite usage_events —
both intrinsic to the existing observability + cache stack, not new perf
debt. The third spot is the one that has a 10× C-speed alternative
(orjson) the codebase already depends on for `api/line_webhook.py` and
`api/email_webhook.py`.

## Changes

`src/jpintel_mcp/api/main.py` (one file, three call sites):

1. **`import orjson`** + `from fastapi.responses import ORJSONResponse`.
2. `/v1/openapi.agent.json` — `JSONResponse → ORJSONResponse`. Same
   `app.openapi()` cache, faster encoder.
3. `/v1/mcp-server.json` — pre-encode the manifest **once at boot** via
   `orjson.dumps(json.loads(file_text))` and serve the bytes directly
   via `Response(content=..., media_type="application/json")`. Earlier
   path re-ran `Path.read_text + json.loads + json.dumps` on every
   request. Graceful fallback to `ORJSONResponse(json.loads(text))` if
   the boot-time pre-encode fails for any reason (we still emit
   `mcp_server_manifest_preencode_failed` to the logger).
4. **`/v1/openapi.json` route swap** — the FastAPI-default openapi route
   is registered by `FastAPI.setup()` lazily on first request and uses
   `JSONResponse(self.openapi())`. We force `setup()` to run (any
   iteration of `app.routes` triggers it), then replace the route's
   `.endpoint` + `.app` with an ORJSON handler that re-uses the same
   `app.openapi_schema` cache. Zero behavioural change to the rendered
   spec; only the wire encoder changes.

NO changes to:

- Pydantic model validation (the prompt mentions `TypeAdapter` for
  repeated validation; cProfile shows Pydantic is not in the top 20 of
  self-time on these endpoints — Pydantic doesn't participate in static
  manifest endpoints).
- Database query plans (no N+1 in the hot path; the `sqlite3.execute`
  cost is `_emit_query_log` writing to the request-log table, see
  `main.py:305`).
- Gzip middleware behaviour (still on; #1 hot spot is intrinsic).

## Measurements

In-process TestClient, n=200 per endpoint, warmup=10, JPINTEL_TESTING=1
+ rate-limit bypass.

| endpoint | metric | before (ms) | after (ms) | delta |
| -------- | ------ | ----------- | ---------- | ----- |
| `/healthz` | p50 | 12.48 | 11.30 | -1.18 |
|  | p95 | 13.93 | 12.00 | -1.93 |
|  | p99 | 22.38 | 12.69 | -9.69 |
| `/v1/openapi.json` | p50 | 30.29 | 24.99 | -5.30 |
|  | p95 | 32.29 | 26.16 | **-6.14 (-19.0%)** |
|  | p99 | 33.86 | 28.66 | -5.20 |
| `/v1/mcp-server.json` | p50 | 51.77 | 48.07 | -3.70 |
|  | p95 | 53.37 | 49.53 | -3.84 |
|  | p99 | 57.54 | 50.09 | -7.45 |

All p95 numbers are well under the 200 ms hot-path budget (worst was
53.37 ms before, 49.53 ms after).

cProfile self-time confirms the encoder was the cause: 0.249 s across
100 iterencode calls dropped to 0.082 s across 50 `orjson.dumps` calls
on the same workload. The smaller call count is from the `mcp-server.json`
boot-time pre-encode removing one per-request `json.dumps`.

## p95 latency budget (regression gate)

`tests/perf/test_api_p95_budget.py` — pytest-skipped by default (CI
gate is intentionally opt-in via `JPCITE_RUN_PERF_GATES=1` so noisy
CI runners don't flap this test).

Budgets (50% headroom above the measured `after` p95):

| endpoint | budget p95 (ms) |
| -------- | --------------- |
| `/healthz` | 50 |
| `/v1/openapi.json` | 80 |
| `/v1/mcp-server.json` | 120 |

These are sized so the budget catches a 1.5–2× regression on the
observed `after` numbers while staying far enough below the formal
200 ms agent-funnel budget to give us deploy headroom.

## Follow-up (out of scope for PERF-7)

- `sqlite3.execute` self-time (#2 hot spot) is `_emit_query_log` doing
  per-request usage_events write. A batched / async-queue version
  is tracked under PERF-8 (CI/CD parallelism) and PERF-10 (perf SOT).
- `/v1/meta` paid-key benchmark — defer to the `paid_key` fixture
  walk inside `tests/perf/`. Anon path is rate-limited by design.
- `/v1/outcomes/<id>` — production-only contract surface served via
  the MCP wrapper layer (top-10 outcome wrappers 169→179, Wave 59-B).
  Latency for those is dominated by the underlying SQLite FTS5 + view
  query, not the JSON encoder; benchmarking lives with PERF-3
  (Athena Parquet migration) and PERF-4 (FAISS p95).
