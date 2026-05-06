"""Browser-side security response headers (P2.6.5, 2026-04-25).

Stamps the standard hardening headers on every response so that any
HTML rendered by an upstream client (operator dashboard, embedded
widget host, browser-loaded docs) cannot be exploited via
clickjacking, MIME sniffing, mixed-content downgrade, or referrer
leak. The product is API-first (JSON / MCP) but the API still serves
a handful of HTML surfaces (``/v1/subscribers/unsubscribe`` HTML
page, future Stripe-hosted callback pages reachable via redirect),
and downstream tooling (Stainless / Mintlify / Postman) rendering
the OpenAPI spec ALSO benefits from a tightened HSTS + CSP envelope.

Headers set (all via ``setdefault`` — never override an upstream
middleware that has already chosen a value):

* ``Strict-Transport-Security`` — 1 year + includeSubDomains + preload.
  Long max-age + preload is intentional: ``jpcite.com`` is operator-
  controlled, never returns to plain HTTP, and we want every browser
  + every ``api.jpcite.com`` subdomain to refuse cleartext from
  the very first request. Listing on the HSTS preload registry is a
  follow-up domain-side action (not code).
* ``Content-Security-Policy`` — ``default-src 'self'`` plus an
  ``'unsafe-inline'`` allowance for ``style-src`` (the unsubscribe
  HTML uses inline ``<style>``; no inline ``<script>`` is ever
  served). ``frame-ancestors 'none'`` blocks clickjacking even if a
  client ignores ``X-Frame-Options``.
* ``X-Frame-Options: DENY`` — redundant with CSP ``frame-ancestors``
  but kept for legacy browsers that don't honour CSP3.
* ``X-Content-Type-Options: nosniff`` — stops IE/Edge from MIME-
  sniffing a JSON body into HTML.
* ``Referrer-Policy: strict-origin-when-cross-origin`` — leak the
  origin only on same-scheme upgrades; never the path / query.
* ``Permissions-Policy`` — disable geolocation / microphone / camera
  for any embedding context. We never use these, so an explicit
  ``=()`` opt-out hardens against a future content-injection bug
  re-enabling them.

Why first in the LIFO middleware stack (= added EARLY in
``main.py``):

Starlette's middleware ordering is LIFO — the LAST ``add_middleware``
call wraps the others, so it executes FIRST on the request and LAST
on the response. We want security headers to be stamped on every
response *including* the responses synthesised by upstream
middleware (rate-limit 429, kill-switch 503, customer-cap 503), so
this middleware must be added EARLY (LIFO inner) and therefore
execute LATE on the way out — after the upstream middleware has
already produced its short-circuit response. ``setdefault`` keeps
us from overriding a header that an upstream layer deliberately set.

DNSSEC + HSTS preload registration are handled by the operator at
the DNS / Cloudflare dashboard layer (see
``docs/_internal/autonomath_com_dns_runbook.md``); this module only
emits the in-band browser hints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request
    from starlette.responses import Response


# Frozen at import time; building the dict on every request would be
# pure waste (these strings never change at runtime).
_SECURITY_HEADERS: dict[str, str] = {
    # 1 year, includeSubDomains, preload — jpcite.com is HTTPS-only
    # and we want browsers to refuse plain HTTP on the very first hit.
    "Strict-Transport-Security": ("max-age=31536000; includeSubDomains; preload"),
    # API-first product, no third-party CDN, no inline scripts. style-src
    # 'unsafe-inline' covers the /v1/subscribers/unsubscribe HTML page
    # which uses inline <style>. frame-ancestors 'none' blocks clickjacking.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'; "
        "base-uri 'none'"
    ),
    # Redundant with CSP frame-ancestors but kept for pre-CSP3 browsers.
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # We don't use any of these surfaces; explicit empty allowlist
    # hardens against a future content-injection bug re-enabling them.
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Stamp the standard browser-hardening headers on every response.

    Uses ``setdefault`` so that a more specific upstream layer (e.g. a
    route that intentionally sends a different ``Referrer-Policy`` for
    a one-off integration) is never silently overridden.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response: Response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


__all__ = ["SecurityHeadersMiddleware"]
