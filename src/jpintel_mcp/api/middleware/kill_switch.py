"""Global kill-switch middleware.

P0 abuse / DoS lever (audit a7388ccfd9ed7fb8c, 2026-04-25). The single
Fly.io Tokyo box runs SQLite under file locks: a sustained burst (e.g. an
AI agent looping a search with bad pagination, or a botnet spraying
``/v1/programs/search`` at 1000 RPS) will pin sqlite and 503 every other
audience. Cloudflare WAF is the ideal first lever, but the operator
needs a sub-30s app-level toggle for incidents that get past the edge —
hence ``KILL_SWITCH_GLOBAL``.

Mechanism
---------
On every request, check ``os.environ["KILL_SWITCH_GLOBAL"]``. If set to
``"1"``, return 503 with the canonical ``service_unavailable`` error
envelope, EXCEPT for paths in :data:`_KILL_SWITCH_ALLOWLIST` so monitoring
(Fly health check / UptimeRobot / status page) keeps working.

Operator runbook: ``docs/_internal/launch_kill_switch.md``.

Recovery: ``flyctl secrets unset KILL_SWITCH_GLOBAL -a autonomath-api``
(reverses in ~30s) — see runbook §recovery for the announcement order.

Audit: every kill-switch hit logs an ``audit_log`` row with
``event_type='kill_switch_block'`` so we can see post-incident which
endpoints / IPs were rejected. Audit failures never break the response
(``_audit_log.log_event`` swallows DB errors by design).

Fail-open posture (vs. the rest of the stack)
---------------------------------------------
Unlike the rate-limit middleware (which fails *open* on internal errors
to avoid self-DoS), the kill switch fails *closed* on env-read errors:
the operator setting ``KILL_SWITCH_GLOBAL=1`` is an explicit "shed
load" intent, and a broken env read should never accidentally let
traffic through. In practice ``os.environ.get`` cannot raise — this is
defensive-only.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from jpintel_mcp.api._audit_log import log_event
from jpintel_mcp.api._error_envelope import make_error, safe_request_id

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request
    from starlette.responses import Response

logger = logging.getLogger("jpintel.kill_switch")


# Allowlisted paths — served normally even when the kill switch is on.
# Rationale per path:
#   /healthz, /readyz       — Fly liveness/readiness probe must keep
#                             responding so the orchestrator does not
#                             cycle the machine and worsen the incident.
#   /v1/am/health/deep      — AutonoMath deep-health probe used by
#                             UptimeRobot / external monitors.
#   /status, /status/       — Public status page (HTML on Cloudflare
#                             Pages; mirrored on the API for operator
#                             health dashboards).
#   /robots.txt             — Crawlers shouldn't get 503s mid-incident
#                             and de-index the entire surface.
_KILL_SWITCH_ALLOWLIST: frozenset[str] = frozenset(
    {
        "/healthz",
        "/readyz",
        "/v1/am/health/deep",
        "/status",
        "/status/",
        "/robots.txt",
    }
)


def _kill_switch_active() -> bool:
    """Return True iff ``KILL_SWITCH_GLOBAL=1`` is set in the process env.

    Read on every request (cheap; ``os.environ`` is a dict). Operators
    flip it via ``flyctl secrets set`` which restarts the Fly machine,
    but in dev / tests we want monkeypatch flips to take effect without
    a module reload.
    """
    return os.environ.get("KILL_SWITCH_GLOBAL") == "1"


def _kill_switch_reason() -> str | None:
    """Free-text reason captured at toggle time (``KILL_SWITCH_REASON``).

    Surfaced via ``GET /v1/admin/kill_switch_status`` so the operator
    has a forensic note about *why* the switch was flipped without
    reading flyctl history. Optional — falls back to None.
    """
    raw = os.environ.get("KILL_SWITCH_REASON", "")
    return raw.strip() or None


def _kill_switch_since() -> str | None:
    """Approximate ISO timestamp of when the switch was flipped.

    We don't have a separate ``KILL_SWITCH_SINCE_ISO`` secret in the
    runbook (operators already juggle two env vars); instead this is
    derived from a lazily-cached module-level value that captures the
    first time we observed the switch as ``1`` in the current process.
    Returns ``None`` if the switch is not active in this process.
    """
    if not _kill_switch_active():
        return None
    global _since_iso  # noqa: PLW0603 — module-local cache
    if _since_iso is None:
        _since_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return _since_iso


_since_iso: str | None = None


def _reset_kill_switch_state() -> None:
    """Test helper: clear the cached ``_since_iso``."""
    global _since_iso  # noqa: PLW0603
    _since_iso = None


class KillSwitchMiddleware(BaseHTTPMiddleware):
    """Global kill-switch — short-circuits every non-allowlisted request
    to 503 when ``KILL_SWITCH_GLOBAL=1``.

    Wired in :mod:`jpintel_mcp.api.main` as the OUTERMOST app-level
    middleware (added after telemetry → executes first in Starlette's
    LIFO stack) so a killed app never even runs DB queries / rate-limit
    bookkeeping for blocked traffic. Telemetry still sees the 503
    because we let the response bubble back through the wrapping
    middlewares.
    """

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        if not _kill_switch_active():
            return await call_next(request)

        path = request.url.path
        if path in _KILL_SWITCH_ALLOWLIST:
            return await call_next(request)

        # Audit the block. Best-effort — log_event swallows DB errors.
        try:
            from jpintel_mcp.db.session import connect

            with connect() as conn:
                log_event(
                    conn,
                    event_type="kill_switch_block",
                    request=request,
                    path=path,
                    method=request.method,
                    reason=_kill_switch_reason(),
                )
                conn.commit()
        except Exception:  # pragma: no cover — defensive
            logger.exception("kill_switch_audit_failed")

        rid = safe_request_id(request)
        envelope = make_error(
            code="service_unavailable",
            user_message=(
                "サービスが一時的に停止しています。"
                "https://jpcite.com/status/ で復旧情報を確認してください。"
            ),
            user_message_en=(
                "Service temporarily disabled. See https://jpcite.com/status/ for updates."
            ),
            request_id=rid,
            details={"retry_after": "see_status_page"},
        )
        return JSONResponse(
            status_code=503,
            content=envelope,
            headers={
                "x-request-id": rid,
                "Retry-After": "60",
            },
        )


__all__ = [
    "KillSwitchMiddleware",
    "_KILL_SWITCH_ALLOWLIST",
    "_kill_switch_active",
    "_kill_switch_reason",
    "_kill_switch_since",
    "_reset_kill_switch_state",
]
