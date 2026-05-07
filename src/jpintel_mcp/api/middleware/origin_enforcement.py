"""Origin allow-list enforcement (Wave 16 abuse-defense P1).

CORSMiddleware silently STRIPS the ``Access-Control-Allow-Origin`` header
when the request's ``Origin`` is not on the allow-list — but the request
still reaches the route handler. For a session-cookie POST that means a
malicious origin can fire a CSRF-style request that the browser will
refuse to read the response from, but our handler runs to completion (DB
write, Stripe API call, etc.) before the browser drops the response.

This middleware short-circuits any cross-origin request whose ``Origin``
header is set and not in the configured whitelist with HTTP 403 — BEFORE
any router. Both regular and OPTIONS preflight requests are gated.

Same-origin requests (no ``Origin`` header) and server-to-server callers
(curl, Stripe webhook, internal cron) are unaffected — those callers do
not include the ``Origin`` header.

Whitelist comes from ``settings.cors_origins`` (comma-separated). Default
includes apex + www + api for ``jpcite.com`` and ``autonomath.ai``
(see ``config.py`` for the canonical list). Apex AND www must both be
listed — Cloudflare Pages serves the marketing site at apex by default,
but `www` is also accessible and any browser request from there must
not be silently dropped. Operators must set ``JPINTEL_CORS_ORIGINS``
explicitly to allow ``http://localhost:3000`` etc. in dev environments.

Allowlist exempts health checks, signed webhooks, and the widget surface.
Widget requests have per-key origin allowlists and must reach
``widget_auth`` so the customer-specific allowlist can be enforced there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from jpintel_mcp.config import settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request
    from starlette.responses import Response

_MUST_INCLUDE: frozenset[str] = frozenset(
    {
        "https://jpcite.com",
        "https://www.jpcite.com",
        "https://api.jpcite.com",
        "https://zeimu-kaikei.ai",
        "https://www.zeimu-kaikei.ai",
        "https://api.zeimu-kaikei.ai",
        "https://autonomath.ai",
        "https://www.autonomath.ai",
    }
)

# Paths exempt from origin enforcement — see module docstring.
# /v1/billing/webhook is the Stripe-signed webhook; the signature header
# (verified inside the handler) is the auth, not Origin. /healthz and
# /readyz must be reachable from monitoring agents that may set arbitrary
# Origin or none.
_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/healthz",
        "/readyz",
        "/v1/billing/webhook",
        "/v1/email/webhook",
        "/v1/compliance/stripe-webhook",
        "/robots.txt",
        "/v1/am/health/deep",
    }
)
_EXEMPT_PATH_PREFIXES: tuple[str, ...] = ("/v1/widget/",)


def _allowed_origins() -> set[str]:
    raw = settings.cors_origins or ""
    return {o.strip().rstrip("/") for o in raw.split(",") if o.strip()} | set(_MUST_INCLUDE)


class OriginEnforcementMiddleware(BaseHTTPMiddleware):
    """Reject cross-origin requests not on ``settings.cors_origins`` with 403.

    Sits BEFORE the router (added late in the middleware stack so it runs
    early in the LIFO chain — after KillSwitch + RequestContext, before any
    DB-touching handler).
    """

    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
        # Same-origin / non-browser callers omit Origin entirely. Pass.
        origin = request.headers.get("origin")
        if not origin:
            return await call_next(request)
        # Exempt monitoring + webhook surfaces.
        if request.url.path in _EXEMPT_PATHS or request.url.path.startswith(_EXEMPT_PATH_PREFIXES):
            return await call_next(request)
        allowed = _allowed_origins()
        normalized = origin.rstrip("/")
        if normalized in allowed:
            return await call_next(request)
        # Not on the whitelist — 403 BOTH the request and any preflight
        # (OPTIONS). Returning 403 to a preflight is the documented way to
        # signal "this origin cannot talk to us at all" — browsers will
        # refuse the subsequent fetch.
        return JSONResponse(
            status_code=403,
            content={
                "error": "origin_not_allowed",
                "message": ("Cross-origin request from a non-whitelisted origin is not permitted."),
                "origin": normalized,
            },
            headers={
                # Vary by Origin so an upstream cache cannot serve a
                # successful response from one origin to another.
                "Vary": "Origin",
            },
        )


__all__ = ["OriginEnforcementMiddleware"]
