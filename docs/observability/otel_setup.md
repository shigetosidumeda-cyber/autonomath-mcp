# OpenTelemetry setup (Wave 18 E2)

The jpcite API emits distributed traces via the OpenTelemetry Protocol
(OTLP) over HTTP. Every REST endpoint is wrapped in a server span by
`FastAPIInstrumentor.instrument_app(app)`; spans carry `trace_id` +
`span_id` that propagate through middleware, router, and DB layer so
one trace lookup reveals the entire request graph.

This page covers backend wiring for the three common collectors:
**Grafana Tempo**, **DataDog**, and **Jaeger**. All three are reached
through the same `OTEL_EXPORTER_OTLP_ENDPOINT` env var — only the URL
and the auth header change.

## Env contract

| Env var | Required | Default | Purpose |
| --- | --- | --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | yes | (unset = OFF) | Collector URL (HTTP) |
| `OTEL_EXPORTER_OTLP_HEADERS` | per-backend | (none) | `key=value,...` auth headers |
| `OTEL_SAMPLE_RATE` | no | `0.01` prod / `1.0` dev | TraceIdRatioBased sampler |
| `OTEL_SERVICE_NAME` | no | `jpcite-api` | `service.name` resource attr |
| `OTEL_PYTHON_FASTAPI_EXCLUDED_URLS` | no | `healthz,readyz,metrics` | Probe-path skip list |

Tracing is **off by default**. Setting `OTEL_EXPORTER_OTLP_ENDPOINT`
flips the entire surface on; unsetting it returns to no-op without a
restart at the next process start.

## Backend 1: Grafana Tempo (self-hosted / Grafana Cloud)

Grafana Cloud accepts up to 50 GB of traces/month on its no-cost plan.

```bash
flyctl secrets set \
  OTEL_EXPORTER_OTLP_ENDPOINT='https://tempo-prod-04-prod-us-east-0.grafana.net/tempo/v1/traces' \
  OTEL_EXPORTER_OTLP_HEADERS='authorization=Basic <base64(user:token)>' \
  OTEL_SAMPLE_RATE='0.01' \
  OTEL_SERVICE_NAME='jpcite-api' \
  JPINTEL_ENV='prod'
```

`<base64(user:token)>` is built from the Grafana Cloud stack user-id
and the access policy token (Permissions: `traces:write`). Verify in
Grafana Cloud → Explore → Tempo → search by `service.name=jpcite-api`.

## Backend 2: DataDog (free trial / paid)

DataDog accepts OTLP HTTP on `https://otlp.datadoghq.com` (use the
regional variant — `datadoghq.eu` / `us3.datadoghq.com` etc). Trial
plans include APM traces at low volume.

```bash
flyctl secrets set \
  OTEL_EXPORTER_OTLP_ENDPOINT='https://otlp.datadoghq.com/v1/traces' \
  OTEL_EXPORTER_OTLP_HEADERS='dd-api-key=<your-dd-api-key>,dd-otlp-source=jpcite' \
  OTEL_SAMPLE_RATE='0.01' \
  OTEL_SERVICE_NAME='jpcite-api' \
  JPINTEL_ENV='prod'
```

Verify in DataDog → APM → Traces → service `jpcite-api`.

## Backend 3: Jaeger (self-hosted, dev / staging)

For local dev, run Jaeger via Docker:

```bash
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4318:4318 \
  jaegertracing/all-in-one:latest
```

Then point the API at it:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT='http://localhost:4318/v1/traces'
export OTEL_SAMPLE_RATE='1.0'
export OTEL_SERVICE_NAME='jpcite-api-dev'
.venv/bin/uvicorn jpintel_mcp.api.main:app --port 8080
```

Open <http://localhost:16686/> and search by service `jpcite-api-dev`.

## Sampling rationale

| Env | Default rate | Rationale |
| --- | --- | --- |
| prod (`JPINTEL_ENV=prod`) | 0.01 (1%) | 10 req/s × 86400 × 0.01 ≈ 8.6k spans/day. Fits inside every free tier. |
| dev / test | 1.0 (100%) | One developer hitting the API a few hundred times per session — capture everything. |

Bump `OTEL_SAMPLE_RATE` for short-window debugging (e.g. `0.1` for an
hour during a customer incident) and revert.

## Verifying the wiring

1. Set `OTEL_EXPORTER_OTLP_ENDPOINT` to a valid collector URL.
2. Restart the API.
3. Look for `otel_init_ok endpoint=... sample_rate=...` in the boot log.
4. Hit `GET /v1/openapi.json` (excluded from the probe-path skip list).
5. Look for `otel_instrument_fastapi_ok excluded=healthz,readyz,metrics`.
6. Query the backend for `service.name=jpcite-api` traces — within
   30 s of the request the span should appear.

If `otel_init_ok` is missing on boot, either the endpoint is unset
(intentional in dev) or the `opentelemetry-*` packages did not install.
Run `python -c 'import opentelemetry.instrumentation.fastapi'` to
verify the install.

## What is NOT exported

* Request / response bodies (no PII; OTel auto-instrumentation only
  captures method + route + status by default).
* `X-API-Key` headers (FastAPIInstrumentor honors the
  `OTEL_PYTHON_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_*` allowlist — we
  ship with the allowlist empty).
* Database query text (sqlite is not auto-instrumented — only the FastAPI
  HTTP surface is wrapped).

If you need DB-level spans, add `opentelemetry-instrumentation-sqlite3`
to dev deps and call its `SQLite3Instrumentor().instrument()` from the
lifespan — intentionally NOT shipped by default to keep telemetry costs
predictable.
