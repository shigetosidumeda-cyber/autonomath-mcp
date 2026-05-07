# R8_LIVE_API_SHAPE_2026-05-07.md

Live HTTP response-shape audit against jpcite v0.3.4 (`https://autonomath-api.fly.dev`)
on **2026-05-07**, post 5/7 hardening landing.

- Deployment ref: `01KR0AGKRFD39QZZJ10VWYZXS5`, GH_SHA `b1de8b2`
  (commit chain `83b1fb3` "fail-closed billing" → `b1de8b2` "fix(deploy)")
- Internal hypothesis framing only. Read-only HTTP GET, anonymous tier (3 req/日).
  No LLM call from auditor side.
- Auditor entered the day already at quota=0/3 (prior smoke probes consumed
  the bucket). Every direct probe today returned the **rate-limit envelope**;
  paid-path body was inspected via the `components.schemas` projection of
  the live `/v1/openapi.json` (which is itself an unmetered surface and
  responded 200).

## 1. Anonymous rate-limit envelope (live)

```
GET /v1/meta                                            HTTP/2 429
GET /v1/programs/search?q=test&limit=1                  HTTP/2 429
GET /v1/tax_rulesets/search?q=test&limit=1              HTTP/2 429
```

All three returned **byte-identical** body modulo `retry_after`:

```jsonc
{
  "code": "rate_limit_exceeded",
  "reason": "rate_limit_exceeded",
  "detail": "匿名リクエスト上限 (3/日) に達しました。…",
  "detail_en": "Anonymous rate limit exceeded (3/day). …",
  "retry_after": 37731,
  "reset_at_jst": "2026-05-08T00:00:00+09:00",
  "limit": 3,
  "resets_at": "2026-05-08T00:00:00+09:00",
  "upgrade_url":         "https://jpcite.com/upgrade.html?from=429",
  "direct_checkout_url": "https://jpcite.com/pricing.html?from=429#api-paid",
  "cta_text_ja": "API key を発行して制限を解除",
  "cta_text_en": "Get an API key to remove the limit",
  "trial_signup_url": "https://jpcite.com/?from=429#trial",
  "trial_cta_text_ja": "カードなしで試す (14 日 / 200 req)",
  "trial_cta_text_en": "Try without a card (14 days / 200 requests)",
  "trial_terms": { "duration_days": 14, "request_cap": 200, "card_required": false }
}
```

Headers (live):

```
x-anon-quota-remaining:        0
x-anon-quota-reset:            2026-05-08T00:00:00+09:00
x-anon-upgrade-url:            https://jpcite.com/upgrade.html?from=429
x-anon-direct-checkout-url:    https://jpcite.com/pricing.html?from=429#api-paid
x-anon-trial-url:              https://jpcite.com/?from=429#trial
x-envelope-version:            v1
strict-transport-security:     max-age=31536000; includeSubDomains; preload
content-security-policy:       default-src 'self'; …; frame-ancestors 'none'
x-frame-options:               DENY
x-content-type-options:        nosniff
referrer-policy:               strict-origin-when-cross-origin
permissions-policy:            geolocation=(), microphone=(), camera=()
retry-after:                   37731
vary:                          Accept, X-Envelope-Version, Accept-Encoding
```

**Pass:** matches the `_AnonRateLimitExceeded` body contract in
`src/jpintel_mcp/api/anon_limit.py` (`UPGRADE_URL_FROM_429`,
`PRICING_DIRECT_URL_FROM_429`, `TRIAL_*` constants), top-level keys not
nested under FastAPI default `{"detail": ...}`. `x-envelope-version: v1`
+ full security-header set is intact (no regression vs 5/6).

## 2. Paid-path response shape (`_billing_unit`)

Live calls 429-blocked, so verified against live OpenAPI schema
(`/v1/openapi.json`, which is unmetered). Paid-path bodies expose a stable
`_billing_unit` integer alongside payload:

- **Schema component**: `ArtifactBillingMetadata` carries
  `endpoint, unit_type, quantity, result_count, pair_count, metered,
   strict_metering, pricing_note, value_basis, audit_seal`.
- **Audit seal**: `ArtifactBillingAuditSeal` carries
  `authenticated_key_present, requested_for_metered_key,
   included_when_available,
   billing_metadata_covered_by_response_hash,
   seal_field_excluded_from_response_hash` — i.e. the seal field is itself
  excluded from the body hash so clients can still verify integrity.
- **Source-side emit sites** (15 hits, alias `_billing_unit`):
  `_response_models.py:758,808,843` (3 base wrappers),
  `intel_diff.py:672`, `intel_houjin_full.py:1029`,
  `intel.py:385,706,1619,1711`,
  `intel_path.py:675,703,760,822`,
  `intel_program_full.py:843`.
  All emit `_billing_unit: 1` per call (matches CLAUDE.md "¥3/req metered").
- **OpenAPI version on wire**: `0.3.4` → matches `pyproject.toml`.

**Pass:** paid surface still emits `_billing_unit` with the v0.3.4 schema
shape; no drift introduced by 5/7 fail-closed reinforcement.

## 3. Sensitive-tool `_disclaimer` envelope (live)

OpenAPI walk found **15 sensitive tool paths** that require
`_disclaimer`. Live invocation is 429-blocked under anon, so verified at the
schema layer:

| Path                                | Tag           | Disclaimer carrier                    |
|-------------------------------------|---------------|---------------------------------------|
| GET  /v1/tax_rulesets/search        | tax_rulesets  | `TaxRulesetSearchResponse` results[]  |
| GET  /v1/tax_rulesets/{unified_id}  | tax_rulesets  | `_disclaimer` on detail body          |
| POST /v1/tax_rulesets/evaluate      | tax_rulesets  | inline                                |
| GET  /v1/source_manifest/{program}  | source_manifest | `SourceManifestEnvelope._disclaimer` (required) |
| POST /v1/verify/answer              | verify        | inline                                |
| POST /v1/cost/preview               | cost          | `_response_models._disclaimer` alias  |
| POST /v1/funding_stack/check        | funding-stack | inline                                |
| GET  /v1/houjin/{bangou}            | houjin        | `intel_houjin_full.py:1028 body[_disclaimer]` |
| GET  /v1/me/saved_searches/{id}/results       | saved-searches | inline                  |
| GET  /v1/me/saved_searches/{id}/results.xlsx  | saved-searches | inline                  |
| GET  /v1/am/tax_incentives          | jpcite        | autonomath_disclaimer envelope        |
| GET  /v1/am/tax_rule                | jpcite        | autonomath_disclaimer envelope        |
| POST /v1/am/dd_batch                | ma_dd         | inline                                |
| POST /v1/am/dd_export               | ma_dd         | inline                                |
| POST /v1/audit/workpaper            | audit         | `_audit_seal._disclaimer`             |

`SourceManifestEnvelope` is the strictest case: schema declares
`_disclaimer` in the **required** list, so a missing disclaimer would fail
validation at emit time. That contract is intact on the live `/v1/openapi.json`.

**Pass at schema layer.** Live body verification deferred until anon quota
resets (2026-05-08 00:00 JST) or an authenticated probe is run from a
separate audit lane — internal-hypothesis framing.

## 4. 5/6 → 5/7 response-shape diff

Reviewed the 5/7 hardening commit `83b1fb3` (the one that ships the
fail-closed posture) and earlier 5/6 baseline `7ee0b08`:

| Surface                            | 5/6 baseline                  | 5/7 hardening                 |
|------------------------------------|-------------------------------|-------------------------------|
| Anon rate-limit envelope keys      | code/reason/detail/detail_en/retry_after/reset_at_jst/limit/resets_at/upgrade_url/direct_checkout_url/cta_*/trial_* | **identical** (no key add/remove) |
| Anon limit on broken backend       | fail-open (would leak free path) | **fail-closed** → 429 `rate_limit_unavailable` |
| Anon `_AnonRateLimitExceeded`      | `detail` rendered nested by FastAPI | top-level body via custom handler `anon_rate_limit_exception_handler` |
| Billing rollup on Stripe failure   | partial swallow               | narrowed exception handling + idempotency tighten |
| `deps.py` DB session injection     | broader session scope          | narrowed (defensive)          |
| `_billing_unit` alias              | `1` per metered call           | **unchanged**                 |
| `_disclaimer` envelope             | required on 15 sensitive paths | **unchanged**                 |
| OpenAPI version                    | 0.3.4                          | 0.3.4                         |
| MCP cohort runtime / manifest hold | 146 / 139                      | 146 / 139                     |
| Total OpenAPI paths                | 182                            | 182                           |

Internal hypothesis: **the 5/7 hardening only changes failure-mode shape
on the anon limit and billing rollup paths; the success-path response
contract (`_billing_unit`, `_disclaimer`, `SourceManifestEnvelope`,
`ArtifactBillingMetadata`/`ArtifactBillingAuditSeal`, security headers,
`x-envelope-version: v1`) is unchanged.** No client breakage expected on
HTTP-200 paths. 429-on-broken-backend is a new code (`rate_limit_unavailable`)
with the same outer envelope shape (top-level `code` + `reason` +
`detail`/`detail_en`) so existing clients that switch on `code ==
"rate_limit_exceeded"` need to widen to `code in {"rate_limit_exceeded",
"rate_limit_unavailable"}` if they want to distinguish the two.

## 5. Honest gaps

- **Live paid-body sample not captured today** — auditor was at anon
  quota=0/3 before the audit started. Paid-path verification is at the
  OpenAPI-schema layer, not raw response. Re-run after JST 00:00 reset
  or with an authenticated key in the next session to lift this gap.
- **Sensitive-path `_disclaimer` text not byte-verified live** — same
  cause; the per-tool string is only confirmed via source-tree grep
  (15 emit sites listed) and schema `required: ['_disclaimer']` on
  `SourceManifestEnvelope`. Live byte capture deferred.
- **Frontend / Cloudflare Pages deploy 3rd retry status** is referenced
  in `83b1fb3` but is out of scope here (this audit is API only).

## 6. Conclusion (internal hypothesis)

5/7 fail-closed reinforcement landed without altering the success-path
response contract on jpcite v0.3.4 LIVE. Anonymous rate-limit envelope
shape, paid-path `_billing_unit` carrier, and sensitive-tool
`_disclaimer` envelope are all intact at the schema layer; the headers
(`x-envelope-version: v1`, security policy set, `x-anon-*` quota series)
are emitted as expected. Recommend a re-run after JST 00:00 reset to
capture a live 200 body for `/v1/programs/search` and one sensitive path
(e.g. `/v1/source_manifest/{program_id}`) so the audit can graduate
from schema-level to body-level confirmation.
