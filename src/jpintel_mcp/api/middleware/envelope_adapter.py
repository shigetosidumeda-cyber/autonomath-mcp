"""Optional ``?envelope=v2`` adapter middleware (§28.2 Agent Contract).

The plan ships the v2 envelope as **opt-in** so we don't break ~140
existing routes during the launch window. This middleware is a thin
diagnostic + observability layer; it does NOT mass-rewrite legacy
responses (that would defeat the opt-in promise).

What it does:

  1. Stamps ``request.state.envelope_v2`` (bool) — routes consult this
     to choose which shape to emit.
  2. Echoes the negotiated content type via the ``X-Envelope-Version``
     response header (``v1`` or ``v2``) so a customer agent can confirm
     which shape it received without parsing the body.
  3. Sets a ``Vary: Accept, X-Envelope-Version`` response header so any
     intermediate cache (Cloudflare Pages, downstream proxy) treats the
     two shapes as separate cache entries.

What it explicitly does NOT do:

  - Rewrite a legacy body into v2 shape (would require knowing the
    semantics of every route's payload — out of scope for the launch
    window).
  - Reject legacy callers when v2 is preferred (default is legacy).
  - Touch the error path (errors flow through the global handlers in
    ``api/main.py:_http_exception_handler``).

Routes that opt in (see ``api/programs.py``, ``api/houjin.py``, and
``api/autonomath.py:rest_deep_health``) call ``wants_envelope_v2(request)``
themselves to branch their response builders. The middleware just
ensures the flag is consistently parsed and the response signals back
to the caller which version it served.
"""
from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from jpintel_mcp.api._envelope import wants_envelope_v2

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request
    from starlette.responses import Response


class EnvelopeAdapterMiddleware(BaseHTTPMiddleware):
    """Stamp v2 opt-in flag + echo X-Envelope-Version response header.

    Order: install AFTER ``_RequestContextMiddleware`` (so request_id is
    already on ``request.state``) and BEFORE any route-mounted middleware
    that might short-circuit (rate limit, CORS). The flag is read by
    individual routes — middleware order matters only for the request
    state stamp, not the response header which is added on the way out.
    """

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        # 1) Parse the opt-in once so individual routes don't re-parse
        #    the query params + Accept header.
        try:
            v2 = wants_envelope_v2(request)
        except Exception:  # noqa: BLE001 — never break a request on opt-in parse
            v2 = False
        with contextlib.suppress(Exception):  # Starlette state always present, defensive
            request.state.envelope_v2 = v2

        # 2) Run the route.
        response = await call_next(request)

        # 3) Stamp the negotiated version header on the way out. Helps a
        #    customer agent verify which shape it received without parsing
        #    the body. Also gives us a crisp signal in access logs for
        #    measuring v2 adoption pre-default-flip.
        try:
            response.headers["X-Envelope-Version"] = "v2" if v2 else "v1"
            existing_vary = response.headers.get("Vary")
            vary_tokens = {t.strip() for t in (existing_vary or "").split(",") if t.strip()}
            vary_tokens.update({"Accept", "X-Envelope-Version"})
            response.headers["Vary"] = ", ".join(sorted(vary_tokens))
        except Exception:  # noqa: BLE001 — header set must never break a response
            pass

        return response


__all__ = ["EnvelopeAdapterMiddleware"]
