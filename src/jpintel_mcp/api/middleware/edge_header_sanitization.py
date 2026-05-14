"""Edge header sanitization (Defense-in-Depth, 2026-05-13).

Cloudflare adds a family of ``CF-*`` headers to every request it proxies:

* ``CF-Connecting-IP`` — the true caller IP as seen by CF's edge.
* ``CF-IPCountry`` — ISO 3166-1 alpha-2 country code (or ``XX`` when unknown).
* ``CF-Ray`` — a unique request id, useful for cross-correlating CF logs.
* ``CF-Visitor`` — JSON blob carrying the original scheme + visitor metadata.
* ``CF-Worker`` — set when the request originated inside a CF Worker.
* ``CF-IPCity`` / ``CF-IPLatitude`` / ``CF-IPLongitude`` / ``CF-IPTimeZone``
  / ``CF-IPContinent`` — geo enrichment (Cloudflare Enterprise / paid tier).
* ``CF-EW-Via`` — set when an Email Worker rewrote the request.
* ``CF-Pseudo-IPv4`` — IPv4 mapping for v6-only callers (Pseudo IPv4 flag).
* ``CF-Device-Type`` — UA-class hint (mobile/tablet/desktop).
* ``CF-JA3-Hash`` / ``CF-JA4`` — TLS ClientHello fingerprints (BotFight).

These headers are AUTHORITATIVE when the request actually traversed the
Cloudflare edge — they describe ground-truth metadata that no client could
have provided. But they are also TRIVIALLY SPOOFABLE by any caller that
hits the origin directly (bypassing the CF edge by hitting ``*.fly.dev`` or
the bare Fly machine address). A direct caller can claim
``CF-IPCountry: KP`` to evade country-based gating, ``CF-Connecting-IP:
1.1.1.1`` to forge audit-log attribution, or strip them entirely.

**Today's edge chain.** Production traffic flows ``client → Cloudflare →
Fly proxy → origin``. Two paths exist:

1. ``api.jpcite.com/v1/*`` — DNS points at CF; CF orange-clouds to Fly;
   CF appends its CF-* headers; Fly proxy preserves them in transit.
2. ``jpcite.com/api/*`` — DNS points at Cloudflare Pages, which runs
   ``functions/api_proxy.ts`` (CF Pages Function). That function
   strips all inbound ``CF-*`` and ``X-Edge-Auth`` headers before minting
   its own trusted headers for ``api.jpcite.com``.

Both paths converge at origin via the Fly proxy. The TCP peer the origin
observes (``request.client.host``) is the Fly proxy IP, NOT a CF egress
IP, so an IP allowlist of CF egress ranges does **not** apply at this
layer. The trust signal that actually matters is whether the request
hop in front of origin was the trusted Cloudflare edge.

**Sanitization policy.** Default-deny:

* If the request does NOT carry a valid signed ``X-Edge-Auth`` HMAC
  proving it was minted by our own Cloudflare Pages Function (shared
  secret ``JPCITE_EDGE_AUTH_SECRET``), AND
* the TCP peer is NOT in the configured ``JPCITE_CF_TRUSTED_PEER_IPS``
  allowlist (CIDR-aware, empty by default),

then every ``CF-*`` header is STRIPPED from the request before any
downstream middleware (anon_limit JA3 fingerprint reader, audit log,
country-gating handler) can read it. The headers are removed in
``request.scope["headers"]`` so even ``request.headers.get("cf-…")``
in a downstream layer returns ``None``.

**What this middleware does NOT do.**

* It does not touch ``Fly-Client-IP`` — that path has its own trust
  separation in ``anon_limit._client_ip`` + ``_raise_edge_ip_unavailable``
  (D2 hardening, 2026-05-13). Fly's proxy header is owned there.
* It does not touch ``X-Forwarded-For`` either — the same module already
  refuses to trust bare XFF (see anon_limit.py docstring).
* It does not validate signatures statically at boot — operators can
  rotate ``JPCITE_EDGE_AUTH_SECRET`` without redeploying.
* It does not emit a metric on every strip (would be ~100% of traffic
  on a misconfigured deploy, drowning Sentry). Per-request structured
  logging is left to downstream auditing.

**LIFO placement.** Add this middleware EARLY in the LIFO stack
(late in ``main.py`` setup) so it runs FIRST on the request, before
``anon_limit._ja3_hash`` reads ``cf-ja3-hash`` and before any handler
inspects ``CF-IPCountry``. Specifically: AFTER ``KillSwitchMiddleware``
+ ``OriginEnforcementMiddleware`` (which themselves run first) so a
killed app or blocked origin still short-circuits, but BEFORE every
middleware that introspects request headers for trust-bearing values.

**Test contract**:
``tests/test_edge_header_sanitization.py`` pins:

1. Direct-to-origin request with spoofed ``CF-IPCountry: KP`` and no
   signed header → origin sees the header as absent.
2. CF-proxy-equivalent request signed with the shared secret →
   headers preserved.
3. Allowlisted peer IP (set via ``JPCITE_CF_TRUSTED_PEER_IPS``) →
   headers preserved.
4. ``cf-ja3-hash`` (used by ``anon_limit`` for fingerprinting) is
   subject to the same gate — direct caller cannot forge a JA3.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import ipaddress
import os
import time
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from starlette.requests import Request
    from starlette.responses import Response


# Canonical lowercase set of CF-* headers we strip when the request is not
# from a trusted hop. Lowercase because ASGI normalises header names to
# lowercase in `scope["headers"]`. Keep this list exhaustive — any
# CF-prefixed header we forget is one a direct-to-origin attacker could
# spoof and have a downstream handler trust.
_CF_HEADERS_TO_STRIP: frozenset[bytes] = frozenset(
    {
        b"cf-connecting-ip",
        b"cf-connecting-ipv6",
        b"cf-ipcountry",
        b"cf-ipcity",
        b"cf-ipcontinent",
        b"cf-iplatitude",
        b"cf-iplongitude",
        b"cf-iptimezone",
        b"cf-postal-code",
        b"cf-region",
        b"cf-region-code",
        b"cf-metro-code",
        b"cf-ray",
        b"cf-visitor",
        b"cf-worker",
        b"cf-ew-via",
        b"cf-pseudo-ipv4",
        b"cf-device-type",
        b"cf-ja3-hash",
        b"cf-ja4",
        b"cf-bot-management-score",
        b"cf-verified-bot",
        b"cf-threat-score",
        b"cf-tlsversion",
        b"cf-tlscipher",
    }
)

# Header carrying the HMAC proof minted by the CF Pages Function.
# Lowercase because we compare against ASGI header names.
_EDGE_AUTH_HEADER: bytes = b"x-edge-auth"

# Replay protection: the signed payload includes a unix-epoch timestamp.
# Anything older than this window is treated as a replay attempt and the
# signature is rejected.
_EDGE_AUTH_MAX_AGE_SECONDS: int = 300

# Path prefixes exempt from CF-header stripping. Health checks and
# Stripe webhooks do not introspect CF-* headers, but stripping is also
# cheap there — we keep the exemption short and documented for parity
# with OriginEnforcementMiddleware so it is obvious that everything
# else is gated.
_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/healthz",
        "/readyz",
    }
)


def _edge_auth_secret() -> str:
    """Return the shared HMAC secret for X-Edge-Auth, or empty if unset.

    When unset, signed-header trust is disabled entirely — only the
    peer-IP allowlist can authorise CF-* passthrough. This is the safe
    default for fresh deployments that have not yet rotated a secret
    into Fly + CF Pages: every request is treated as untrusted and CF-*
    headers are stripped.
    """
    return os.environ.get("JPCITE_EDGE_AUTH_SECRET", "").strip()


def _trusted_peer_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse ``JPCITE_CF_TRUSTED_PEER_IPS`` (comma-separated CIDRs) once.

    Re-read on every call so an operator can flip the var without a
    redeploy. Parsing failures are logged-but-not-raised — a malformed
    entry should not take the API down; it just means that entry is
    ignored and the request hits the signed-header path (or the strip
    fallback) instead.
    """
    raw = os.environ.get("JPCITE_CF_TRUSTED_PEER_IPS", "").strip()
    if not raw:
        return ()
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for chunk in raw.split(","):
        entry = chunk.strip()
        if not entry:
            continue
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            # Silently skip malformed entries. Tests will catch the
            # mistake separately; in production we never want a typo
            # in this env var to cause a boot loop.
            continue
    return tuple(nets)


def _peer_is_trusted(peer_host: str | None) -> bool:
    """Return True iff ``peer_host`` is inside the configured CF allowlist.

    Empty allowlist (default) means no peer is trusted by IP — every
    request must instead carry a valid signed X-Edge-Auth. This is the
    safe default; operators opt-in to IP-based trust explicitly.
    """
    if not peer_host:
        return False
    nets = _trusted_peer_networks()
    if not nets:
        return False
    try:
        addr = ipaddress.ip_address(peer_host)
    except ValueError:
        return False
    return any(addr in net for net in nets)


def _verify_signed_edge_header(
    raw_value: str,
    secret: str,
    *,
    now: int | None = None,
    caller_ip: str | None = None,
) -> bool:
    """Constant-time HMAC verification on X-Edge-Auth.

    Expected current wire format:
    ``v1:<unix_ts>:<caller_ip>:<hex_hmac_sha256>`` where the HMAC is
    computed over ``f"v1:{unix_ts}:{caller_ip}"`` keyed by ``secret``.
    The older ``v1:<unix_ts>:<hex_hmac_sha256>`` format is still accepted
    when ``caller_ip`` is not supplied so already-deployed edge functions
    can roll through without breaking CF-header passthrough. Callers that
    need to trust ``X-Forwarded-For`` pass ``caller_ip`` and therefore
    require the bound token.

    Rejection conditions (any → False):

    * Empty secret (signed path disabled).
    * Empty header value.
    * Malformed structure (wrong segment count, unknown version).
    * Non-numeric timestamp.
    * Timestamp older than ``_EDGE_AUTH_MAX_AGE_SECONDS`` (replay window).
    * Future timestamp by more than 60s (clock skew tolerance).
    * HMAC mismatch (constant-time compare).
    """
    if not secret or not raw_value:
        return False
    parts = raw_value.split(":", 2)
    if len(parts) != 3:
        return False
    version, ts_str, tail = parts
    tail_parts = tail.rsplit(":", 1)
    if len(tail_parts) == 2:
        token_caller_ip, sig_hex = tail_parts
        if not token_caller_ip:
            return False
    else:
        token_caller_ip = None
        sig_hex = tail
    if version != "v1":
        return False
    if caller_ip is not None:
        if token_caller_ip is None:
            return False
        if token_caller_ip != caller_ip:
            return False
    try:
        ts = int(ts_str)
    except ValueError:
        return False
    current = now if now is not None else int(time.time())
    age = current - ts
    # Allow up to 60s of negative skew (origin clock ahead of edge clock).
    if age < -60:
        return False
    if age > _EDGE_AUTH_MAX_AGE_SECONDS:
        return False
    if token_caller_ip is not None:
        payload = f"v1:{ts_str}:{token_caller_ip}".encode()
    else:
        payload = f"v1:{ts_str}".encode()
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_hex.lower())


def _strip_cf_headers_inplace(scope: dict[str, Any]) -> int:
    """Remove every ``CF-*`` header from ``scope["headers"]`` in place.

    ASGI's ``scope["headers"]`` is a ``list[tuple[bytes, bytes]]`` keyed
    on lowercase header name. We rebuild the list excluding any entry
    whose name is in ``_CF_HEADERS_TO_STRIP``. Returns the count of
    stripped headers so tests / observability can pin the behaviour.

    Mutating ``scope["headers"]`` (rather than only ``request.headers``)
    is the load-bearing step: ``request.headers`` is a thin lazy view
    over ``scope["headers"]``, so a subsequent middleware that builds
    its own ``Request(scope)`` (e.g. anon_limit, audit) still sees the
    sanitised header list. Skipping this step would only mutate the
    current ``Request`` object and leave the underlying scope untouched.
    """
    raw_headers: list[tuple[bytes, bytes]] = scope.get("headers") or []
    if not raw_headers:
        return 0
    kept: list[tuple[bytes, bytes]] = []
    stripped = 0
    for name, value in raw_headers:
        if name.lower() in _CF_HEADERS_TO_STRIP:
            stripped += 1
            continue
        kept.append((name, value))
    if stripped:
        scope["headers"] = kept
    return stripped


def _is_exempt_path(path: str) -> bool:
    """Return True if the request path bypasses CF-header sanitization.

    Mirrors the (much smaller) exempt set used by OriginEnforcementMiddleware
    for monitoring endpoints. Webhook surfaces are NOT exempt — they have
    their own signature verification and CF-* metadata is not part of it.
    """
    return path in _EXEMPT_PATHS


class EdgeHeaderSanitizationMiddleware(BaseHTTPMiddleware):
    """Strip CF-* headers from untrusted requests before they reach handlers.

    Trust model (default-deny):

    1. **Signed-header path**: caller carries a valid ``X-Edge-Auth: v1:<ts>:<hmac>``
       header. Verified with the shared ``JPCITE_EDGE_AUTH_SECRET`` secret
       and a ±60s / +300s replay window. Pass-through.
    2. **Peer-IP allowlist path**: TCP peer is inside ``JPCITE_CF_TRUSTED_PEER_IPS``
       (comma-separated CIDRs). Pass-through.
    3. **Default**: strip every ``CF-*`` header from ``scope["headers"]``.

    Either trust path is sufficient — they compose for defence in depth
    (rotating the HMAC secret does not require flipping the IP allowlist).

    The middleware never raises; it only mutates the request. Downstream
    handlers see either the original headers (trusted) or no CF-* headers
    at all (untrusted).
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[..., Any],
    ) -> Response:
        # Exempt monitoring surfaces — they do not introspect CF-* and a
        # downed health-check is a worse outcome than a leaked CF-Country
        # header on /healthz.
        if _is_exempt_path(request.url.path):
            return await call_next(request)

        # Trust path 1: signed header.
        secret = _edge_auth_secret()
        if secret:
            raw_token = request.headers.get("x-edge-auth", "")
            if raw_token and _verify_signed_edge_header(raw_token, secret):
                return await call_next(request)

        # Trust path 2: peer IP allowlist.
        peer_host: str | None = None
        if request.client:
            peer_host = request.client.host
        if _peer_is_trusted(peer_host):
            return await call_next(request)

        # Untrusted: strip every CF-* header. Stash the count on
        # request.state for downstream observability (audit log,
        # tests). Use scope mutation so a later middleware building
        # its own Request() instance still sees the sanitised list.
        stripped = _strip_cf_headers_inplace(request.scope)
        # request.state is a SimpleNamespace; safe to attach freely.
        with contextlib.suppress(AttributeError):
            request.state.edge_headers_stripped = stripped
        return await call_next(request)


__all__ = [
    "EdgeHeaderSanitizationMiddleware",
    "_CF_HEADERS_TO_STRIP",
    "_strip_cf_headers_inplace",
    "_verify_signed_edge_header",
    "_peer_is_trusted",
]
