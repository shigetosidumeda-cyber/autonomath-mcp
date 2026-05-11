"""Per-key / per-IP token-bucket rate limit (D9, 2026-04-25).

Purpose
-------
Defend the API against burst abuse / DDoS / scraping below the threshold
where Cloudflare WAF rate-limit rules engage. Cloudflare's edge limits are
*coarse* (1000 req/min global on /v1/*, 500 req/min on /v1/programs/search
— see ``cloudflare-rules.yaml``); per-caller throttling is finer-grained
and runs in-process so it works in dev / staging / behind any proxy chain.

This module is **not** a cost control. ¥3/req metered pricing is unchanged
(memory: ``project_autonomath_business_model``). The 10 req/sec cap on a
paid key allows up to ~600 req/min = ¥1,800/min, which a customer who is
spending several million yen / month is well within. The throttle exists
to prevent a runaway agent loop from turning into accidental DoS.

Tuning
------
* **Paid keys**: 10 req/sec, burst 20. Bucket fills at 10 tokens/sec.
* **Auth-shaped traffic per IP**: 20 req/sec, burst 40. This additional
  guard catches invalid-key spray where each bogus key would otherwise
  create a fresh paid-key bucket before the DB auth layer rejects it.
* **Anonymous IPs**: 1 req/sec, burst 5. Bucket fills at 1 token/sec.
* **Whitelist**: ``/healthz`` ``/readyz`` ``/v1/billing/webhook`` and the
  preflight ``OPTIONS`` are skipped — same posture as the anon-quota dep.
* **Process-local**: a ``dict[str, _Bucket]`` per worker. Multi-worker
  drift is bounded by ``workers * burst`` and is acceptable: a single
  worker hitting 10 req/sec is the harm we care about, not 4 workers
  serving 4 × 10 = 40 req/sec aggregate (which is well below the WAF
  cap of 1000 req/min global). Sharing across workers would require
  Redis and is deferred until QPS scaling justifies it.

Anonymous quota interaction
---------------------------
The 3 req/日 anonymous IP quota is enforced separately by
``api/anon_limit.py::enforce_anon_ip_limit`` as a router-dep (sits inside
the handler, so it runs *after* this middleware). Order is intentional:

1. **This middleware** rejects rapid bursts before the DB increment runs,
   so a malicious client cannot inflate ``anon_rate_limit.call_count``
   beyond the monthly quota by ignoring 429s.
2. The anon-month dep then increments the bucket only for requests that
   passed the burst gate — keeping the monthly quota honest.

Identity extraction
-------------------
* ``X-API-Key`` / ``Authorization: Bearer …`` → bucket keyed on
  ``HMAC(api_key_salt, raw_key)`` so we never log raw keys. Falls back to
  IP-based bucket if the header value is empty after strip.
* No header → bucket keyed on the canonicalised client IP (Fly-Client-IP
  > X-Forwarded-For first hop > request.client.host), normalised via the
  same ``_normalize_ip_to_prefix`` rule as ``anon_limit`` (IPv6 → /64).

Fail-open posture
-----------------
Any exception (clock skew, hash failure, weird request shape) returns
``call_next`` immediately. A broken throttle MUST NOT become a self-DoS.
Over-serving is strictly better than 500-on-every-call.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from jpintel_mcp.config import settings

if TYPE_CHECKING:
    from fastapi import Request
    from starlette.responses import Response

logger = logging.getLogger("jpintel.rate_limit")

# Per-key throttle. 10 req/s sustained, burst 20 on a fresh bucket.
# 600 req/min = ¥1,800 — well within typical paid usage envelopes.
_PAID_RATE_PER_SEC: float = 10.0
_PAID_BURST: float = 20.0

# Per-IP guard for requests that carry an auth-shaped header. Valid paid
# callers still get the per-key bucket above; this second bucket prevents
# rotated invalid keys from bypassing the anonymous IP burst and hammering
# the auth DB lookup path. Kept higher than the paid per-key limit so one
# normal customer key is governed by the key bucket, not the IP guard.
_AUTH_IP_RATE_PER_SEC: float = 20.0
_AUTH_IP_BURST: float = 40.0

# Per-anon-IP throttle. 1 req/s, burst 5. The 3 req/日 cap (anon_limit.py)
# is the long-term ceiling; this is just the per-second guard.
_ANON_RATE_PER_SEC: float = 1.0
_ANON_BURST: float = 5.0

# Paths that bypass throttling entirely:
#   /healthz, /readyz       — Fly liveness/readiness probes
#   /v1/billing/webhook     — Stripe webhooks (high-rate at payment events)
#   OPTIONS                 — CORS preflight (must always succeed quickly)
_WHITELIST_PATHS: frozenset[str] = frozenset(
    {
        "/healthz",
        "/readyz",
        "/v1/billing/webhook",
    }
)


@dataclass
class _Bucket:
    """Token bucket. ``tokens`` is the current credit, ``last`` the
    monotonic timestamp of the last refill. Refill is computed lazily on
    each ``take`` call rather than via a timer, so an idle bucket costs no
    CPU and a spike refills exactly the elapsed quanta.
    """

    tokens: float
    last: float
    rate_per_sec: float
    burst: float


# Process-local bucket store. Keyed by:
#   "k:<hex16>"   for an authed key (first 16 hex of HMAC(salt, raw_key))
#   "auth-ip:<addr>" for any request carrying an auth header
#   "ip:<addr>"   for an anon caller (already normalised to /32 or /64)
_buckets: dict[str, _Bucket] = {}
_buckets_lock = threading.Lock()


def _reset_rate_limit_buckets() -> None:
    """Test helper: clear the bucket store (used by ``tests/test_rate_limit``)."""
    with _buckets_lock:
        _buckets.clear()


def _normalize_ip_to_prefix(ip: str) -> str:
    """Match ``anon_limit._normalize_ip_to_prefix`` so the buckets and the
    monthly quota use the same identity key — otherwise an IPv6 client
    would burst-throttle on /128 here but quota on /64 there.
    """
    import ipaddress

    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(addr, ipaddress.IPv4Address):
        return str(addr)
    try:
        net = ipaddress.IPv6Network((addr, 64), strict=False)
        return str(net.network_address)
    except ValueError:
        return ip


def _client_ip(request: Request) -> str:
    """Same priority order as ``anon_limit._client_ip``."""
    fly_ip = request.headers.get("fly-client-ip")
    if fly_ip:
        return fly_ip.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _extract_raw_key(request: Request) -> str | None:
    raw = request.headers.get("x-api-key")
    if raw:
        return raw.strip() or None
    auth = request.headers.get("authorization")
    if auth:
        parts = auth.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip() or None
    return None


def _bucket_key_for(request: Request) -> tuple[str, float, float]:
    """Return ``(key, rate, burst)`` for this request.

    Identity precedence: authed key (key_hash prefix) > IP address. We
    deliberately use the *prefix* of the HMAC rather than the full hex
    digest so the bucket store stays compact; collision risk on 64 bits
    of identity space is negligible at the active-key counts we operate
    at (< 10k authed keys).
    """
    raw_key = _extract_raw_key(request)
    if raw_key is not None:
        key_hash = hmac.new(
            settings.api_key_salt.encode("utf-8"),
            raw_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:16]
        return f"k:{key_hash}", _PAID_RATE_PER_SEC, _PAID_BURST

    ip = _client_ip(request)
    norm = _normalize_ip_to_prefix(ip)
    return f"ip:{norm}", _ANON_RATE_PER_SEC, _ANON_BURST


def _auth_ip_bucket_key_for(request: Request) -> str:
    ip = _client_ip(request)
    norm = _normalize_ip_to_prefix(ip)
    return f"auth-ip:{norm}"


def _take_token(bucket_key: str, rate: float, burst: float) -> tuple[bool, float]:
    """Return ``(allowed, retry_after_seconds)``.

    Atomic under ``_buckets_lock`` — a single in-process bucket so the
    classic test-and-set race (two threads each see 1 token, both decrement
    to 0, both proceed) cannot happen. Lock hold time is microseconds; this
    is not a contention bottleneck under realistic load.
    """
    now = time.monotonic()
    with _buckets_lock:
        b = _buckets.get(bucket_key)
        if b is None:
            b = _Bucket(tokens=burst, last=now, rate_per_sec=rate, burst=burst)
            _buckets[bucket_key] = b
        else:
            # Refill: add (elapsed * rate) tokens up to ``burst`` ceiling.
            # If the burst/rate config changed (we use one global value
            # per identity-class so this only happens at module reload in
            # tests), reseat the bucket's params to avoid permanent drift.
            elapsed = max(0.0, now - b.last)
            b.tokens = min(burst, b.tokens + elapsed * rate)
            b.last = now
            b.rate_per_sec = rate
            b.burst = burst

        if b.tokens >= 1.0:
            b.tokens -= 1.0
            return True, 0.0

        # Not enough credit. Compute when the bucket will next have ≥1
        # token: (1 - tokens) / rate, rounded up to whole seconds for
        # the Retry-After header (RFC 7231 expresses it as an integer).
        deficit = 1.0 - b.tokens
        retry_after = max(1.0, deficit / rate) if rate > 0 else 60.0
        return False, retry_after


def _build_throttled_body(retry_after_s: int, *, bucket: str) -> dict[str, Any]:
    """Render the 429 body. ``bucket`` is opaque ('paid' or 'anon-ip') so
    a caller can tell which limit they hit without revealing the raw
    key-hash or IP.

    The body matches the canonical envelope used by ``_error_envelope.py``:
    ``{code, message, retry_after, docs_url, bucket}``. Agent-facing
    callers branch on ``code`` rather than parsing ``message`` (Wave 18 AX
    Recovery step contract).
    """
    return {
        "error": {
            "code": "rate_limit_exceeded",
            "message": ("リクエストが多すぎます。少し待ってから再試行してください。"),
            "message_en": ("Too many requests. Please slow down and retry."),
            "retry_after": retry_after_s,
            "docs_url": "https://jpcite.com/docs/errors.html#rate_limit_exceeded",
            "bucket": bucket,
        }
    }


def _build_rate_limit_headers(
    *,
    bucket: str,
    limit: int,
    remaining: int,
    retry_after: int | None,
) -> dict[str, str]:
    """Return the RFC-7231-style rate-limit response headers.

    Includes both the per-bucket ``X-RateLimit-Limit`` /
    ``X-RateLimit-Remaining`` / ``X-RateLimit-Reset`` triplet AND a
    ``Retry-After`` header when ``retry_after`` is set (only on 429
    refusals). Stamped on every response by the dispatch path so a
    customer agent can pace itself without ever triggering the 429.

    The ``Reset`` value is a Unix epoch (seconds) representing the next
    full second when the bucket is guaranteed to have at least one
    fresh token. Cheap heuristic: ``now + max(1, retry_after_or_60)``.
    """
    import time as _t

    headers: dict[str, str] = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, remaining)),
        "X-RateLimit-Bucket": bucket,
    }
    # Reset window: when retry_after is known use it, else conservative 60s.
    reset_in = retry_after if retry_after else 60
    headers["X-RateLimit-Reset"] = str(int(_t.time()) + max(1, int(reset_in)))
    if retry_after is not None:
        headers["Retry-After"] = str(int(retry_after))
    return headers


def _is_disabled() -> bool:
    """Return True iff the throttle is globally disabled.

    Driven by ``RATE_LIMIT_BURST_DISABLED=1`` so the test suite can opt
    out without affecting prod. The env var is read on every request
    (cheap; ``os.environ`` is a dict) so monkeypatch flips work without
    a module reload. Default off in prod.
    """
    return os.environ.get("RATE_LIMIT_BURST_DISABLED") == "1"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket throttle for the AutonoMath REST API.

    Wired in :mod:`jpintel_mcp.api.main` after request-id binding so 429s
    carry an ``x-request-id`` header but before the customer-cap and
    telemetry middlewares. The cap middleware never runs for a request
    rejected here, which is desired: a 429 is not a billable surface and
    must not appear in usage_events at all.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Whitelist: never throttle health probes, Stripe webhooks, or
        # CORS preflight. The Stripe webhook in particular sees bursts at
        # batch-charge time that would otherwise trip the anon-IP bucket
        # (Stripe rotates IPs but each batch hits within < 1s).
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path in _WHITELIST_PATHS:
            return await call_next(request)
        if _is_disabled():
            return await call_next(request)

        has_auth_header = _extract_raw_key(request) is not None
        if has_auth_header:
            auth_ip_key = _auth_ip_bucket_key_for(request)
            try:
                auth_ip_allowed, auth_ip_retry_after_s = _take_token(
                    auth_ip_key, _AUTH_IP_RATE_PER_SEC, _AUTH_IP_BURST
                )
            except Exception:  # pragma: no cover — defensive fail-open
                logger.exception("rate_limit_auth_ip_take_failed")
                return await call_next(request)
            if not auth_ip_allowed:
                ra_int = max(1, int(auth_ip_retry_after_s + 0.999))
                return JSONResponse(
                    status_code=429,
                    content=_build_throttled_body(ra_int, bucket="auth-ip"),
                    headers=_build_rate_limit_headers(
                        bucket="auth-ip",
                        limit=int(_AUTH_IP_BURST),
                        remaining=0,
                        retry_after=ra_int,
                    ),
                )

        try:
            bucket_key, rate, burst = _bucket_key_for(request)
        except Exception:  # pragma: no cover — defensive fail-open
            logger.exception("rate_limit_identity_failed")
            return await call_next(request)

        try:
            allowed, retry_after_s = _take_token(bucket_key, rate, burst)
        except Exception:  # pragma: no cover — defensive fail-open
            logger.exception("rate_limit_take_failed")
            return await call_next(request)

        bucket_label = "paid" if bucket_key.startswith("k:") else "anon-ip"

        if allowed:
            # Stamp X-RateLimit-Limit / X-RateLimit-Remaining /
            # X-RateLimit-Reset on the success path so customer agents
            # can pace themselves WITHOUT triggering the 429 — the AX
            # Access pillar (Biilmann 4-pillar) requires these headers
            # on every response, not just the throttled one.
            response = await call_next(request)
            with _buckets_lock:
                b = _buckets.get(bucket_key)
                remaining = int(b.tokens) if b is not None else int(burst)
            for k, v in _build_rate_limit_headers(
                bucket=bucket_label,
                limit=int(burst),
                remaining=max(0, remaining),
                retry_after=None,
            ).items():
                response.headers.setdefault(k, v)
            return response

        ra_int = max(1, int(retry_after_s + 0.999))
        return JSONResponse(
            status_code=429,
            content=_build_throttled_body(ra_int, bucket=bucket_label),
            headers=_build_rate_limit_headers(
                bucket=bucket_label,
                limit=int(burst),
                remaining=0,
                retry_after=ra_int,
            ),
        )


__all__ = [
    "RateLimitMiddleware",
    "_reset_rate_limit_buckets",
]
