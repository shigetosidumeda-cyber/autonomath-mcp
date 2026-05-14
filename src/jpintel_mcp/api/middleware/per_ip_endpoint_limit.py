"""Per-IP per-endpoint per-minute rate limit (P0 abuse defence, 2026-04-25).

Background
----------
Pre-launch audit (a7388ccfd9ed7fb8c) flagged that a single AI agent
looping ``/v1/programs/search`` with bad pagination — or a botnet
spraying the same endpoint at 1000 RPS — would saturate the SQLite
file-lock on the single Tokyo Fly box and 503 every other audience.
The existing ``RateLimitMiddleware`` (``rate_limit.py``) is a 1-second
burst gate (1 req/s anon, 10 req/s paid) which is the right *short*
window. This module adds the complementary *long* window: a per-IP,
per-endpoint sliding-minute cap aimed at heavy / financial endpoints.

Limits (all per-IP, per-minute)
-------------------------------
* **Heavy search endpoints** — 30 req/min per anonymous IP, 300 req/min
  per API key:
  - ``GET /v1/programs/search``
  - ``GET /v1/case_studies/search``
* **Read-only single-record endpoints** — 60 req/min per anonymous IP,
  600 req/min per API key:
  - ``GET /v1/programs/{id}``
  - ``GET /v1/case_studies/{id}``
* **Financial endpoints** — 10 req/min per anonymous IP, 30 req/min per
  API key:
  - ``POST /v1/checkout/start``
  - ``POST /v1/me/billing-portal``
  - ``POST /v1/billing/checkout``
  - ``POST /v1/billing/portal``

Anything not in the table runs unthrottled here (the burst middleware
+ anon monthly quota still apply).

Implementation
--------------
Sliding-window counter with a fixed 60-second bucket. Each (ip, rule)
pair gets a deque of request timestamps; on each request we evict
timestamps older than the window and count what's left. O(1) amortised.

State is process-local (one ``dict`` per worker). Multi-worker drift
is bounded by ``workers * cap``. We accept that — sharing state across
workers needs Redis and is deferred until QPS scaling justifies it.

Identity is the canonicalised client IP (signed edge XFF > Fly-Client-IP
> request.client.host), normalised to /64 for IPv6 to match
``anon_limit`` and ``rate_limit``. API-key callers use a keyed bucket so
one corporate NAT or agent platform is not capped at the anonymous IP
limit; they remain throttled by the per-key paid cap.

Fail-open posture: any internal error returns ``call_next`` immediately.
A broken throttle MUST NOT become self-DoS.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

if TYPE_CHECKING:
    from fastapi import Request
    from starlette.responses import Response

logger = logging.getLogger("jpintel.per_ip_endpoint_limit")


@dataclass(frozen=True)
class _Rule:
    """One bucket-spec: ``method`` + ``path_pattern`` (compiled regex) +
    ``cap`` per minute. ``paid_cap`` is used when a plausible API key is
    present. ``label`` is the bucket key fragment used to keep separate
    counters for endpoints that share an IP/key.
    """

    label: str
    method: str
    path_re: re.Pattern[str]
    cap: int
    paid_cap: int | None = None


# Window length in seconds. 60s gives "30 req/min" the obvious meaning.
_WINDOW_S: float = 60.0


# Compiled rule list. Order matters: the first match wins.
# Patterns are anchored with ``$`` so a longer path doesn't accidentally
# inherit a shorter rule's cap.
_RULES: tuple[_Rule, ...] = (
    # Heavy search — 30 req/min per IP.
    _Rule(
        label="search_programs",
        method="GET",
        path_re=re.compile(r"^/v1/programs/search/?$"),
        cap=30,
        paid_cap=300,
    ),
    _Rule(
        label="search_case_studies",
        method="GET",
        path_re=re.compile(r"^/v1/case_studies/search/?$"),
        cap=30,
        paid_cap=300,
    ),
    # Financial — 10 req/min per IP. Two path families because both
    # ``/v1/checkout/start`` and ``/v1/billing/checkout`` exist as
    # legacy / current entry points.
    _Rule(
        label="checkout_start",
        method="POST",
        path_re=re.compile(r"^/v1/checkout/start/?$"),
        cap=10,
        paid_cap=30,
    ),
    _Rule(
        label="billing_checkout",
        method="POST",
        path_re=re.compile(r"^/v1/billing/checkout/?$"),
        cap=10,
        paid_cap=30,
    ),
    _Rule(
        label="billing_portal",
        method="POST",
        path_re=re.compile(r"^/v1/(?:me/)?billing[-_]portal/?$"),
        cap=10,
        paid_cap=30,
    ),
    # Read-only single-record endpoints — 60 req/min per IP.
    # Matches /v1/programs/<anything-without-slash>, but the static
    # /search subpath is matched by an earlier rule so it wins.
    _Rule(
        label="single_program",
        method="GET",
        path_re=re.compile(r"^/v1/programs/(?!search)[^/]+/?$"),
        cap=60,
        paid_cap=600,
    ),
    _Rule(
        label="single_case_study",
        method="GET",
        path_re=re.compile(r"^/v1/case_studies/(?!search)[^/]+/?$"),
        cap=60,
        paid_cap=600,
    ),
)


_buckets: dict[str, deque[float]] = {}
_buckets_lock = threading.Lock()


def _reset_per_ip_endpoint_buckets() -> None:
    """Test helper: clear the bucket store."""
    with _buckets_lock:
        _buckets.clear()


def _normalize_ip_to_prefix(ip: str) -> str:
    """Match ``anon_limit._normalize_ip_to_prefix`` so all three layers
    (monthly quota, burst gate, this) use the same identity key."""
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
    signed_xff = _signed_edge_forwarded_for(request)
    if signed_xff:
        return signed_xff
    fly_ip = request.headers.get("fly-client-ip")
    if fly_ip:
        return fly_ip.strip()
    if request.client:
        return request.client.host
    return "unknown"


def _signed_edge_forwarded_for(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for", "").strip()
    if not xff:
        return None
    caller_ip = xff.split(",", 1)[0].strip()
    if not caller_ip:
        return None
    try:
        from jpintel_mcp.api.middleware.edge_header_sanitization import (
            _edge_auth_secret,
            _verify_signed_edge_header,
        )
    except Exception:
        return None
    secret = _edge_auth_secret()
    token = request.headers.get("x-edge-auth", "")
    if not secret or not token or not _verify_signed_edge_header(
        token, secret, caller_ip=caller_ip
    ):
        return None
    return caller_ip


def _match_rule(method: str, path: str) -> _Rule | None:
    for rule in _RULES:
        if rule.method != method:
            continue
        if rule.path_re.match(path):
            return rule
    return None


def _plausible_api_key(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip()
    if not key:
        return None
    # Do not validate here; auth dependencies do that later. This just
    # keeps anonymous traffic from opting into paid buckets with junk.
    if not (key.startswith("am_") or key.startswith("jpcite_") or key.startswith("jc_")):
        return None
    if len(key) < 12:
        return None
    return key


def _candidate_api_key(request: Request) -> str | None:
    raw = request.headers.get("x-api-key")
    if not raw:
        authorization = request.headers.get("authorization")
        if authorization:
            parts = authorization.split(None, 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                raw = parts[1].strip()
    return _plausible_api_key(raw)


def _bucket_identity_and_cap(request: Request, rule: _Rule) -> tuple[str, int, str]:
    api_key = _candidate_api_key(request)
    if api_key and rule.paid_cap:
        digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
        return f"key:{digest}", rule.paid_cap, "per-key"
    ip = _normalize_ip_to_prefix(_client_ip(request))
    return f"ip:{ip}", rule.cap, "per-ip"


def _auth_ip_guard(request: Request, rule: _Rule) -> tuple[str, int, str] | None:
    if not rule.paid_cap or _candidate_api_key(request) is None:
        return None
    ip = _normalize_ip_to_prefix(_client_ip(request))
    return f"auth-ip:{ip}", rule.paid_cap, "per-auth-ip"


def _take(bucket_key: str, cap: int) -> tuple[bool, int]:
    """Return ``(allowed, retry_after_s)``.

    Atomic under ``_buckets_lock``. Window slide is computed lazily on
    each call: drop timestamps older than ``now - _WINDOW_S``, then test
    against ``cap``.
    """
    now = time.monotonic()
    cutoff = now - _WINDOW_S
    with _buckets_lock:
        dq = _buckets.get(bucket_key)
        if dq is None:
            dq = deque()
            _buckets[bucket_key] = dq
        # Evict expired timestamps from the front.
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) < cap:
            dq.append(now)
            return True, 0
        # Over cap. Retry-After = seconds until the oldest entry ages
        # out, rounded up to a whole second.
        retry = max(1, int((dq[0] + _WINDOW_S) - now + 0.999))
        return False, retry


def _is_disabled() -> bool:
    """Short-circuit env flag for tests / emergency disable."""
    return os.environ.get("PER_IP_ENDPOINT_LIMIT_DISABLED") == "1"


class PerIpEndpointLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP, per-endpoint, per-minute cap. Independent of the burst
    gate (rate_limit.py) and the monthly anon quota (anon_limit.py).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if _is_disabled():
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)

        try:
            rule = _match_rule(request.method, request.url.path)
        except Exception:  # pragma: no cover — defensive
            logger.exception("per_ip_endpoint_limit_match_failed")
            return await call_next(request)
        if rule is None:
            return await call_next(request)

        try:
            identity, cap, bucket_kind = _bucket_identity_and_cap(request, rule)
            bucket_key = f"{identity}|{rule.label}"
            allowed, retry_after = _take(bucket_key, cap)
            auth_ip_guard = _auth_ip_guard(request, rule)
            if allowed and auth_ip_guard is not None:
                guard_identity, guard_cap, guard_kind = auth_ip_guard
                guard_key = f"{guard_identity}|{rule.label}"
                guard_allowed, guard_retry_after = _take(guard_key, guard_cap)
                if not guard_allowed:
                    allowed = False
                    retry_after = guard_retry_after
                    cap = guard_cap
                    bucket_kind = guard_kind
        except Exception:  # pragma: no cover — defensive
            logger.exception("per_ip_endpoint_limit_take_failed")
            return await call_next(request)

        if allowed:
            return await call_next(request)

        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "rate_limited",
                    "message": (
                        "このエンドポイントへのアクセスが多すぎます。"
                        f"{retry_after} 秒後に再試行してください。"
                    ),
                    "message_en": (
                        f"Too many requests for this endpoint. Retry after {retry_after}s."
                    ),
                    "retry_after": retry_after,
                    "bucket": f"{bucket_kind}:{rule.label}",
                    "limit_per_minute": cap,
                }
            },
            headers={"Retry-After": str(retry_after)},
        )


__all__ = [
    "PerIpEndpointLimitMiddleware",
    "_reset_per_ip_endpoint_buckets",
    "_RULES",
]
