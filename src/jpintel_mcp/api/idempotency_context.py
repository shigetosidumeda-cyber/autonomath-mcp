"""Request-local billing idempotency context.

The HTTP Idempotency-Key middleware owns request replay. Billing code lives
deeper in route handlers, so we pass a stable logical-request key through a
ContextVar instead of threading another argument through every endpoint.
"""

from __future__ import annotations

from contextvars import ContextVar

billing_idempotency_key: ContextVar[str | None] = ContextVar(
    "billing_idempotency_key",
    default=None,
)

billing_event_index: ContextVar[int] = ContextVar(
    "billing_event_index",
    default=0,
)
