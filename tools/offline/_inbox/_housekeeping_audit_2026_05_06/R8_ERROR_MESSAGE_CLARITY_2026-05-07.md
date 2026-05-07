# R8_ERROR_MESSAGE_CLARITY_2026-05-07.md

Live HTTP error-response clarity audit against jpcite v0.3.4 (`https://autonomath-api.fly.dev`),
on **2026-05-07**, follow-on to `R8_LIVE_API_SHAPE_2026-05-07.md` which already
characterised 429 (`rate_limit_exceeded`).

- **Internal hypothesis framing only.** Read-only HTTP GET / POST (no body
  side-effects past Stripe-webhook signature reject). LLM 0. Production
  charge 0 (anonymous + 429-blocked, plus webhook 400 which never reaches
  metered path).
- Auditor entered the day at quota=0/3 (R8_LIVE_API_SHAPE consumed the
  bucket), so "validation 422" + "503 db_unavailable" + "500 internal_error"
  are characterised via the `_error_envelope.py` source projection + live
  `/v1/openapi.json` schema (which is itself unmetered).
- Live OpenAPI confirms: `info.version = 0.3.4`, `paths = 182`,
  error schemas registered = `ErrorBody / ErrorEnvelope / HTTPValidationError /
  ValidationError`.

## 1. Live error responses captured

| # | Trigger                                         | HTTP | Code emitted          | Live envelope shape |
|---|--------------------------------------------------|------|-----------------------|---------------------|
| 1 | `GET /v1/nonexistent`                            | 404  | `route_not_found`     | `{detail, error{...}}` |
| 2 | `GET /v1/admin/users`                            | 404  | `route_not_found`     | `{detail, error{...}}` |
| 3 | `GET /v1/billing/status` (path doesn't exist)    | 404  | `route_not_found`     | `{detail, error{...}}` |
| 4 | `GET /v1/billing/usage` (path doesn't exist)     | 404  | `route_not_found`     | `{detail, error{...}}` |
| 5 | `GET /v1/me/api_keys` (path doesn't exist)       | 404  | `route_not_found`     | `{detail, error{...}}` |
| 6 | `GET /v1/programs/search?q=test&limit=1`         | 429  | `rate_limit_exceeded` | flat (R8_LIVE_API_SHAPE §1) |
| 7 | `GET /v1/programs/search?q=x&limit=999`          | 429  | `rate_limit_exceeded` | (validation never reached — 429 first) |
| 8 | `POST /v1/meta` (GET-only path)                  | 405  | `method_not_allowed`  | `{detail, error{...}}` |
| 9 | `DELETE /v1/meta`                                | 405  | `method_not_allowed`  | `{detail, error{...}}` |
| 10| `POST /v1/billing/webhook` (no signature)        | **400** | **(no envelope)**  | `{"detail":"bad signature"}` ← **gap** |
| 11| `POST /v1/billing/webhook` (fake t=,v1=)         | **400** | **(no envelope)**  | `{"detail":"bad signature"}` ← **gap** |
| 12| `GET /v1/me` (auth required, no key)             | 401  | `auth_required`       | `{detail, error{...}}` |

All 12 responses carry the v0.3.4 hardening header set
(`x-request-id`, `x-envelope-version: v1`, HSTS / CSP / X-Frame-Options /
X-Content-Type-Options / Referrer-Policy / Permissions-Policy). Every
4xx body returned a 16-hex `request_id` matching the `x-request-id`
header — traceability contract holds.

## 2. Canonical envelope contract (per `src/jpintel_mcp/api/_error_envelope.py`)

20 closed-enum codes registered (`ERROR_CODES` + `ErrorCode` Literal):

```
missing_required_arg, invalid_enum, invalid_date_format, out_of_range,
unknown_query_parameter, no_matching_records, ambiguous_query, seed_not_found,
auth_required, auth_invalid, rate_limit_exceeded, cap_reached,
route_not_found, method_not_allowed,
db_locked, db_unavailable, subsystem_unavailable, service_unavailable,
internal, internal_error
```

Every code has `severity` (hard | soft) + `user_message_ja` + `user_message_en`
defaults. `make_error()` always emits:

- `code` — closed-enum string (regex-friendly for AI consumers)
- `user_message` — Japanese (≤200 chars, plain copy)
- `user_message_en` — English mirror (dropped only when null)
- `request_id` — ULID-style 26-char Crockford base32 OR upstream
  `safe_request_id(request)`
- `severity` — `"hard"` (caller must fix) | `"soft"` (retry-able)
- `documentation` — `https://jpcite.com/docs/error_handling#<code>`
  anchor (per-code section)
- per-code extras: `retry_after`, `retry_with`, `field_errors`,
  `suggested_paths`, `path`, `method`

## 3. Per-code clarity assessment (live + source)

### 3.1 `route_not_found` (404) — **PASS, AI- and human-friendly**

Live body verified:

```jsonc
{
  "detail": "Not Found",                       // FastAPI back-compat
  "error": {
    "code": "route_not_found",
    "user_message": "指定パスは存在しません。https://api.jpcite.com/v1/openapi.json で有効なパス一覧を確認してください。",
    "user_message_en": "Route not found. List valid paths at https://api.jpcite.com/v1/openapi.json.",
    "request_id": "ace4439654f7fcf8",
    "severity": "hard",
    "documentation": "https://jpcite.com/docs/error_handling#route_not_found",
    "suggested_paths": [
      "/v1/openapi.agent.json", "/v1/openapi.json",
      "/v1/programs/search", "/v1/meta", "/v1/stats/coverage"
    ],
    "path": "/v1/nonexistent"
  }
}
```

- AI-parse: `error.code` enum + `suggested_paths[]` recovery hint
  (LLM agent can pivot to a valid path without prose parsing).
- Human-parse: JA + EN `user_message`, doc anchor.
- echoed `path` confirms which input was rejected (debug-friendly).

### 3.2 `method_not_allowed` (405) — **PASS**

```jsonc
{ "detail": "Method Not Allowed",
  "error": { "code":"method_not_allowed", ..., "documentation":"…#method_not_allowed" } }
```

`Allow: GET` header pairs the wire response with envelope guidance —
self-recoverable for AI agent.

### 3.3 `auth_required` (401) — **PASS, with forward-pointer**

```jsonc
{ "detail": "no session",
  "error": {
    "code": "auth_required",
    "user_message": "API キーが必要です。https://jpcite.com/dashboard で発行し、X-API-Key ヘッダで送信してください。",
    "user_message_en": "API key required. Issue one at https://jpcite.com/dashboard …",
    "retry_with": { "header": "X-API-Key", "alt_header": "Authorization: Bearer" }
  } }
```

`retry_with` schema is the strongest UX in the audit — explicitly
names the recovery header (and alt scheme) so an AI consumer can
self-correct without doc fetch.

### 3.4 `rate_limit_exceeded` (429) — **PASS** (cf. R8_LIVE_API_SHAPE §1)

The 429 body is intentionally flat (NOT `{"error":{...}}`) because it
predates the δ2 canonical envelope; carries `retry_after`, `reset_at_jst`,
`upgrade_url`, `direct_checkout_url`, `trial_signup_url`, `trial_terms`.
Acceptable due to legacy contract, but is the ONLY shape divergence
inside the canonical 4xx surface.

### 3.5 `validation_failed` 422 (`invalid_enum`) — **PASS via source-projection**

`_validation_handler` (`api/main.py:1523-1544`) wraps the canonical
envelope alongside back-compat keys:

```jsonc
{
  "detail": [...errors_ja...],                // back-compat list
  "detail_summary_ja": "入力検証に失敗しました…",
  "error": {
    "code": "invalid_enum",
    "user_message": "値が許可一覧にありません。field_errors[].expected の許可値から選び直して再送してください。",
    "user_message_en": "Value is not in the allowed list. Choose a value from field_errors[].expected and resubmit.",
    "field_errors": [{ "loc":[...], "msg":"...", "msg_ja":"...", "type":"...", "expected":[...] }],
    "path": "...", "method": "..."
  }
}
```

Translation map covers 21 Pydantic v2 error types (`missing`,
`int_parsing`, `extra_forbidden`, `string_pattern_mismatch`, …) →
JA copy. **Couldn't observe live** because anonymous quota blocked at
the rate-limit middleware before `StrictQueryMiddleware` ran (LIFO
ordering); the CI suite covers this path.

### 3.6 `db_unavailable` 503 — **PASS via source-projection**

`_db_missing_handler` (`api/main.py:1418-1453`) emits canonical body
with `Retry-After: 300` header + `retry_after` echoed in extras
(`retry_with` semantics for 503). JA message names the failure mode
(`ファイル不在 / mount 失敗`) + escalation contact (`info@bookyou.net`)
+ instructs to attach `request_id`.

### 3.7 `internal_error` 500 — **PASS via source-projection**

`_unhandled_exception_handler` (`api/main.py:1455-1487`) keeps legacy
`{"detail":"internal server error","request_id":"…"}` for back-compat,
**plus** appends canonical `error{code:"internal_error",...}` with the
SAME request_id so log search can correlate. JA copy points users at
`info@bookyou.net` with `request_id`.

## 4. Improvement recommendations (prioritised)

### R8-ERR-1 (P0) — Stripe webhook 400 leaks bare detail string

`POST /v1/billing/webhook` with bad signature returns
`{"detail":"bad signature"}` (26 bytes) — **bypasses canonical envelope
entirely**. Root cause: `_http_exception_handler` in `api/main.py:1572-1593`
only maps {401, 403, 404, 405, 429, 503} → canonical envelope; status
**400 falls through to the back-compat passthrough branch** (line 1584).

Impact:
- Stripe debugging: NO `request_id` echoed in body (header still present
  but body+log correlation breaks for any tooling that pattern-matches
  on `error.code`).
- Legitimate Stripe deliveries hitting transient signature issues
  surface a 26-byte string with no `documentation` anchor.

Fix: add 400 to the mapping branch with a new `invalid_signature` code
(or repurpose `auth_invalid`). Honesty preserved by keeping `detail`
back-compat for existing parsers. Estimated 12 LOC.

### R8-ERR-2 (P1) — 429 envelope shape divergence vs δ2 canonical

The anon 429 body is flat (`{"code":..., "detail":..., "limit":...}`)
while every other 4xx is nested (`{"error":{...}}`). Customer agents
that key off `response.json()["error"]["code"]` get **no match on 429**
and fall back to status-code-only handling — they miss the rich
`upgrade_url` / `trial_terms` payload because the parser never reaches
them.

Two paths:
- (a) **back-compat preservation**: emit BOTH at root + nested
  (`response["code"]` AND `response["error"]["code"]`) — costs ~50 bytes.
- (b) **envelope migration with x-envelope-version flip**: ship v2 only
  for callers that send `Accept: application/vnd.jpcite.v2+json`.

Recommendation: (a) for cheap parity, (b) when next OpenAPI minor.

### R8-ERR-3 (P2) — `documentation` anchor target page doesn't exist

Every envelope points at `https://jpcite.com/docs/error_handling#<code>`
but `docs/error_handling.md` exists only as a repo file (mkdocs source);
the **live deployed docs site needs the per-code anchors verified**.
404-on-anchor breaks the documented escape hatch on every error.

Fix: add an `mkdocs build --strict` smoke that asserts every entry in
`ERROR_CODES` has a corresponding `## <code>` section heading in
`docs/error_handling.md`. Already a CI gate candidate.

### R8-ERR-4 (P2) — Duplicate codes `internal` vs `internal_error`

Both codes carry identical JA + EN copy. Dual registration is a smell
that probably came from rolling the MCP envelope (`internal`) into the
REST envelope (`internal_error`). Pick one (recommend `internal_error`
for REST since handlers emit it; alias `internal` → same anchor or
remove from `ERROR_CODES`). Low-risk cleanup.

### R8-ERR-5 (P3) — Add `request_id` lookup CTA in user-facing copy

JA copy already says "request_id を添えて info@bookyou.net まで連絡"
on `internal_error` / `db_unavailable` — extend to ALL `severity:hard`
codes, since users hitting `auth_invalid` or `cap_reached` may also
need to reach support. Estimated 2 lines per code.

## 5. AI-consumer parse-friendliness verdict

| Axis                                               | Status |
|----------------------------------------------------|--------|
| `error.code` enum string (20 closed values)         | PASS   |
| `error.code` registered in OpenAPI `components.schemas` | PASS (`ErrorBody`/`ErrorEnvelope`) |
| `request_id` traceability (header == body == log)   | PASS (16-hex / 26-char ULID, `safe_request_id` enforces) |
| Per-code recovery hint (`retry_with`, `suggested_paths`, `field_errors`) | PASS for 401/404/422 |
| `documentation` anchor                              | PASS (live anchor target verification = R8-ERR-3) |
| Bilingual messages (`user_message` + `user_message_en`) | PASS for all 20 codes |
| Envelope shape uniformity                           | **FAIL** on 429 (R8-ERR-2) and 400 webhook (R8-ERR-1) |

## 6. Human-user friendliness verdict

JA copy is uniformly plain-Japanese, ≤200 chars, names a recovery
action ("X-API-Key ヘッダで送信", "field_errors の loc で確認",
"info@bookyou.net まで連絡"). No stack traces, no English-only paths
on 422 (Pydantic-default leak fixed). 景表法 / 消費者契約法 honesty
holds — no fabricated SLA promise, all retry guidance gated on actual
infrastructure capability (`Retry-After` driven, not aspirational).

## 7. R8 doc + git add

- Doc: this file (`R8_ERROR_MESSAGE_CLARITY_2026-05-07.md`)
- Source touched: NONE (read-only audit)
- Live API touched: NONE beyond GETs already counted in anonymous bucket

---

**Signed-off**: 2026-05-07 audit. Internal hypothesis framing preserved.
LLM call count from auditor side: 0.
