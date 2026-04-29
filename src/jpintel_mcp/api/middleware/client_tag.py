"""X-Client-Tag header middleware (税理士 顧問先 attribution).

税理士事務所 (tax accountant offices) wiring AutonoMath into their back-end
need to attribute API consumption to individual 顧問先 (client firms) for
invoice line-item passthrough. Without per-call attribution the accountant
must allocate ¥3/req across an opaque pool — that is a bookkeeping stopper
for the segment.

Contract:

* Header name:  ``X-Client-Tag``
* Max length:   32 chars (server-validated, longer values are silently
  dropped — never 4xx, because attribution is metadata-only and a malformed
  tag must not block the actual request).
* Charset:      ``[A-Za-z0-9_-]`` (alphanumeric, hyphen, underscore). Same
  rationale as length: anything else is silently dropped.
* Required?     No. Absent header == NULL ``client_tag`` in usage_events.

The validated tag is stashed onto ``request.state.client_tag`` so
``api/deps.log_usage`` can pick it up at write time and forward to the new
``usage_events.client_tag`` column (migration 085). Aggregations are exposed
via ``GET /v1/me/usage?group_by=client_tag`` and the matching CSV export.

Anonymous callers:
  An anonymous caller (no X-API-Key, no Authorization: Bearer) can also
  pass X-Client-Tag — but ``log_usage`` returns early for anon callers
  (key_hash is None), so the tag is dropped on the floor. This is fine:
  an accountant exclusively uses authenticated keys.

Failure posture:
  Header parsing never raises into the request hot path. A malformed
  header is silently treated as absent. The middleware is the world's
  cheapest 22-line wrapper — its failure budget is "never block".
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request
    from starlette.responses import Response

_log = logging.getLogger("jpintel.client_tag")

# Match the migration 085 / docs contract exactly. Anchored, so substring
# matches that include forbidden characters are rejected.
_TAG_MAX_LEN = 32
_TAG_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_client_tag(raw: str | None) -> str | None:
    """Return a sanitized client_tag, or None when the input is invalid/absent.

    Rules (all must pass to return non-None):
      * non-empty after .strip()
      * length <= _TAG_MAX_LEN
      * matches ``[A-Za-z0-9_-]+`` (no whitespace, no slashes, no Unicode)

    Any failure returns None — same as "header was absent". This is the
    silent-drop posture documented in the module docstring; we never 4xx
    on attribution metadata.
    """
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if len(cleaned) > _TAG_MAX_LEN:
        return None
    if not _TAG_RE.fullmatch(cleaned):
        return None
    return cleaned


class ClientTagMiddleware(BaseHTTPMiddleware):
    """Stash X-Client-Tag onto request.state.client_tag (or None).

    Reads ``X-Client-Tag`` from the request, validates the shape via
    ``validate_client_tag``, and assigns the result to
    ``request.state.client_tag``. Downstream code (``api/deps.log_usage``)
    reads that attribute and forwards to the new ``usage_events.client_tag``
    column.

    Always sets the attribute (to None when absent/invalid) so the
    downstream read site never has to ``getattr(..., default=None)`` —
    the contract is "this attribute always exists after the middleware".
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            raw = request.headers.get("x-client-tag")
            request.state.client_tag = validate_client_tag(raw)
        except Exception:  # pragma: no cover — defensive
            _log.warning("client_tag header parse failed", exc_info=True)
            request.state.client_tag = None
        return await call_next(request)


__all__ = ["ClientTagMiddleware", "validate_client_tag"]
