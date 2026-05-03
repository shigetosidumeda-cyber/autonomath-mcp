"""Strict query-parameter middleware (δ1, group δ).

Background
----------
A wave-3 audit (K4 / J10) found that 87% of REST endpoints (80/92) were
silently dropping unknown query parameters. FastAPI's default behaviour
is to ignore any query key that no declared :class:`Depends` /
:class:`Query` parameter consumes. For an LLM consumer this is a
correctness hole: the agent thinks it filtered with
``?prefecture=東京都`` but the server returned an unfiltered global
result, which the agent then summarises as fact. False positive
classification by the upstream model is the worst possible failure
mode for AutonoMath because customers pay ¥3/req for a result they
cannot trust.

Behaviour
---------
On every request we resolve the matched route (walking the FastAPI
router tree just like Starlette does internally), read the route's
``dependant.query_params`` (the closed set of declared param names,
including alias names), and reject any request that carries a query
key not in that set with **HTTP 422** + a structured
``unknown_query_parameter`` envelope.

Notes / design choices
----------------------
* **Why not request.scope["route"]?** ``BaseHTTPMiddleware`` runs
  *before* Starlette's routing layer populates ``scope["route"]``, so
  the scope is empty here. We replicate Starlette's match loop with
  ``route.matches(scope)`` and pick the first ``Match.FULL``.
* **Recursive match.** FastAPI mounts sub-routers via
  ``include_router``; the top-level ``app.router.routes`` contains
  ``APIRoute`` objects after include, but we still walk a possible
  ``Mount`` tree defensively.
* **Opt-out.** Setting ``JPINTEL_STRICT_QUERY_DISABLED=1`` skips the
  middleware entirely. Used by tests that exercise legacy unknown-key
  tolerance, and as a runtime kill-switch if the closed-set assumption
  ever surfaces an unforeseen breakage in prod.
* **Unmatched route.** If no route matches, we let the request through
  so the existing 404 handler can format the response (the strict-query
  layer is not a router — only a query-shape gate). Same for routes
  without a ``dependant`` attribute (e.g. mounted Starlette ``Route``).
* **Method tolerance.** A query check fires on any HTTP method; even
  ``POST`` bodies sometimes carry query-string filters in our API
  (``/v1/programs/search?q=...`` with no body). The check is purely
  about the URL query, not the body.
* **CORS preflight bypass.** ``OPTIONS`` requests skip the gate so a
  browser preflight that doesn't carry a CORS-relevant query never
  trips a 422. CORS layer answers preflight on its own.

Headers
-------
The 422 response does not set ``x-request-id`` itself; that header is
attached by the outer ``_RequestContextMiddleware`` after this gate
returns. The error envelope still echoes the request id via
``request.state`` if available.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.routing import Match

_log = logging.getLogger("jpintel.strict_query")

#: Env var name. Set to "1" to disable the middleware at runtime.
ENV_DISABLE = "JPINTEL_STRICT_QUERY_DISABLED"


def _is_disabled() -> bool:
    return os.getenv(ENV_DISABLE, "").strip() == "1"


def _walk_routes(routes, scope):
    """Recursively find the first FULL-matching route in a router tree.

    Returns the matching route or ``None``. Walks both top-level
    ``APIRoute`` entries and any nested ``Mount`` / ``Router`` whose
    ``.routes`` is iterable. Mirrors what
    ``starlette.routing.Router.__call__`` does internally, but lets us
    inspect the matched route's ``dependant`` *before* the handler
    runs.
    """
    for route in routes:
        try:
            match, _child_scope = route.matches(scope)
        except Exception:  # pragma: no cover — defensive
            continue
        if match == Match.FULL:
            return route
        # Defensive: descend into nested routers (rarely used but safe).
        nested = getattr(route, "routes", None)
        if nested:
            found = _walk_routes(nested, scope)
            if found is not None:
                return found
    return None


def _declared_query_param_names(route) -> set[str] | None:
    """Return the closed set of declared query param names for a route.

    Includes the parameter alias if set (FastAPI exposes the alias as
    the ``name`` on the ModelField in ``dependant.query_params``, which
    is the form callers actually send on the wire). Returns ``None``
    if the route is not an APIRoute-style FastAPI route — caller treats
    that as "skip strict check".
    """
    dep = getattr(route, "dependant", None)
    if dep is None:
        return None
    names: set[str] = set()
    for p in dep.query_params:
        # ModelField.name is the wire name (alias if alias set).
        if getattr(p, "name", None):
            names.add(p.name)
    return names


class StrictQueryMiddleware(BaseHTTPMiddleware):
    """Reject requests carrying undeclared query parameters with 422.

    See module docstring for rationale and design notes.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if _is_disabled():
            return await call_next(request)

        # Skip CORS preflight — the CORS layer answers OPTIONS itself
        # and a 422 here would break a browser caller's discovery flow.
        if request.method == "OPTIONS":
            return await call_next(request)

        # Empty query string: nothing to check, fast path.
        if not request.url.query:
            return await call_next(request)

        try:
            route = _walk_routes(request.app.router.routes, request.scope)
        except Exception:
            # Never block a request because the middleware itself
            # failed to walk the tree — fail open.
            _log.exception("strict_query: route walk failed")
            return await call_next(request)

        if route is None:
            # Unknown route — let the 404 handler format the response.
            return await call_next(request)

        declared = _declared_query_param_names(route)
        if declared is None:
            # Non-APIRoute (e.g. Starlette Mount) — skip strict check.
            return await call_next(request)

        actual = set(request.query_params.keys())
        unknown = actual - declared
        if not unknown:
            return await call_next(request)

        # Build the structured 422 envelope. Use the canonical error
        # envelope helper so wire shape matches every other 4xx/5xx.
        from jpintel_mcp.api._error_envelope import make_error  # local import
        from jpintel_mcp.api.middleware.did_you_mean import (
            suggest_query_keys,
        )

        rid = request.headers.get("x-request-id")
        unknown_sorted = sorted(unknown)
        expected_sorted = sorted(declared)
        # R12 §2.1 / W2-3 D1: stdlib difflib suggester for typos like
        # `perfecture → prefecture`. Empty dict when nothing close enough;
        # downstream renders only the human-readable hint when populated.
        did_you_mean = suggest_query_keys(unknown_sorted, expected_sorted)
        hint = ""
        if did_you_mean:
            hint = "もしかして: " + ", ".join(f"{k} → {v}" for k, v in did_you_mean.items()) + ". "
        body = make_error(
            code="unknown_query_parameter",
            user_message=(
                "未定義のクエリパラメータが含まれています: "
                f"{', '.join(unknown_sorted)}. "
                f"{hint}"
                f"許可されているパラメータ: {', '.join(expected_sorted) or '(なし)'}"
            ),
            request_id=rid,
            unknown=unknown_sorted,
            expected=expected_sorted,
            did_you_mean=did_you_mean,
            path=request.url.path,
            method=request.method,
        )
        return JSONResponse(status_code=422, content=body)


__all__ = ["StrictQueryMiddleware", "ENV_DISABLE"]
