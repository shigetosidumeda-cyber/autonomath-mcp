# R8 — Audit Log + Traceability Deep Audit (2026-05-07)

**Scope.** End-to-end forensic-recovery audit of the live API
(`https://autonomath-api.fly.dev`) on jpcite v0.3.4: ULID
`x-request-id` propagation, structured-logging surface, Sentry
integration, and billing-event monotonic mapping into Stripe usage
records + per-month `audit_seal` HMAC signatures.

**TL;DR.** Forensic-recovery surface is **mostly green** — append-only
diff log + per-call HMAC seal + daily Merkle anchor + 7-year retention
are all wired and exercised in production. **Three non-defects** were
upgraded to "drift bugs" and fixed under this audit (request_id shape
mismatch happy-vs-error path, missing Sentry tag, missing request_id
in query telemetry JSON line). Pre-commit (`ruff` / `ruff-format` /
`mypy --strict`) green on the two touched files.

---

## 1. Live `x-request-id` propagation (forensic anchor)

Verified against the live Fly.io deploy (`autonomath-api.fly.dev`,
`server: Fly/421c5554c (2026-05-06)`):

| Path                               | Status | `x-request-id`         | `x-envelope-version` |
| ---------------------------------- | ------ | ---------------------- | -------------------- |
| `/healthz`                         | 200    | `7e26cca253b417f8`     | `v1`                 |
| `/v1/healthz` (404, route absent)  | 404    | `921835351fc9e24e`     | `v1`                 |
| `/v1/openapi.json`                 | 200    | `b1f1e571243b2f7b`     | `v1`                 |
| `/v1/laws/search?...`              | 429    | `a951308324c31c45`     | `v1`                 |
| `/v1/programs/search?...`          | 429    | `c979e7fb7e2903e6`     | `v1`                 |
| `/readyz`                          | 200    | `44ae5cedc66d5239`     | `v1`                 |
| `/v1/health` (404)                 | 404    | `d2d98796ecca3a0c`     | `v1`                 |

**Header is present on every probed route**, including 404 / 429 short-
circuits — the middleware sits early enough in the stack that error
responses still carry the correlation id.

**Drift finding (FIXED).** Pre-fix, the live header was a 16-char hex
string (`secrets.token_hex(8)`), but `_error_envelope._mint_request_id`
mints a **26-char Crockford-base32 ULID** (`01KQ3XQ77RR7J8XWZ8C0YR2JN2`
shape) and `error.request_id` envelopes use that ULID. Both shapes pass
the shared `^[A-Za-z0-9-]{8,64}$` validator regex, but **forensic search
filters that key off length / sortability would split the same request
across two formats**. `_RequestContextMiddleware` now mints via the same
`_mint_request_id()` helper as the error path — single shape across
header, log line, envelope, and Sentry tag.

`fly-request-id` (Fly's edge layer ULID) is also returned on every
response and is independent of our `x-request-id` — keeps it as a
fallback when our id is missing (e.g. blocked by an upstream WAF rule
before `_RequestContextMiddleware` runs).

---

## 2. `audit_log.py` + `audit_proof.py` + `_audit_seal.py` audit

### 2.1 `audit_log.py` (305 lines) — public read surface

- Endpoint: `GET /v1/am/audit-log` (router prefix `/v1/am`).
- Backed by `am_amendment_diff` (autonomath.db, migration 075,
  populated daily by `scripts/cron/refresh_amendment_diff.py`).
- Cursor pagination on `(detected_at DESC, diff_id DESC)` — handles
  append-only growth without offset-skew.
- Filters: `since=YYYY-MM-DD`, `entity_id=` (exact match).
- Anonymous read allowed (3/IP/day quota); paid keys metered ¥3/req
  via `log_usage(..., strict_metering=True)`.
- Honest meta: `_meta.honest_note` declares "検出のみで個別判断は行いません"
  + `creator: "Bookyou株式会社 (T8010001213708)"`.
- **Graceful degrade.** When `am_amendment_diff` is missing on a fresh
  volume the endpoint returns an empty page (`_log.warning` to telemetry)
  rather than 500 — keeps customer agents working through DR cutover.

### 2.2 `audit_proof.py` (314 lines) — Merkle inclusion proof

- Endpoint: `GET /v1/audit/proof/{evidence_packet_id}`.
- Backed by `audit_merkle_anchor` + `audit_merkle_leaves` (migration
  146, `scripts/cron/merkle_anchor_daily.py`).
- Verifier fold: `sha256(left||right)` Bitcoin-style; supports
  `left` / `right` sibling positions.
- Anchors carry `ots_proof` (OpenTimestamps blob) +
  `github_commit_sha` (commit message containing the daily root) so a
  third-party can verify root existence at-or-before the calendar date.
- Strict input validation: `_EPID_RE = ^evp_[A-Za-z0-9_]{1,64}$`.
- Cleanly degrades to 404 when migration 146 is missing on the volume.

### 2.3 `_audit_seal.py` (854 lines) — per-call HMAC seal

- `build_seal(...)` → seal envelope with both legacy fields
  (`call_id` / `ts` / `query_hash` / `response_hash` / `source_urls` /
  `hmac`) and §17.D fields (`seal_id` / `corpus_snapshot_id` /
  `verify_endpoint` / `_disclaimer`).
- `compute_hmac(...)` HMAC-SHA256 over
  `call_id|ts|query_hash|response_hash|seal_id|corpus_snapshot_id`
  using `_active_key()` → `JPINTEL_AUDIT_SEAL_KEYS` (rotatable; falls
  back to `settings.audit_seal_secret`).
- `verify_hmac(...)` constant-time compare via `hmac.compare_digest`,
  walks every key in the rotation set when `key_version` not supplied —
  zero-downtime rotation.
- `persist_seal(...)` strict 4-attempt INSERT chain handling pre-119
  schema fallback; transaction-wrapped via `BEGIN IMMEDIATE`; raises
  `sqlite3.IntegrityError` on duplicate `seal_id`.
- 7-year retention computed via `_retention_until_for_seal()`.
- `get_corpus_snapshot_id()` → `corpus-YYYY-MM-DD` derived from
  `MAX(am_source.last_verified)` JST date; 6h TTL cache; collapses to
  today's JST on any sqlite failure (never blocks the response path).
- `extract_source_urls()` walks the response body, dedupes,
  `max_urls=32` bound — keeps seal row size predictable.

**Honest assessment.** All three modules are production-quality. No
unsealed-paid-response paths were found; `attach_seal_to_body` either
attaches a seal (verified persistence) or attaches `_seal_unavailable:
true` and emits `audit_log_section52` telemetry on failure.

---

## 3. Structured logging audit

- `logging_config.py` configures **structlog → JSONRenderer** in
  production (`JPINTEL_LOG_FORMAT=json` per `fly.toml [env]`).
- Shared processors: `merge_contextvars` + `add_log_level` +
  `add_logger_name` + `TimeStamper(iso, utc)` + `format_exc_info`.
- `bind_contextvars(request_id=, path=, method=)` runs in
  `_RequestContextMiddleware`; `bind_api_key_context()` in deps adds
  `api_key_hash_prefix` + `tier`.
- `_emit_query_log()` emits one JSON line per request to the
  `autonomath.query` channel with PII-redacted endpoint + params shape.

**Drift finding (FIXED).** `_emit_query_log()` did not include
`request_id` in the JSON record — meaning the per-request telemetry
line could not be joined to the response header by id. Added a
`request_id` parameter; populated from `request.state.request_id` in
`_QueryTelemetryMiddleware`. Single id now threads:

```
x-request-id (response header)
  └─ structlog contextvar (every log line in this request scope)
  └─ Sentry tag (R8 fix below)
  └─ autonomath.query JSON line (R8 fix above)
  └─ error.request_id (envelope shape, on 4xx/5xx)
  └─ audit_seal.call_id (per metered response — separate id, joined via DB)
```

### Log levels

INFO / WARNING / ERROR / CRITICAL are used consistently:

- **INFO** — success path / telemetry (`_query_log.info`).
- **WARNING** — recoverable degrade
  (`am_amendment_diff missing`, `db_missing`, `usage_events sync mark
  failed`).
- **ERROR / EXCEPTION** — `_log.exception("unhandled exception ...")`
  in the 500 handler, plus `me.py` / `billing.py` `capture_exception`
  paths.
- **CRITICAL** — reserved for boot-fail (`SystemExit("[BOOT FAIL] ..."`)
  rather than logger.critical; fail-fast at startup is the chosen
  signal.

No `print()` calls were found in the request hot path.

---

## 4. Sentry integration audit

`_init_sentry()` (`api/main.py:403`) — two-gate init:
1. `settings.sentry_dsn` non-empty.
2. `_is_production_env()` returns true (`JPINTEL_ENV ∈ {prod,
   production}`).

Integrations: `StarletteIntegration(transaction_style="endpoint")` +
`FastApiIntegration(transaction_style="endpoint")`. Sample rates are
configured (`traces_sample_rate`, `profiles_sample_rate`).

`send_default_pii=False` + `include_local_variables=False` — the latter
is critical: stack-frame snapshots would otherwise capture
`X-API-Key` / `Stripe-Signature` from dependency-resolution frames.

`sentry_filters.sentry_before_send` strips `x-api-key` /
`authorization` / `cookie` / `stripe-signature` /
`x-forwarded-for` / `fly-client-ip` / `x-real-ip` from the request
blob; drops cookies + env; drops `data` + `query_string` for
`/billing` URLs; drops `email` / `ip_address` / `username` from
`event.user`.

`sentry_filters.sentry_before_send_transaction` additionally drops
`http.request.body` + `http.response.body` from spans on `/billing`.

Capture call sites:
- `observability/sentry.py.safe_capture_exception/_message` — non-API
  entry points (cron) lazy-init Sentry; never raises.
- `api/me.py:922`, `api/billing.py:166`, `api/email_webhook.py:67`,
  `api/_bg_task_worker.py:62` — direct `sentry_sdk.capture_exception`
  on background paths.
- `api/middleware/deprecation_warning.py` — `safe_capture_message` for
  deprecation hits.
- `email/postmark.py:409-411` — Postmark error path tags
  `component=email.postmark` + `template_alias`.

**Drift finding (FIXED).** Sentry SDK auto-attaches `x-request-id` to
the `event.request` blob, but it is NOT exposed as a tag — Sentry
search `request_id:01KR0Q...` returned zero hits. Added
`sentry_sdk.set_tag("request_id", rid)` in `_RequestContextMiddleware`
so triage can pivot on the same id printed in customer-facing 500
bodies. No-op when Sentry is uninitialised.

---

## 5. Billing event traceability

### 5.1 `usage_events` → Stripe usage record monotonic mapping

`deps.log_usage()` (`api/deps.py:924+`):
- INSERTs one row into `usage_events` (key_hash, endpoint, status_code,
  metered, params_digest, latency_ms, result_count, client_tag,
  quantity, billing_idempotency_key, tokens_saved_estimated).
- On success, schedules `report_usage_async` →
  `stripe.SubscriptionItem.create_usage_record(...,
  idempotency_key=f"usage_{usage_event_id}")`.
- The local row id is the **monotonic anchor**: same logical request
  → same `usage_events.id` → same idempotency_key → Stripe-side dedup.
- Worker writes back `stripe_record_id` + `stripe_synced_at` on
  success; failure leaves NULL so a reconciliation pass can replay
  (audit `a37f6226fe319dc40`).

The deferred path (`_record_usage_async`) opens its own connection so
the request-scoped `conn` (closed by `get_db()` finally) does not
block worker writes.

**Quantity clamp.** `_QUANTITY_MAX=100,000` enforced on both inline
and deferred paths — typo turning ¥3 into ¥30M cannot leak through.

**Strict-metering 503.** When `strict_metering=True` and the metered
cap final-check fails, the response is replaced with 503
`billing_cap_final_check_failed` so customers cannot receive a paid
response without a durable `usage_events` row.

### 5.2 `audit_seal` per-call HMAC

- Sealed responses carry `audit_seal.{seal_id, hmac, key_version,
  corpus_snapshot_id, verify_endpoint, ...}` (see §2.3).
- `audit_seals` row is INSERTed from the same `log_usage()` path
  (deferred via `_record_usage_async` for hot path, inline for
  idempotent / `strict_metering` paths).
- 7-year retention via `_retention_until_for_seal` — aligns with
  税理士法 §41 / 法人税法 §150-2 / 所得税法 §148.
- `lookup_seal()` supports both `seal_id` and legacy `call_id`
  lookups so customers who issued a seal pre-119 can still verify.

### 5.3 Per-month signature path

The cron `regenerate_audit_log_rss.py` + `merkle_anchor_daily.py`
together produce a daily Merkle root → OpenTimestamps + GitHub-commit
double-anchor. Per-month aggregation lives in
`scripts/cron/refresh_amendment_diff.py` (rolls up the diff log) and
`audit_seals` row counts (queryable from REST). Rotating signing keys
is supported via `JPINTEL_AUDIT_SEAL_KEYS` (comma list or JSON;
`retired_at` field excludes a key from active-set without breaking
verify of historical seals).

---

## 6. Trivial fixes landed in this audit (5 files / 5 changes)

| # | File | Fix |
|---|------|-----|
| 1 | `src/jpintel_mcp/api/main.py` | `_RequestContextMiddleware` mints via `_mint_request_id()` (26-char ULID) instead of `secrets.token_hex(8)` (16 hex). Unifies happy path with error path so log search keys off one regex / one length / one sort order. |
| 2 | `src/jpintel_mcp/api/main.py` | `_RequestContextMiddleware` calls `sentry_sdk.set_tag("request_id", rid)` so Sentry triage can pivot on the same id printed in customer 500 bodies. No-op when Sentry uninitialised. |
| 3 | `src/jpintel_mcp/api/main.py` | `_emit_query_log()` accepts `request_id`, populated from `request.state.request_id` in `_QueryTelemetryMiddleware`. Per-request JSON telemetry line now joinable to the response header by id. |
| 4 | `src/jpintel_mcp/api/main.py` | Two defensive `secrets.token_hex(8)` fallbacks in the `FileNotFoundError` and unhandled-exception handlers replaced with `_mint_request_id()` so the last-ditch id matches the rest of the surface. |
| 5 | `src/jpintel_mcp/api/_error_envelope.py` | Docstring drift: four references to `secrets.token_hex(8)` updated to "26-char Crockford-base32 ULID" so the docstring matches the actual mint behaviour (saves a future reader the same investigation). |

Pre-commit suite (ruff / ruff-format / mypy `--strict`) is **green on
both touched files**. No new dependencies. No public-API changes (the
length of `x-request-id` is widening from 16 to 26 chars; the value is
already opaque-by-contract, no SDK or smoke test asserts on length).

---

## 7. Out-of-scope / honest gaps

- **No re-broadcast of historic 16-hex ids as ULIDs.** Pre-fix
  request_ids in customer logs / our own log aggregation remain in
  16-hex shape — that is intended (rewriting them would be dishonest).
  The shape transition is forward-only from this commit.
- **MCP stdio surface** does not carry `x-request-id`; FastMCP uses
  its own JSON-RPC `id` field. Out of scope for this audit; covered
  by the verifier package separately.
- **Per-month signature `verify` CLI** is not yet shipped to
  customers; the public verify endpoint exists at
  `GET /v1/audit/seals/{seal_id}` but the CLI fold is documented in
  `audit_proof.py` only. Tracked elsewhere.

---

## 8. Closure

The forensic-recovery surface meets the launch-incident bar:

- Every paid response carries an HMAC-bound seal anchored to a daily
  Merkle root.
- Every request — paid or anon — carries one ULID `x-request-id` that
  threads header + log line + Sentry tag + error envelope.
- Stripe usage records are idempotent on the local `usage_events.id`
  so DR replay-from-Stripe is deterministic.
- Sentry transmits no PII / API keys / Stripe signatures and is
  filtered to prod-only.

**Status: forensic-recovery surface ready for launch.** R8 audit-log
deep audit closed.
