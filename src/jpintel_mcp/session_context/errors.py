"""Wave 51 dim L — session_context error types.

The dim L module (``feedback_session_context_design``) requires that an
expired or unknown state token surface a **distinct, machine-checkable**
error rather than a bare ``KeyError`` or ``ValueError``. Callers
(REST router, MCP tool, ETL replay) all need to:

  * detect "this token is no longer valid" without string-matching;
  * emit an audit log row for compliance (the customer-LLM saw a 410
    state-token-gone response);
  * decide whether to open a fresh session or surface the error to the
    end-user agent.

Three concrete error classes are exported. They share a common base so a
single ``except SessionError`` block can catch any of them when a caller
simply wants to fall through to a "open a new session" path.
"""

from __future__ import annotations


class SessionError(Exception):
    """Base error for the dim L session surface.

    Direct instances are not raised by the module — callers catch this
    base when they want to handle any session-related failure with one
    branch. The three concrete subclasses below carry the actual signal.
    """


class SessionNotFoundError(SessionError):
    """Raised when a token does not exist in the registry.

    Distinct from :class:`SessionExpiredError`: a not-found token may be
    a typo / replay-from-old-deploy / lost-state race, whereas an
    expired token is the **expected** outcome of the 24h TTL cycle.

    Callers that observe ``SessionNotFoundError`` should NOT auto-renew
    state. The audit log row should record ``reason="token_unknown"`` so
    a post-hoc reader can tell typos and TTL expiry apart.
    """

    def __init__(self, token_id: str) -> None:
        super().__init__(f"session token not found: {token_id!r}")
        self.token_id = token_id


class SessionExpiredError(SessionError):
    """Raised when a token exists but its ``expires_at`` is in the past.

    The 24h TTL is the **defining property** of dim L; this error code
    is the contract between the session_context registry and any caller
    (REST handler, MCP tool wrapper, audit log writer). The audit log
    should record ``reason="token_expired"`` so a post-hoc reader can
    confirm the TTL floor held.
    """

    def __init__(self, token_id: str, expired_at: float) -> None:
        super().__init__(
            f"session token expired: {token_id!r} expired_at={expired_at}",
        )
        self.token_id = token_id
        self.expired_at = expired_at


class SessionPayloadError(SessionError):
    """Raised when a step payload violates the size / count caps.

    The module enforces:
      * ``MAX_STEPS`` step entries per session (default 32);
      * ``MAX_CONTEXT_BYTES`` UTF-8 byte cap on ``saved_context`` and on
        each step payload (default 16 KiB).

    A payload that violates either cap is rejected with this error so
    a caller does not silently drop data. Callers should translate to
    HTTP 413 (REST) or a structured tool error (MCP).
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


__all__ = [
    "SessionError",
    "SessionExpiredError",
    "SessionNotFoundError",
    "SessionPayloadError",
]
