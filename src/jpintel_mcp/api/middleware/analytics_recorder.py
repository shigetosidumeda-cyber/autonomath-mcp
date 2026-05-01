"""Per-request analytics recorder (P0-10, 2026-04-30).

Writes one row to ``analytics_events`` for EVERY HTTP request, including
anonymous traffic that ``log_usage()`` cannot capture (because
``usage_events.key_hash`` is NOT NULL by FK + schema constraint, and 99% of
launch-window traffic is anonymous on the 3/日 free tier).

This is intentionally separate from ``log_usage()`` / ``usage_events``:

* ``usage_events`` = authoritative billing ledger (Stripe reconciliation).
  Authenticated callers only. Failure here = under-billing.
* ``analytics_events`` = all-traffic adoption / funnel / feature-coverage
  signal. Auth + anon. Failure here = silently lower analytics counts;
  never blocks the response, never affects billing.

Failure semantics:
* The middleware NEVER raises into the request hot path. Every step is
  wrapped in a broad ``except Exception`` so a bad header / closed conn /
  missing migration never produces a 5xx.
* The DB write happens AFTER ``call_next`` returns and runs synchronously
  on a short-lived connection. Latency added to a successful response is
  ~1-2ms (one INSERT; same SQLite WAL the rest of the API writes to).

PII rules:
* Raw IP NEVER stored — hashed via ``deps.hash_ip_for_telemetry`` (same
  daily-rotated salt as ``empty_search_log.ip_hash``).
* Path is the URL path with query string stripped. Path-param values
  (T-numbers, law IDs, unified_ids) are passed through ``redact_pii`` so
  ``/v1/invoice_registrants/T8010001213708`` lands as the redacted form,
  not the raw 法人番号.
* ``key_hash`` is the existing HMAC stored in ``api_keys.key_hash`` —
  cannot be reversed to raw key material.

Deployment notes:
* Migration ``111_analytics_events.sql`` (target_db: jpintel) creates the
  table + indexes. Both ``schema.sql`` (test fixtures + dev init_db) and
  ``entrypoint.sh`` §4 (Fly prod boot) apply it idempotently.
* Wired in ``api/main.py`` near ``_QueryTelemetryMiddleware`` so it
  captures the same outermost latency.
"""
from __future__ import annotations

import contextlib
import logging
import sqlite3
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from jpintel_mcp.api.anon_limit import _client_ip
from jpintel_mcp.api.deps import hash_api_key, hash_ip_for_telemetry
from jpintel_mcp.db.session import connect
from jpintel_mcp.security.pii_redact import redact_pii

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request
    from starlette.responses import Response

_log = logging.getLogger("jpintel.analytics_recorder")

# Paths excluded from analytics recording. Health checks, OpenAPI docs,
# robots.txt, etc. would dominate the table without adding signal. Mirrors
# the same exclusion list used by `RateLimitMiddleware`.
_EXCLUDED_PATHS: frozenset[str] = frozenset({
    "/healthz",
    "/readyz",
    "/status",
    "/robots.txt",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/favicon.ico",
})


def _extract_key_hash(request: Request) -> str | None:
    """Return the HMAC key_hash for the caller, or None for anonymous.

    Mirrors the auth resolution in ``deps.require_key`` but read-only —
    we never validate / 401 here, we just record what header the caller
    presented. A bogus key returns a hash that doesn't exist in
    ``api_keys`` (ON DELETE / FK semantics: ``analytics_events.key_hash``
    is intentionally NOT a foreign key, so a stale-but-valid HMAC from a
    revoked key still records cleanly).
    """
    raw = request.headers.get("x-api-key")
    if not raw:
        auth = request.headers.get("authorization", "")
        parts = auth.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw = parts[1].strip()
    if not raw:
        return None
    try:
        return hash_api_key(raw)
    except Exception:  # noqa: BLE001 — defensive
        return None


def _record_one(
    *,
    ts: str,
    method: str,
    path: str,
    status: int,
    latency_ms: int,
    key_hash: str | None,
    anon_ip_hash: str | None,
    client_tag: str | None,
) -> None:
    """Open a short-lived SQLite connection and insert one row.

    All exceptions are swallowed — the middleware contract is
    "never block, never raise". A missing table (migration 111 not yet
    applied) surfaces as ``sqlite3.OperationalError`` and is logged at
    DEBUG, not WARNING, because the path is hot.
    """
    conn: sqlite3.Connection | None = None
    try:
        conn = connect()
        conn.execute(
            "INSERT INTO analytics_events("
            "  ts, method, path, status, latency_ms,"
            "  key_hash, anon_ip_hash, client_tag, is_anonymous"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (
                ts,
                method,
                path,
                status,
                latency_ms,
                key_hash,
                anon_ip_hash,
                client_tag,
                1 if key_hash is None else 0,
            ),
        )
    except sqlite3.OperationalError as exc:
        _log.debug("analytics_events insert skipped (likely missing migration): %s", exc)
    except Exception as exc:  # noqa: BLE001 — defensive
        _log.debug("analytics_events insert failed: %s", exc)
    finally:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()


class AnalyticsRecorderMiddleware(BaseHTTPMiddleware):
    """Insert one ``analytics_events`` row per HTTP request.

    Placement in ``main.py``: outer-ish (executes early in the LIFO
    stack so it captures the full latency, but inside CORS / kill switch
    so a CORS-rejected preflight doesn't generate a row).
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip excluded paths immediately — saves 1-2ms per health probe
        # and keeps the table from being dominated by /healthz noise.
        path = request.url.path
        if path in _EXCLUDED_PATHS:
            return await call_next(request)

        t0 = monotonic()
        status_code = 500  # default if call_next raises
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            latency_ms = int((monotonic() - t0) * 1000)
            try:
                key_hash = _extract_key_hash(request)
                anon_ip_hash: str | None = None
                if key_hash is None:
                    raw_ip = _client_ip(request)
                    anon_ip_hash = hash_ip_for_telemetry(raw_ip)

                client_tag = getattr(request.state, "client_tag", None)
                redacted_path = redact_pii(path) if path else path
                _record_one(
                    ts=datetime.now(UTC).isoformat(),
                    method=request.method,
                    path=redacted_path,
                    status=status_code,
                    latency_ms=latency_ms,
                    key_hash=key_hash,
                    anon_ip_hash=anon_ip_hash,
                    client_tag=client_tag,
                )
            except Exception as exc:  # noqa: BLE001 — never block
                _log.debug("analytics_recorder dispatch swallowed exc: %s", exc)


__all__ = ["AnalyticsRecorderMiddleware"]
