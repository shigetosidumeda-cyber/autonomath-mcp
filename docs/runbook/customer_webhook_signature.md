---
title: Customer webhook signature format
updated: 2026-05-16
operator_only: true
category: secret
---

# Customer webhook signature format

Reference for customers integrating jpcite outbound webhooks
(`/v1/me/webhooks`). Covers the **current v1 format**, the **planned
rotation path** to a Stripe-style timestamped envelope, and **verification
code samples** for Python, Node.js, and Ruby.

This page documents the *contract*. Implementation owners:

- `src/jpintel_mcp/api/customer_webhooks.py` — `compute_signature` +
  `X-Jpcite-Signature` header on the test-delivery surface.
- `scripts/cron/dispatch_webhooks.py` — same `compute_signature` import,
  same header, fan-out cron.

Do not edit those files in lockstep with this doc; the source of truth
for the wire format is the test suite at
`tests/test_customer_webhooks_signature_format.py`.

---

## 1. Current v1 format

Every webhook POST from jpcite carries the following request headers:

```
Content-Type: application/json; charset=utf-8
User-Agent:   jpcite-webhook/1.0
X-Jpcite-Signature: hmac-sha256=<64 lowercase hex chars>
X-Jpcite-Event:     <event_type, e.g. program.amended>
X-Jpcite-Webhook-Id: <numeric id>
```

Legacy aliases `X-Zeimu-Signature` / `X-Zeimu-Event` /
`X-Zeimu-Webhook-Id` are emitted alongside the `X-Jpcite-*` set for
customers who integrated before the brand rename. They carry an
identical value to the `X-Jpcite-*` header and will remain in place
until the next major version bump.

### Signature input

The signed input is the **raw request body** as sent on the wire (no
canonicalisation, no whitespace stripping):

```
sig = HMAC-SHA256(secret, raw_body_bytes)
header_value = "hmac-sha256=" + lowercase_hex(sig)
```

The `secret` is the `whsec_...`-prefixed string returned **exactly once**
in the response to `POST /v1/me/webhooks`. The customer is responsible
for storing it; jpcite cannot retrieve it later.

### Verification rule

```python
import hmac

expected_hex = hmac.new(secret.encode("utf-8"),
                       raw_body_bytes,
                       "sha256").hexdigest()
presented   = header.removeprefix("hmac-sha256=")
ok = hmac.compare_digest(expected_hex, presented)
```

`hmac.compare_digest` is mandatory — string equality is a timing-oracle.

### Parser tolerance

The header parser on the customer side **MUST**:

- Strip leading / trailing whitespace from the header value.
- Treat the `hmac-sha256=` prefix as case-insensitive
  (`HMAC-SHA256=`, `Hmac-Sha256=` are all valid).
- Reject any value that does not produce exactly 64 hex characters after
  stripping the prefix.

The dispatcher always emits the lowercase form; case-insensitive parsing
is forward-compat insurance only.

---

## 2. Forward-compatible rotation: Stripe-style `t=...,v1=...`

A future jpcite release will rotate the header into a Stripe-compatible
multi-element envelope. The planned wire format is:

```
X-Jpcite-Signature: t=<unix_epoch_seconds>,v1=<64 hex chars>
```

With multiple scheme tokens permitted for grace-period rotation:

```
X-Jpcite-Signature: t=1748736000,v1=<hex>,v0=hmac-sha256=<legacy hex>
```

Rotation plan (no concrete date — gated by customer integration breadth):

1. **Phase 0 — today.** `hmac-sha256=<hex>` only. This doc + test
   `test_customer_webhooks_signature_format.py` pin the format.
2. **Phase 1 — dual emit.** Dispatcher writes
   `t=<unix>,v1=<hex>,v0=hmac-sha256=<hex>` in a single header. Existing
   customer code that splits on `hmac-sha256=` keeps working unchanged.
3. **Phase 2 — v1 only.** The legacy `v0=hmac-sha256=...` element is
   dropped. Customers who upgraded in Phase 1 see no change; those who
   didn't see a verification failure and pull this doc.

### v1 verification rule

```
elements = header.split(",")               # ["t=1748736000", "v1=<hex>"]
parts    = {k: v for k, v in (e.split("=", 1) for e in elements)}
t        = int(parts["t"])
v1       = parts["v1"]

# Timestamp tolerance: reject if outside ±5 minutes of now (replay defence).
if abs(now_unix - t) > 300:
    raise InvalidSignature("timestamp out of tolerance")

# Signed input is "<t>.<raw_body>".
signed_payload = f"{t}.".encode("utf-8") + raw_body_bytes
expected       = hmac.new(secret.encode("utf-8"),
                          signed_payload, "sha256").hexdigest()
ok = hmac.compare_digest(expected, v1)
```

The timestamp tolerance is the only behavioural difference from v1: the
signature input changes from `body` to `"<unix>.<body>"`, and replay
attempts older than 5 minutes are rejected even on a matching MAC.

### How to ship verification code that survives the rotation

Customers should branch on the presence of `t=` in the header value:

```python
def verify(header: str, raw_body: bytes, secret: str, now_unix: int) -> bool:
    header = header.strip()
    if header.lower().startswith("hmac-sha256="):
        # v1 (current) — body-only HMAC.
        presented = header.split("=", 1)[1].strip()
        expected  = hmac.new(secret.encode(), raw_body,
                             "sha256").hexdigest()
        return hmac.compare_digest(expected, presented)
    if "t=" in header and "v1=" in header:
        # v2 (future) — timestamped envelope.
        parts = dict(kv.split("=", 1) for kv in header.split(","))
        t  = int(parts["t"])
        v1 = parts["v1"]
        if abs(now_unix - t) > 300:
            return False
        signed = f"{t}.".encode() + raw_body
        expected = hmac.new(secret.encode(), signed,
                            "sha256").hexdigest()
        return hmac.compare_digest(expected, v1)
    return False
```

Code shaped like the snippet above will keep verifying successfully
across Phase 0 → Phase 1 → Phase 2 without any customer-side redeploy.

---

## 3. Verification code samples

### Python (FastAPI / Flask / pure stdlib)

```python
import hmac
from hashlib import sha256

def verify_jpcite_signature(
    header: str,
    raw_body: bytes,
    secret: str,
    now_unix: int | None = None,
) -> bool:
    """Verify an X-Jpcite-Signature header. v1 + v2 forward-compat."""
    if not header:
        return False
    header = header.strip()
    # v1 (current). Case-insensitive prefix per parser-tolerance rule.
    if header.lower().startswith("hmac-sha256="):
        presented = header.split("=", 1)[1].strip()
        expected = hmac.new(secret.encode("utf-8"), raw_body, sha256).hexdigest()
        return hmac.compare_digest(expected.lower(), presented.lower())
    # v2 (future). Reject when timestamp drifts > 5 min.
    if "t=" in header and "v1=" in header:
        import time
        parts = dict(kv.split("=", 1) for kv in header.split(","))
        t = int(parts["t"])
        if abs((now_unix or int(time.time())) - t) > 300:
            return False
        signed = f"{t}.".encode("utf-8") + raw_body
        expected = hmac.new(secret.encode("utf-8"), signed, sha256).hexdigest()
        return hmac.compare_digest(expected.lower(), parts["v1"].lower())
    return False
```

### Node.js (Express / Fastify)

```javascript
const crypto = require("crypto");

function verifyJpciteSignature(header, rawBody, secret, nowUnix = null) {
  if (!header) return false;
  const h = header.trim();
  // v1 (current).
  if (h.toLowerCase().startsWith("hmac-sha256=")) {
    const presented = h.split("=", 2)[1].trim();
    const expected = crypto
      .createHmac("sha256", secret)
      .update(rawBody)
      .digest("hex");
    return crypto.timingSafeEqual(
      Buffer.from(expected, "hex"),
      Buffer.from(presented, "hex"),
    );
  }
  // v2 (future).
  if (h.includes("t=") && h.includes("v1=")) {
    const parts = Object.fromEntries(h.split(",").map((kv) => kv.split("=", 2)));
    const t = parseInt(parts.t, 10);
    const now = nowUnix ?? Math.floor(Date.now() / 1000);
    if (Math.abs(now - t) > 300) return false;
    const signed = Buffer.concat([Buffer.from(`${t}.`), rawBody]);
    const expected = crypto
      .createHmac("sha256", secret)
      .update(signed)
      .digest("hex");
    return crypto.timingSafeEqual(
      Buffer.from(expected, "hex"),
      Buffer.from(parts.v1, "hex"),
    );
  }
  return false;
}
```

Note: with Express, configure the body parser to expose the raw bytes
(e.g. `express.raw({ type: "application/json" })`) or HMAC verification
will fail against a re-serialised JSON body.

### Ruby (Rails / Sinatra)

```ruby
require "openssl"

def verify_jpcite_signature(header, raw_body, secret, now_unix: nil)
  return false if header.nil? || header.empty?
  h = header.strip
  # v1 (current).
  if h.downcase.start_with?("hmac-sha256=")
    presented = h.split("=", 2).last.strip
    expected = OpenSSL::HMAC.hexdigest("sha256", secret, raw_body)
    return OpenSSL.fixed_length_secure_compare(expected.downcase, presented.downcase)
  end
  # v2 (future).
  if h.include?("t=") && h.include?("v1=")
    parts = h.split(",").map { |kv| kv.split("=", 2) }.to_h
    t = parts["t"].to_i
    now = now_unix || Time.now.to_i
    return false if (now - t).abs > 300
    signed = "#{t}.".dup.force_encoding("ASCII-8BIT") + raw_body
    expected = OpenSSL::HMAC.hexdigest("sha256", secret, signed)
    return OpenSSL.fixed_length_secure_compare(expected.downcase, parts["v1"].downcase)
  end
  false
end
```

Rails: read the raw body via `request.raw_post`. ActionController's
`params` will re-serialise the JSON and break HMAC.

---

## 4. Operational notes

- **Replay defence**: v1 has none. Customers that need it MUST persist
  the `X-Jpcite-Webhook-Id` + the event payload's
  `data.event_id` (or `data.diff_id` / `data.case_id` per event type)
  and reject duplicate processing. v2's `t=` element will add a
  protocol-level 5-minute window.
- **Constant-time comparison**: `hmac.compare_digest` (Python),
  `crypto.timingSafeEqual` (Node), `OpenSSL.fixed_length_secure_compare`
  (Ruby). Never use `==` on the hex strings.
- **Raw body**: HMAC is computed over the byte sequence transmitted on
  the wire. Frameworks that pre-parse JSON and hand you a dict will give
  you a re-serialised body that does not match. Always read the raw
  bytes before HMAC verification.
- **Secret rotation**: today's flow is DELETE + POST a new webhook to
  receive a fresh `whsec_...` secret. The PATCH endpoint does NOT
  rotate the secret. v2 may grow an in-place rotation path; until then,
  budget brief downtime.

## 5. Where the contract is pinned

- Wire format assertions:
  `tests/test_customer_webhooks_signature_format.py`.
- Dispatcher signing call site:
  `scripts/cron/dispatch_webhooks.py::_deliver_one`.
- Test-delivery signing call site:
  `src/jpintel_mcp/api/customer_webhooks.py::test_delivery`.
- OpenAPI schema (auto-generated, do not hand-edit):
  `docs/openapi/v1.json`.
