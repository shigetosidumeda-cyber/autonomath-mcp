# jpcite — Security Posture (operator-only)

This document is **excluded from the public docs site** via
`mkdocs.yml::exclude_docs`. Public-facing copy lives in `SECURITY.md`
(vulnerability disclosure) and `docs/compliance/data_governance.md`
(data handling).

Audience: solo operator (Bookyou 株式会社, info@bookyou.net) and any
future contractor doing a security review. Last updated 2026-04-25.

## 1. Threat model

jpcite is a thin REST + MCP wrapper over a SQLite corpus of public
program data. There is no PII at rest — the only customer-private fields
are `api_keys.key_hash` (HMAC, salted) and `customers.email`. The
realistic threat surface is therefore narrow:

| Threat | Vector | Why it matters |
| --- | --- | --- |
| **Scraping / bulk export** | Anonymous burst over /v1/programs/search | Devalues the API as a paid product. The data IS public, but normalised + tiered + cited form is our differentiator. |
| **Cost DDoS** | Burst against authed key (paid) | At ¥3/req metered, a runaway agent loop or stolen key directly costs the operator (Anthropic / Stripe pass-through is asymmetric). |
| **Fuzzer probing** | Loop hitting unhandled paths | Generates Sentry noise, masks real incidents. |
| **PII exfiltration** | None at rest; query params could carry T-numbers / 法人番号 | Mitigated via `INV-21 redact_pii` middleware on the query telemetry log. |
| **Aggregator contamination** | Banned-domain rows leaking into `programs.source_url` | Hard-fail boot via `INV-04` on lifespan startup. Past incident → 詐欺 risk. |
| **Stripe webhook spoofing** | Forged events to /v1/billing/webhook | Mitigated via Stripe-Signature header verification inside the handler. |
| **API key leak** | Customer publishes key on GitHub | Self-rotate via /v1/me/keys/rotate. Operator-side: revoke + invalidate cap cache. |

Out of scope (intentionally): geographic content blocking, DDoS at
the Tbps scale (Cloudflare absorbs), insider threat (solo ops).

## 2. Defense layers (top-down)

```
            ┌─────────────────────────────────────────────────────┐
            │ 1. Cloudflare WAF Custom Rules                       │
            │    – block empty UA / known-bad bots                  │
            │    – challenge curl/wget without X-API-Key on data    │
            │    – allow Tor (no defensive gain to block)           │
            │    cloudflare-rules.yaml::custom_rules                │
            └─────────────────────────────────────────────────────┘
                                 │
            ┌─────────────────────────────────────────────────────┐
            │ 2. Cloudflare Rate Limiting (zone-wide)              │
            │    – /v1/* 1000 req/min global                        │
            │    – /v1/programs/search 500 req/min global           │
            │    – per-IP 120 req/min                               │
            │    – per-key emergency cap 5000 req/min               │
            │    – 5xx loop → managed challenge                     │
            │    cloudflare-rules.yaml::rate_limiting_rules         │
            └─────────────────────────────────────────────────────┘
                                 │
            ┌─────────────────────────────────────────────────────┐
            │ 3. App middleware: RateLimitMiddleware (D9)          │
            │    – 10 req/sec per paid key, burst 20                │
            │    – 1 req/sec per anon /32 or /64, burst 5           │
            │    – returns 429 + Retry-After (RFC 7231)             │
            │    api/middleware/rate_limit.py                       │
            └─────────────────────────────────────────────────────┘
                                 │
            ┌─────────────────────────────────────────────────────┐
            │ 4. Router dep: enforce_anon_ip_limit (B-series)      │
            │    – 3 req/日 per /32 or /64 (JST 翌日リセット)       │
            │    api/anon_limit.py                                  │
            └─────────────────────────────────────────────────────┘
                                 │
            ┌─────────────────────────────────────────────────────┐
            │ 5. App middleware: CustomerCapMiddleware (P3-W)      │
            │    – per-key monthly_cap_yen self-cap                 │
            │    – 503 + cap_reached:true                           │
            │    api/middleware/customer_cap.py                     │
            └─────────────────────────────────────────────────────┘
                                 │
            ┌─────────────────────────────────────────────────────┐
            │ 6. Stripe metered billing                            │
            │    – ¥3/req (税込 ¥3.30) only after status<400          │
            │    – 4xx/5xx are NEVER billed                         │
            │    billing/                                            │
            └─────────────────────────────────────────────────────┘
```

Layers 1–2 absorb network-layer abuse before it touches Fly.io. Layers
3–5 handle abuse that gets past Cloudflare (operator hits the origin
directly during debugging, edge bypass via header injection, etc.).
Layer 6 is the final cost gate.

## 3. Hard-fail invariants on boot

Defined in `api/main.py::_lifespan`. The API refuses to start if any of
these fail — preferable to silently serving compromised state.

| Invariant | What it checks | Fail mode |
| --- | --- | --- |
| **INV-04 aggregator integrity** | No banned aggregator domain (noukaweb, hojyokin-portal, biz.stayway, stayway.jp, nikkei.com, prtimes.jp, wikipedia.org) appears in `programs.source_url`. | `RuntimeError` + lifespan abort. |
| **Pepper guard (prod only)** | `AUTONOMATH_API_HASH_PEPPER` is set and is not the dev placeholder `"dev-pepper-change-me"`. | `logger.critical` + `sys.exit(1)`. |
| **INV-21 PII redaction** (continuous) | Query-telemetry log lines pass through `redact_pii` so endpoint paths and `params_shape` cannot leak T-numbers / email / 電話 even if a future endpoint forgets the contract. | Failure logged, never blocks the response. |

## 4. Pepper / salt / signing keys

| Variable | Purpose | Rotation cadence |
| --- | --- | --- |
| `API_KEY_SALT` | HMAC salt for `key_hash`, `ip_hash`, throttle bucket key. | **Rotate only on leak**. Rotating invalidates every stored `key_hash`, forcing every customer to re-issue. Document procedure: dual-salt window (read both, write new) for 7 days, then drop the old. |
| `AUTONOMATH_API_HASH_PEPPER` | Pepper for `key_hash` (defense in depth on top of salt). | Same rotation policy as `API_KEY_SALT`. Must never be the dev placeholder in prod (boot-time guard). |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signature. | Rotate on suspected leak; quarterly best-practice. Stripe makes new secret active immediately; old secret continues to verify for 24h. |
| `ADMIN_API_KEY` | Operator-only `/v1/admin/*` gate. | **Rotate quarterly**. Revoke immediately if a laptop is lost. |
| `SENTRY_DSN` | Error reporting. | Rotate only on leak (DSN is by design semi-public; project-scoped). |
| `STRIPE_SECRET_KEY` (live) | Stripe API. | Rotate annually; immediately on leak. |

Operator action items (2026-04-25):

- [ ] Confirm `flyctl secrets list -a autonomath-api` returns all of:
  `API_KEY_SALT`, `AUTONOMATH_API_HASH_PEPPER`, `STRIPE_WEBHOOK_SECRET`,
  `STRIPE_SECRET_KEY`, `ADMIN_API_KEY`, `SENTRY_DSN`.
- [ ] Confirm none of them equal a published default (compare against
  `.env.example`).
- [ ] Add a quarterly calendar reminder to rotate `ADMIN_API_KEY`.

## 5. PII handling (continuous)

- **At rest**: only `customers.email` and `subscribers.email`. Both are
  user-provided for transactional purposes (billing receipts,
  amendment alerts). No 法人番号 / 電話 / 住所.
- **In query telemetry**: the `autonomath.query` JSON log line carries
  only `endpoint` (path, redacted) + `params_shape` (keys + scalar
  metadata, never values). See `api/main.py::_emit_query_log` and
  `security/pii_redact.py`.
- **In Sentry**: `send_default_pii=False`,
  `include_local_variables=False`, `before_send=sentry_before_send`
  scrubs known-sensitive fields. Verify quarterly via Sentry → Issues
  spot-check.
- **In API responses**: `ResponseSanitizerMiddleware` strips 景表法
  banned phrases (INV-22). PII is never legitimately rendered into a
  response body, so no PII-strip middleware is needed for response.

## 6. Vulnerability disclosure

Public policy is `SECURITY.md` at the repo root. Summary:

- Email: **info@bookyou.net**
- Acknowledgement: 72 hours (JST business days)
- Fix target: 14 days for server-side issues
- No bug bounty (solo-ops; cannot triage volume)
- We will publicly credit reporters who request it

Do **not** open a GitHub issue for security-sensitive reports.

## 7. Incident response (solo-ops)

Order of operations on a confirmed incident:

1. **Contain**: revoke any affected API key via `/v1/admin/keys/revoke`.
   Rotate `ADMIN_API_KEY` if it might be affected.
2. **Communicate**: email affected customers from `info@bookyou.net`
   within 24 hours. Use the template in
   `docs/_internal/incident_email_template.md` (TODO if it doesn't
   exist yet).
3. **Patch**: hotfix on `main`, deploy via `fly deploy`. No staging
   gate during incident.
4. **Postmortem**: append to `docs/_internal/incidents.md` (private,
   excluded from mkdocs build) within 7 days. Include: cause,
   detection lag, fix, preventative invariant added.

## 8. Files referenced in this document

- `src/jpintel_mcp/api/main.py` — middleware wiring, `_lifespan` invariants
- `src/jpintel_mcp/api/middleware/rate_limit.py` — D9 burst throttle
- `src/jpintel_mcp/api/middleware/customer_cap.py` — per-key spend cap
- `src/jpintel_mcp/api/anon_limit.py` — 3 req/日 anon dep
- `src/jpintel_mcp/api/response_sanitizer.py` — INV-22 景表法 strip
- `src/jpintel_mcp/security/pii_redact.py` — INV-21 redact helper
- `cloudflare-rules.yaml` — operator WAF + RL apply manifest
- `SECURITY.md` — public vulnerability disclosure policy
