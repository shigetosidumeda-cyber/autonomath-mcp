"""Legacy-host deprecation middleware (api.zeimu-kaikei.ai → api.jpcite.com).

Background
----------
``api.jpcite.com`` is the canonical API domain (matches the rest of the
brand surface — site, dashboard, docs). The product previously served at
``api.zeimu-kaikei.ai`` which still has live customers and MCP clients
pointing at it. Both hostnames resolve to the same Fly.io app
(``autonomath-api``) so a hard cutover would break every existing
integration silently.

Strategy
~~~~~~~~
Indefinite parallel serving + RFC 8594 ``Deprecation`` + RFC 9745
``Sunset`` + RFC 8288 ``Link: rel="successor-version"`` on every response
served via the legacy host. Clients that honour the headers (modern
SDKs, well-behaved MCP clients, monitoring) see the migration signal
immediately; clients that ignore them keep working. We monitor traffic
share on the legacy host and only escalate (redirect / hard-deprecate)
once the legacy share drops below ~5%.

See ``docs/_internal/api_domain_migration.md`` for the full migration
plan.

Design constraints
~~~~~~~~~~~~~~~~~~
* **Headers only** — never mutates the response body, never changes
  status code. Pure additive observability + client hint. Existing
  callers are bit-for-bit unchanged on the legacy host.
* **Never raises** — observability code that breaks customer requests
  is worse than no observability. All exception paths swallow.
* **Cheap** — single ``request.headers.get('host')`` lookup + one
  case-insensitive compare per request. No DB read, no I/O.
* **Bypass nothing** — every legacy-host response gets tagged, including
  ``/healthz`` / ``/readyz``. A monitor still polling the legacy host
  needs to see the migration signal too.
* **Sunset date is hard-coded** — RFC 9745 expects an HTTP-date. We
  pin ``Wed, 31 Dec 2026 23:59:59 GMT`` as the formal end-of-life
  marker. The ACTUAL cutover date is decided by traffic share, not
  this constant; the date here is purely a client-facing hint for
  "do not assume this domain will work indefinitely". When the
  operator commits to a real cutover date, bump this constant in one
  place.

Header reference
~~~~~~~~~~~~~~~~
* ``Deprecation: true`` — RFC 8594. Boolean form indicates the
  resource is deprecated as of "now"; date form (``Deprecation:
  Wed, 11 Nov 2020 23:59:59 GMT``) indicates a specific past date.
  We use the boolean form because the legacy host has been deprecated
  since the new domain launched; pinning a single past date would be
  arbitrary.
* ``Sunset: <HTTP-date>`` — RFC 9745. The date past which the
  resource is expected to disappear. Clients can use this to schedule
  proactive migration.
* ``Link: <https://api.jpcite.com>; rel="successor-version"`` —
  RFC 8288 + RFC 5988. Points clients at the canonical replacement.
  ``successor-version`` is the registered relation type for
  "this resource has been superseded by the linked one".
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request
    from starlette.responses import Response


_log = logging.getLogger("autonomath.api.host_deprecation")

# Legacy hostname (lowercase for case-insensitive compare).
# Cloudflare / Fly may or may not include the port in the Host header
# depending on the proxy chain; we strip the port before comparing.
_LEGACY_HOST = "api.zeimu-kaikei.ai"

# Frozen at import time. RFC 9745 Sunset date — formal end-of-life
# marker. Actual cutover date is decided by traffic share monitoring;
# this is the client-facing "do not assume forever" hint. When the
# operator commits to a different cutover date, bump this constant.
_SUNSET_DATE = "Wed, 31 Dec 2026 23:59:59 GMT"

# Canonical successor URL. RFC 8288 link header, rel=successor-version.
_SUCCESSOR_URL = "https://api.jpcite.com"

_LEGACY_HOST_HEADERS: dict[str, str] = {
    "Deprecation": "true",
    "Sunset": _SUNSET_DATE,
    "Link": f'<{_SUCCESSOR_URL}>; rel="successor-version"',
}


def _is_legacy_host(request: Request) -> bool:
    """Return True iff the inbound request targeted the legacy hostname.

    Reads the ``Host`` header (Starlette normalises it to lowercase via
    its case-insensitive header dict). Strips the optional ``:port``
    suffix because Cloudflare / Fly proxy chains may or may not include
    it. Failure paths return False — we never want a header-parsing
    bug to flip the migration signal on for the canonical domain.
    """
    try:
        host = request.headers.get("host", "")
        if not host:
            return False
        # Strip optional port (`api.zeimu-kaikei.ai:443`).
        host_no_port = host.split(":", 1)[0].strip().lower()
        return host_no_port == _LEGACY_HOST
    except Exception:  # noqa: BLE001 — observability cannot raise
        _log.debug("legacy_host_check_failed", exc_info=True)
        return False


class HostDeprecationMiddleware(BaseHTTPMiddleware):
    """Stamp RFC 8594 / 9745 / 8288 headers on legacy-host responses.

    Triggered when the inbound ``Host`` header matches
    ``api.zeimu-kaikei.ai`` (case-insensitive, port-stripped). Adds
    ``Deprecation: true`` + ``Sunset: <date>`` + ``Link:
    <successor>; rel=successor-version`` to the outgoing response.
    Body and status code are untouched.

    Requests targeting the canonical host (``api.jpcite.com``) or any
    other host (local dev, internal probes) pass through unchanged.

    Uses ``setdefault`` so that a route handler that explicitly chose a
    different ``Sunset`` / ``Deprecation`` / ``Link`` value (e.g. a
    per-route deprecation already declared via the existing
    ``DeprecationWarningMiddleware`` flow) is never silently overridden.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        legacy = _is_legacy_host(request)
        response: Response = await call_next(request)
        if not legacy:
            return response
        try:
            for name, value in _LEGACY_HOST_HEADERS.items():
                response.headers.setdefault(name, value)
        except Exception:  # noqa: BLE001 — never break customer requests
            _log.debug("host_deprecation_stamp_failed", exc_info=True)
        return response


__all__ = ["HostDeprecationMiddleware"]
