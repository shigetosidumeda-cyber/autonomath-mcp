"""Cache-Control headers for static-ish JSON manifests (R8 perf, 2026-05-07).

The OpenAPI spec, the agent-projection spec, and the MCP server manifest
change only on deploy. R8_PERF_BASELINE_2026-05-07 measured them as the
top edge-cache-miss bandwidth source: 539 KB raw / 105 KB gzip per
``/v1/openapi.json`` fetch, re-rendered server-side on every probe, with
no ``Cache-Control`` header so Cloudflare (and any downstream HTTP cache)
treated each response as un-cacheable.

This middleware stamps a ``Cache-Control: public, max-age=300,
s-maxage=600`` header on the three manifests so:

* Browsers / SDK generators / Stainless-style introspectors hold a copy
  for 5 minutes (``max-age=300``).
* CF / Fastly / Akamai edges hold a copy for 10 minutes
  (``s-maxage=600``).
* The combined effect is one origin fetch per edge POP per 10 minutes
  instead of every request, which lets us reclaim the SJC anycast +
  back-haul-to-NRT 540 ms tax measured in R8.

Why a middleware rather than per-route ``response.headers[...]``:

* ``/v1/openapi.json`` is registered by FastAPI itself during ``setup()``
  and we cannot wire response_class kwargs into that path without
  monkey-patching ``app.openapi``. A small middleware path-match keeps
  the change surgical and reversible.
* The middleware is *additive*: it only sets ``Cache-Control`` when the
  upstream layer hasn't already chosen a value (``setdefault``-style),
  so any future per-route override wins without a code change here.
* LIFO ordering — added EARLY so it executes LATE on the response and
  sees the bytes upstream serializers have already produced.

Negative cases (do NOT cache):

* 4xx / 5xx responses must not be edge-cached — a transient 500 should
  not poison the manifest for 10 minutes. The middleware checks the
  response status before stamping.
* Routes that already set ``Cache-Control`` (e.g. ``no-store`` for any
  customer-state surface) are not overridden.

Path matching is exact-prefix on the request URL path so the middleware
never accidentally caches anything else (search results, billing, etc.).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request
    from starlette.responses import Response


# Static-ish manifests. Edit only when a new deploy-stamp manifest is
# added at the API surface. Order matters only for readability; the
# middleware uses set membership.
_STATIC_MANIFEST_PATHS: frozenset[str] = frozenset(
    {
        "/v1/openapi.json",
        "/v1/openapi.agent.json",
        "/v1/mcp-server.json",
    }
)

# Frozen at import time. ``public`` allows shared (CDN) caches to store
# the response. ``max-age=300`` = 5 minutes for the end client (browser,
# SDK generator). ``s-maxage=600`` = 10 minutes for the shared cache
# (Cloudflare). The two values being different is intentional: we want
# edge POPs to coalesce more aggressively than browsers.
_CACHE_CONTROL_VALUE: str = "public, max-age=300, s-maxage=600"


class StaticManifestCacheMiddleware(BaseHTTPMiddleware):
    """Stamp ``Cache-Control`` on the deploy-stamp JSON manifests.

    Idempotent — uses ``setdefault`` so any upstream layer that has
    already chosen a value (including a future ``no-store`` override
    for a one-off integration) is preserved. Only stamps on 2xx
    responses; transient errors must not be edge-cached.
    """

    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
        response: Response = await call_next(request)
        path = request.url.path
        if path in _STATIC_MANIFEST_PATHS and 200 <= response.status_code < 300:
            response.headers.setdefault("Cache-Control", _CACHE_CONTROL_VALUE)
        return response


__all__ = ["StaticManifestCacheMiddleware"]
