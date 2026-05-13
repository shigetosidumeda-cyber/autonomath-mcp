# Canonical response envelope (v2)

Status: **opt-in** (default = legacy shape).

The v2 envelope unifies the wire shape that customer agents (Cursor / Cline / Continue / Claude Desktop / Zapier / Make / RPA / SDK consumers) pattern-match on. Pre-v2, jpcite emitted ~4 distinct success shapes (`{total,limit,offset,results}`, nested 360 blocks, jpcite-specific status/explanation/meta, raw pydantic dumps). v2 collapses every successful response into one shape; every error into one shape.

## When to use v2

Use v2 when:

- You are an **AI/agent client** that pattern-matches on `status`, `error.code`, or `meta.request_id`.
- You want **deterministic follow-up calls** via `suggested_actions[]`.
- You want **citations** (`citations[]`) as a first-class field rather than parsing each row's inline source_url.
- You want a **single error shape** for every 4xx/5xx instead of code-branch mapping the legacy union of `{detail}`, `{detail, error}`, `{detail, limit, resets_at}`, etc.

Use legacy when:

- You are an **existing browser frontend** whose JS still reads `body.total` / `body.results`.
- You are a **CSV/XLSX/ICS exporter** — those formats are produced by `?format=csv|xlsx|...` and are unaffected by the envelope flag.
- You are a **dashboard / SLA monitor** that already pattern-matches on the legacy `am/health/deep` shape.

## How to opt in

Use the explicit media type:

   ```http
   GET /v1/programs/search?q=IT導入
   Accept: application/vnd.jpcite.v2+json
   ```

The response carries an `X-Envelope-Version: v2` header so a client can confirm which shape it received without parsing the body. Caches respect `Vary: Accept, X-Envelope-Version` so legacy and v2 callers share the same path safely.

## Wire shape — success

```json
{
  "status": "rich | sparse | empty | partial | error",
  "query_echo": {
    "normalized_input": {"q": "IT導入"},
    "applied_filters": {"tier": ["S","A"], "prefecture": "東京都"},
    "unparsed_terms": []
  },
  "results": [ /* rows, same shape as legacy results[] */ ],
  "citations": [
    {
      "source_id": "src-...",
      "source_url": "https://www.meti.go.jp/...",
      "publisher": "経済産業省",
      "title": "...",
      "fetched_at": "2026-04-29T03:00:00Z",
      "checksum": "sha256:...",
      "license": "pdl_v1.0",
      "field_paths": ["/results/0/amount_max_yen"],
      "verification_status": "verified"
    }
  ],
  "warnings": [],
  "suggested_actions": [
    {"tool": "get_program", "args": {"unified_id": "UNI-..."}},
    {"endpoint": "/v1/programs/{unified_id}", "args": {"unified_id": "UNI-..."}}
  ],
  "meta": {
    "request_id": "01KQ3XQ77RR7J8XWZ8C0YR2JN2",
    "api_version": "v2",
    "latency_ms": 42,
    "billable_units": 1,
    "client_tag": "顧問先-001"
  }
}
```

Status semantics:

| status | results | required extras |
|---|---|---|
| `rich` | ≥ 5 rows | — |
| `sparse` | 1–4 rows | (optional) `retry_with` |
| `empty` | 0 rows | `empty_reason` (`no_match` / `filters_too_narrow` / `source_unavailable` / `license_blocked`); `retry_with` recommended |
| `partial` | ≥ 0 rows | `warnings[]` MUST be non-empty |
| `error` | `[]` | `error` envelope (see below) |

## Wire shape — error

```json
{
  "status": "error",
  "results": [],
  "warnings": [],
  "citations": [],
  "query_echo": {...},
  "error": {
    "code": "RATE_LIMITED",
    "user_message": "レート制限を超過しました。Retry-After ヘッダの秒数だけ待ってから再試行してください。",
    "developer_message": "anonymous IP quota: 3/day (reset <next JST 00:00>)",
    "retryable": true,
    "retry_after": 60,
    "documentation": "https://jpcite.com/docs/api-reference/response_envelope#rate_limited"
  },
  "meta": {
    "request_id": "01KQ3XQ77RR7J8XWZ8C0YR2JN2",
    "api_version": "v2",
    "latency_ms": 1,
    "billable_units": 0
  }
}
```

Closed enum on `error.code`:

| code | retryable | typical HTTP | when |
|---|---|---|---|
| `RATE_LIMITED` | true | 429 | per-second throttle exhausted; honour `Retry-After` |
| `UNAUTHORIZED` | false | 401 | missing/invalid X-API-Key |
| `FORBIDDEN` | false | 403 | auth ok but action not permitted (license-gate is separate) |
| `NOT_FOUND` | false | 404 | resource lookup miss; agent should NOT retry the same key |
| `VALIDATION_ERROR` | false | 400/422 | bad input field; check `developer_message` for the field path |
| `LICENSE_GATE_BLOCKED` | false | 403 | row(s) dropped by `?license=` filter or proprietary policy |
| `QUOTA_EXCEEDED` | false | 429 | quota cap reached (anon 3/日 or paid customer-set monthly cap) |
| `INTEGRITY_ERROR` | true | 500 | DB integrity / cross-source mismatch detected mid-request; retry once |
| `SERVER_ERROR` | true | 500 | unexpected exception; `developer_message` carries the trace pointer |

## MCP shape

MCP tools wrap the v2 envelope in a CallToolResult per the 2025-06-18 spec:

```json
{
  "structuredContent": { /* StandardResponse JSON */ },
  "content": [
    {"type": "text", "text": "rich · 23 results"}
  ]
}
```

Errors set `"isError": true` at the result root and surface `error.user_message` in the text content block.

## Migrated routes (worked examples)

The following routes accept the `Accept: application/vnd.jpcite.v2+json` opt-in today. Other routes return the legacy shape regardless of the header — they will be migrated incrementally.

| Route | Default shape | v2 shape |
|---|---|---|
| `GET /v1/programs/search` | `{total, limit, offset, results}` | `StandardResponse[Program]` |
| `GET /v1/houjin/{bangou}` | nested 360 block | single-result `StandardResponse[dict]` with `citations[]` |
| `GET /v1/am/health/deep` | `{status, version, checks, timestamp_utc}` | single-result `StandardResponse[dict]` (`ok` returns a sparse single-result envelope; `degraded` / `unhealthy` return `partial`) |

## Sample v2 response

`GET /v1/programs/search?q=IT導入&tier=S` with `Accept: application/vnd.jpcite.v2+json`:

```json
{
  "status": "rich",
  "query_echo": {
    "normalized_input": {"q": "IT導入"},
    "applied_filters": {"tier": ["S"], "fields": "default", "limit": 20, "offset": 0},
    "unparsed_terms": []
  },
  "results": [ /* 7 program rows, same shape as legacy results[] */ ],
  "citations": [],
  "warnings": [],
  "suggested_actions": [],
  "meta": {
    "request_id": "01KQ3XQ77RR7J8XWZ8C0YR2JN2",
    "api_version": "v2",
    "latency_ms": 42,
    "billable_units": 1
  }
}
```

(`citations[]` is empty here because the rows already carry `source_url` inline; routes with separate provenance — e.g. `/v1/houjin/{bangou}` — populate `citations[]` directly.)

## Compatibility timeline

- **2026-04-30** — v2 ships as opt-in via `Accept: application/vnd.jpcite.v2+json`.
- **2026-05-06** (launch) — v2 documented in API reference, MCP tools, and SDK READMEs as the recommended shape for AI/agent clients.
- **2026-05-06 → 2026-08-04** (90-day window) — both shapes supported in parallel. Legacy callers see no change. v2 adoption tracked via `X-Envelope-Version` access logs.
- **2026-08-04** — compatibility review point. v1 remains supported unless a separate schema update notice is published in advance; client negotiation stays header-only during this period.

## Stability

- The v2 wire shape is **stable** for the compatibility period. Adding new top-level keys is permitted; renaming or removing existing ones requires `api_version` bump.
- `error.code` is a closed enum. Adding a new code is permitted; renaming requires `api_version` bump.
- Per-row payload (inside `results[]`) follows each route's own contract, unchanged from v1.

## See also

- [api-reference.md](../api-reference.md) — REST API reference
- [error_handling.md](../error_handling.md) — error codes and retry guidance
- [sdks/typescript.md](../sdks/typescript.md) — SDK usage
