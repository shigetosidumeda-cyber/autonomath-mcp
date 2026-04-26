"""MCP tool wrapper for the deep health check.

Exposes ``deep_health_am`` so any client can introspect production
liveness without scraping the REST endpoint.
"""

from __future__ import annotations

import logging

from jpintel_mcp.api._health_deep import get_deep_health
from jpintel_mcp.mcp._error_helpers import safe_internal_message
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.am.health")


@mcp.tool(annotations=_READ_ONLY)
def deep_health_am() -> dict[str, object]:
    """Aggregate health: 10 checks across both DBs + static bundle.

    Status is ``ok`` / ``degraded`` / ``unhealthy``. Always returns a document —
    never raises — so callers can use it as a heartbeat. Mirrors the REST
    endpoint ``/v1/am/health/deep`` so MCP clients can introspect liveness
    without scraping HTTP.

    Example:
        deep_health_am()
        → {"status": "ok", "checks": [{"name": "jpintel_db", "ok": true, ...}, ...]}

    When NOT to call:
        - As a substitute for real data tools — health says "DB reachable",
          NOT "your query has results". Use search_* / get_* for content.
        - To verify a SINGLE table's integrity → run a targeted SELECT instead.
        - On every user request — heartbeat is for monitoring, not per-call gating.
    """
    try:
        return get_deep_health()
    except Exception as exc:
        msg, _ = safe_internal_message(
            exc, logger=logger, tool_name="deep_health_am"
        )
        return make_error("internal", msg)
