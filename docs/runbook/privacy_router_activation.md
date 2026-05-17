---
title: Privacy router activation (APPI §31 / §33)
updated: 2026-05-12
operator_only: true
category: monitoring
---

# Privacy router activation runbook (APPI §31 / §33)

`/v1/privacy/disclosure_request` (APPI §31 個人情報開示請求) and
`/v1/privacy/deletion_request` (APPI §33 個人情報削除請求) are gated by
two independent env flags:

| Flag | Default in `fly.toml` | Effect |
| --- | --- | --- |
| `AUTONOMATH_APPI_ENABLED` | `0` | `0` → routes unmounted, every POST returns 404. `1` → routes mounted. |
| `AUTONOMATH_APPI_REQUIRE_TURNSTILE` | unset (= `1`) | When the router is enabled AND this is `1`, boot fails unless `CLOUDFLARE_TURNSTILE_SECRET` is set. Set to `0` to opt out (honor system + manual review). |
| `CLOUDFLARE_TURNSTILE_SECRET` | unset | When non-empty, every POST must carry a valid `CF-Turnstile-Token` header. When empty, `_verify_turnstile_token` short-circuits at request time. |

The privacy policy (`site/privacy.html` §9) already advertises the
**email channel** (`info@bookyou.net`) as the canonical APPI §27–§34
intake. APPI duty is therefore discharged today even with the routes
returning 404 — the boot gate is hardened against an over-claim where
the docs hint at a web form that does not exist in production.

This runbook lists three activation paths so the operator can pick
based on launch readiness without redeploying the privacy.html copy.

---

## Path A — leave routes off (current production state)

Do nothing. `fly.toml` keeps `AUTONOMATH_APPI_ENABLED = "0"`.

- `/v1/privacy/disclosure_request` → 404
- `/v1/privacy/deletion_request` → 404
- privacy.html §9 email channel handles every intake (info@bookyou.net,
  30-day SLA, manual identity verification).
- No Turnstile secret needed; boot gate satisfied.

This is the safest posture and was the launch default in v0.3.4.

---

## Path B — activate routes with Turnstile (recommended once secret is wired)

Use this once the operator has provisioned Cloudflare Turnstile and
copied the server-side secret into Fly secrets.

```bash
# 1. Stage the Turnstile secret first.
flyctl secrets set CLOUDFLARE_TURNSTILE_SECRET="<server-side secret>" \
  -a autonomath-api

# 2. Flip the APPI gate. fly.toml stays untouched in git history;
#    we only override the env in Fly's secret store.
flyctl secrets set AUTONOMATH_APPI_ENABLED="1" -a autonomath-api

# 3. Redeploy is automatic on `flyctl secrets set`. Verify:
curl -sS https://api.jpcite.com/openapi.json | jq -r '.paths | keys[]' | \
  grep '/v1/privacy/'
# Expect: /v1/privacy/deletion_request and /v1/privacy/disclosure_request

# 4. Smoke a 401 (no token) and a 201 (good token) from a browser.
```

Boot gate behaviour: passes. Both routes mounted. Turnstile required on
every POST.

---

## Path C — activate routes WITHOUT Turnstile (honor system fallback)

Use this when the operator wants the routes live but has not yet wired
Turnstile. APPI §31/§33 receive a handful of requests per year; the
upstream anonymous IP rate cap (3 req/day per IP) and the manual review
SLA on the operator side give enough abuse headroom for a
zero-customer-call ramp.

```bash
# 1. Set the escape hatch.
flyctl secrets set AUTONOMATH_APPI_REQUIRE_TURNSTILE="0" -a autonomath-api

# 2. Flip the APPI gate.
flyctl secrets set AUTONOMATH_APPI_ENABLED="1" -a autonomath-api

# 3. Verify routes are live (same probe as Path B step 3).
```

Boot gate behaviour: passes — `_assert_production_secrets()` skips the
Turnstile check when `AUTONOMATH_APPI_REQUIRE_TURNSTILE=0`. At request
time, `_verify_turnstile_token` returns immediately because
`CLOUDFLARE_TURNSTILE_SECRET` is empty. Every POST that satisfies the
Pydantic schema lands in `appi_disclosure_requests` /
`appi_deletion_requests` with `status='pending'`, the operator inbox
(`info@bookyou.net`) receives the Postmark notification, and the
requester receives the receipt acknowledgement.

To upgrade Path C → Path B later: provision Turnstile, set
`CLOUDFLARE_TURNSTILE_SECRET`, then `flyctl secrets unset
AUTONOMATH_APPI_REQUIRE_TURNSTILE -a autonomath-api`. The boot gate
falls back to its default-strict behaviour without requiring code
changes.

---

## Rollback

Either path rolls back identically:

```bash
flyctl secrets set AUTONOMATH_APPI_ENABLED="0" -a autonomath-api
```

Routes return 404 again; existing rows in `appi_*_requests` stay
durable for the operator-side cron sweep
(`status='pending'` query in the runbook
`docs/_internal/privacy_appi_31.md`).

---

## Verification matrix

| Mode | `AUTONOMATH_APPI_ENABLED` | `AUTONOMATH_APPI_REQUIRE_TURNSTILE` | `CLOUDFLARE_TURNSTILE_SECRET` | Boot | Route status | POST behaviour |
| --- | --- | --- | --- | --- | --- | --- |
| A (off) | `0` | any | any | OK | unmounted | 404 |
| B (with Turnstile) | `1` | unset / `1` | set | OK | mounted | 401 if header missing/bad, else 201 |
| C (honor system) | `1` | `0` | unset | OK | mounted | 201 (Pydantic schema only) |
| Misconfigured | `1` | unset / `1` | unset | **FAIL** | n/a | n/a |

The misconfigured row is the boot gate's job — it forces the operator
to make an explicit Path B vs Path C decision instead of silently
mounting routes that 401 every legitimate caller.

---

## What does NOT change

- `fly.toml` — never touched by this runbook. Operator drives both
  flags via `flyctl secrets set`. The committed file keeps
  `AUTONOMATH_APPI_ENABLED = "0"` as the safe default for fresh
  environments and CI.
- `site/privacy.html` §9 copy — the email channel
  (`info@bookyou.net`) remains the canonical intake regardless of
  whether the routes are live. The web form is an additional
  convenience surface, not a replacement.
- `docs/_internal/privacy_appi_31.md` — operator-side runbook for
  identity verification, 14/30-day SLA, and the §31-2 / §33-1
  refusal codes. Not affected by activation mode.

---

## Test coverage

`tests/test_boot_gate.py`:

- `test_prod_fails_on_missing_turnstile_secret_when_appi_enabled` —
  Misconfigured row above.
- `test_prod_allows_missing_turnstile_secret_when_appi_disabled` —
  Path A row.
- `test_prod_allows_missing_turnstile_secret_when_require_turnstile_off`
  — Path C row (escape hatch).

`tests/test_appi_turnstile.py` and
`tests/test_appi_deletion_turnstile.py` cover the request-time
short-circuit on empty secret.
