"""Deprecation-warning middleware (Sentry alert wiring, 2026-04-29).

Background
----------
The Sentry alert rule ``deprecated_endpoint_hit`` in
``monitoring/sentry_alert_rules.yml`` is configured to fire on
``logger:autonomath.api.deprecation level:warning`` with a 100-hits-in-7-days
threshold (weekly digest cadence — solo-ops can't deprecate routes faster
than customers migrate). Without an emitter the rule is inert; this
middleware is the emitter.

Two trigger sources are supported (whichever the operator chose to mark
the route with):

1. **FastAPI ``deprecated=True``** on the matched route. This is the
   OpenAPI-canonical flag — a route declared as
   ``@router.get("/x", deprecated=True)`` shows up in the spec with
   ``"deprecated": true`` and downstream tooling (Stainless / Mintlify /
   Postman) renders it as struck-through. We piggy-back on the same flag
   so deprecation marking is single-sourced.

2. **Response ``Deprecation`` / ``Sunset`` headers** (RFC 8594, RFC 9745).
   For routes that prefer a per-response opt-in (e.g. a parameter
   combination is deprecated, but the route itself is not), the handler
   sets the header and the middleware picks it up on the way out.

Why a middleware and not a router-level dependency?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A FastAPI ``Depends`` runs *before* the handler — at that point we know
the matched route but not the response, so the header-based trigger
would be invisible. A middleware sits AFTER the handler, sees the route
match (via ``request.scope['route']`` after Starlette resolved it) AND
the outgoing response. Both triggers are observable from the same place.

Design constraints
~~~~~~~~~~~~~~~~~~
* **Sentry-only emission.** The :func:`safe_capture_message` helper
  checks ``SENTRY_DSN`` + ``JPINTEL_ENV=prod`` before transmitting; with
  the DSN unset (dev/CI/test) the call short-circuits to a no-op. We do
  NOT log every deprecated hit at WARNING in normal runs (too noisy);
  the structured log is INFO-level so it shows up in dashboard tail but
  doesn't drown DEBUG.
* **Never raises.** Observability code that raises is worse than no
  observability. All exception paths swallow.
* **Bypass /healthz, /readyz, /status.** Liveness probes from Fly.io
  hit these tens of times per minute; they cannot be deprecated and
  should never tag the metric.
* **Bypass OPTIONS preflight.** Browsers send OPTIONS with no
  user-meaningful intent; an OPTIONS hit on a deprecated route does not
  signal an active dependency.

Filter-rule alignment
~~~~~~~~~~~~~~~~~~~~~
The Sentry rule expects:

  - ``logger:autonomath.api.deprecation`` (Python logger name)
  - ``level:warning`` (Sentry severity)
  - aggregate ``count()``, threshold 100 / 7d, frequency 24h

We emit a ``safe_capture_message(..., level="warning",
metric="api.deprecation.hit", route=<path_template>)`` which Sentry
indexes as a breadcrumb-class event with logger tag set to
``autonomath.api.deprecation`` (configured via the message's
``with sentry_sdk.push_scope`` block in the helper).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.routing import Match

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

# Logger name MUST match the Sentry rule filter
# (`monitoring/sentry_alert_rules.yml` rule id `deprecated_endpoint_hit`).
_log = logging.getLogger("autonomath.api.deprecation")

# Routes that should never tag the metric, regardless of marking.
# Liveness / readiness / status probes get hit by Fly.io health checks
# at high frequency; deprecating them is not a meaningful operation.
_ALWAYS_BYPASS_PATHS = frozenset(
    {
        "/healthz",
        "/readyz",
        "/status",
        "/robots.txt",
        "/v1/openapi.json",
        "/v1/openapi.agent.json",
        "/v1/am/health/deep",
    }
)


def _matched_route_is_deprecated(request: Request) -> tuple[bool, str | None]:
    """Walk the FastAPI router for the matched route + its deprecated flag.

    Returns ``(is_deprecated, path_template)``. ``BaseHTTPMiddleware`` runs
    before Starlette's routing layer populates ``scope['route']``, so we
    replicate Starlette's match loop. Same posture as ``StrictQueryMiddleware``
    (api/middleware/strict_query.py) which also walks the router by hand.

    On any error (no router, no matched route, attribute access blowup) we
    return ``(False, None)`` — the middleware fails open on the bypass check
    so a routing-system bug never blocks a real customer request.
    """
    try:
        app = request.scope.get("app")
        if app is None:
            return False, None
        router = getattr(app, "router", None)
        if router is None:
            return False, None
        for route in router.routes:
            match_result, _ = route.matches(request.scope)
            if match_result == Match.FULL:
                deprecated = bool(getattr(route, "deprecated", False))
                path_template = getattr(route, "path", None)
                return deprecated, path_template
    except Exception:  # noqa: BLE001 — observability cannot raise
        _log.debug("matched_route_lookup_failed", exc_info=True)
    return False, None


def _response_signals_deprecation(response: Response) -> bool:
    """Per-response opt-in: handler set ``Deprecation`` / ``Sunset`` header.

    RFC 8594 (`Deprecation`) is a date or boolean ``true``.
    RFC 9745 (`Sunset`) is an HTTP-date past which the route disappears.
    Either signals an active deprecation regardless of the route's
    ``deprecated`` flag — useful for "this parameter combination is
    deprecated, but the route is not".
    """
    if response is None:
        return False
    headers = response.headers
    if not headers:
        return False
    # Header lookup is case-insensitive in Starlette's MutableHeaders.
    return "deprecation" in headers or "sunset" in headers


class DeprecationWarningMiddleware(BaseHTTPMiddleware):
    """Tag deprecated-route hits to Sentry for the alert-rule pipeline.

    Triggers (any one fires the metric):

      * matched FastAPI route has ``deprecated=True``
      * response carries a ``Deprecation`` or ``Sunset`` header

    Emission target: ``safe_capture_message(metric="api.deprecation.hit",
    level="warning", route=<path>)``. The Sentry helper short-circuits if
    ``SENTRY_DSN`` is unset (dev/CI/test) so this middleware is a no-op
    in non-prod environments aside from the structured log line.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Bypass: liveness probes + preflight. These are not "real" hits
        # for the purposes of the deprecation budget.
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        if path in _ALWAYS_BYPASS_PATHS:
            return await call_next(request)

        is_deprecated, path_template = _matched_route_is_deprecated(request)
        response = await call_next(request)

        try:
            triggered_by_response = _response_signals_deprecation(response)
            if not (is_deprecated or triggered_by_response):
                return response

            # Pick the path template (e.g. ``/v1/programs/{program_id}``)
            # over the raw path so a deprecated parametric route does not
            # explode Sentry tag cardinality with one entry per id.
            tag_route = path_template or path

            # Structured log — always (cheap, dashboard-tailable).
            _log.warning(
                "deprecated_endpoint_hit route=%s method=%s status=%s trigger=%s",
                tag_route,
                request.method,
                response.status_code,
                "route_flag" if is_deprecated else "response_header",
            )

            # Sentry — gated by SENTRY_DSN + JPINTEL_ENV=prod inside
            # safe_capture_message. No-op in dev/CI/test.
            try:
                from jpintel_mcp.observability import safe_capture_message

                safe_capture_message(
                    f"api.deprecation.hit route={tag_route}",
                    level="warning",
                    metric="api.deprecation.hit",
                    route=tag_route,
                    method=request.method,
                    status_code=response.status_code,
                    trigger="route_flag" if is_deprecated else "response_header",
                )
            except Exception:  # noqa: BLE001 — observability cannot raise
                _log.debug("sentry_capture_failed", exc_info=True)
        except Exception:  # noqa: BLE001 — never break customer requests
            _log.debug("deprecation_middleware_failed", exc_info=True)

        return response


__all__ = ["DeprecationWarningMiddleware"]
