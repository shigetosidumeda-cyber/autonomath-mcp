"""Anonymous-quota response headers (S3 friction removal, 2026-04-25).

Every successful anonymous response (no X-API-Key, no Authorization: Bearer)
carries three response headers so an LLM caller — or its human-in-the-loop —
sees the remaining free quota and the conversion path **before** the 50/月
ceiling triggers a 429:

* ``X-Anon-Quota-Remaining`` — integer, calls left this JST calendar month.
* ``X-Anon-Quota-Reset``     — ISO 8601 timestamp of next JST 月初 00:00.
* ``X-Anon-Upgrade-Url``     — public landing for API-key issuance.

Why headers (not body wrapping):

The product has zero UI; the value is the API + MCP + static docs. We do
not own the calling client's render layer, so a body-level wrapper would
fight every existing JSON consumer. Headers are non-invasive: callers that
ignore them keep working, callers that read them (claude.ai's MCP host,
operator dashboards, curl scripts, custom Python clients) get the upgrade
hint surfaced naturally.

Why anonymous-only:

The 429 path covers the hard ceiling. These headers cover the *soft*
runway — the 0..49 calls before the ceiling — to convert traffic that
otherwise would silently churn at request 51. Authenticated callers
already know the upgrade URL (they used it once); spamming it on every
paid response is noise.

Quota state source:

``enforce_anon_ip_limit`` (router-level dep, ``api/anon_limit.py``) writes
``request.state.anon_quota`` after its INSERT/UPDATE so the count is
authoritative for *this* request — no second SELECT here. If the dep was
not attached to the route (whitelisted endpoint like ``/healthz``), no
``anon_quota`` is set and we leave the response alone.

Failure posture:

A missing ``request.state.anon_quota`` is the normal "this route is not
anon-quota-gated" signal — silent skip. Any other exception is logged at
WARN and swallowed; broken header injection must never become a 500
amplifier.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from jpintel_mcp.api.anon_limit import UPGRADE_URL_BASE

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request
    from starlette.responses import Response

_log = logging.getLogger("jpintel.anon_quota_header")


def _is_anonymous(request: Request) -> bool:
    """Same anon-detection rule as ``enforce_anon_ip_limit``.

    A request is "claiming auth" if it sends ``X-API-Key`` or an
    ``Authorization: Bearer ...`` header. Whether the key is *valid* is
    not our concern — bogus keys hit the 401 path elsewhere; the anon
    bucket is untouched for that request, so we should not stamp anon
    headers either.
    """
    if request.headers.get("x-api-key"):
        return False
    auth = request.headers.get("authorization", "")
    return not (auth and auth.split(None, 1)[0].lower() == "bearer")


class AnonQuotaHeaderMiddleware(BaseHTTPMiddleware):
    """Stamp anon-quota response headers on every anonymous response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response: Response = await call_next(request)

        # Fast skip: authed callers don't get anon headers.
        try:
            if not _is_anonymous(request):
                return response
        except Exception:  # pragma: no cover — defensive
            return response

        # The router-level dep populated request.state.anon_quota when it
        # ran. Routes that don't carry the dep (e.g. /healthz, /readyz,
        # /v1/billing/webhook) have no quota state -> silent skip.
        quota = getattr(request.state, "anon_quota", None)
        if not isinstance(quota, dict):
            return response

        try:
            remaining = int(quota.get("remaining", 0))
            reset_at = str(quota.get("reset_at_jst", ""))
            if remaining < 0:
                remaining = 0
            response.headers.setdefault("X-Anon-Quota-Remaining", str(remaining))
            if reset_at:
                response.headers.setdefault("X-Anon-Quota-Reset", reset_at)
            response.headers.setdefault("X-Anon-Upgrade-Url", UPGRADE_URL_BASE)
        except Exception:  # pragma: no cover — defensive
            _log.warning("anon_quota_header: failed to stamp headers", exc_info=True)

        return response


__all__ = ["AnonQuotaHeaderMiddleware"]
