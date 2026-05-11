"""Lightweight observability helpers (Sentry, cost alert, SLO probes).

This package is intentionally narrow — heavy lifting (PII scrubbing,
metric export) lives next to the HTTP edge in `jpintel_mcp.api.*`. The
helpers here are pure functions / no-side-effect wrappers so they can be
imported from cron scripts (`scripts/cron/*`) without dragging the
FastAPI app graph along.

See `docs/observability.md` (operator-only, excluded from public docs)
for the full alert / SLO matrix.
"""

from __future__ import annotations

from jpintel_mcp.observability.cron_heartbeat import heartbeat
from jpintel_mcp.observability.otel import (
    current_trace_id,
    init_otel,
    instrument_fastapi,
)
from jpintel_mcp.observability.sentry import (
    is_sentry_active,
    safe_capture_exception,
    safe_capture_message,
)

__all__ = [
    "current_trace_id",
    "heartbeat",
    "init_otel",
    "instrument_fastapi",
    "is_sentry_active",
    "safe_capture_exception",
    "safe_capture_message",
]
