"""Wave 51 dim L — Contextual session module (file-backed, 24h TTL).

Stateless → multi-turn transition surface for agent loops. This package
is the **reusable, router-agnostic** core for the dim L design described
in ``feedback_session_context_design``:

    * agents need to resume a multi-turn intent without re-explaining
      every filter / preference each call;
    * state token + saved_context + 3-endpoint pattern
      (open / step / close) is the canonical shape per the memo;
    * file-backed persistence under ``state/sessions/<token_id>.json``
      survives process restarts within the 24h TTL window.

A separate **REST surface** lives at
``src/jpintel_mcp/api/session_context.py`` (in-process LRU). This
package complements it by adding a **file-backed** persistence layer
that any caller (REST handler, MCP tool, ETL replay, operator script)
can share without depending on the FastAPI router internals or an
external store (Redis / sqlite).

Public surface
--------------
    SESSION_TTL_SEC          — module constant (86400 sec). NEVER lower.
    MAX_CONTEXT_BYTES        — 16 KiB cap on each payload.
    MAX_STEPS                — 32 step entries per session.
    SessionToken             — Pydantic model returned by open_session.
    SavedContext             — Pydantic model returned by step/close.
    SessionRegistry          — file-backed primitive.
    open_session(...)        — module-level convenience wrapper.
    step_session(...)        — module-level convenience wrapper.
    close_session(...)       — module-level convenience wrapper.
    SessionError             — base error class.
    SessionNotFoundError     — raised when a token is missing.
    SessionExpiredError      — raised when the TTL has lapsed.
    SessionPayloadError      — raised on size / count cap violations.

Non-goals
---------
* Does NOT call any LLM API or external HTTP endpoint.
* Does NOT mount a FastAPI router (see ``api/session_context.py`` for
  the REST surface).
* Does NOT replace the in-process REST surface — both implementations
  share the 24h TTL contract so a future migration is additive.
"""

from __future__ import annotations

from .errors import (
    SessionError,
    SessionExpiredError,
    SessionNotFoundError,
    SessionPayloadError,
)
from .models import (
    MAX_CONTEXT_BYTES,
    MAX_STEPS,
    SESSION_TTL_SEC,
    SavedContext,
    SessionToken,
)
from .registry import (
    DEFAULT_REGISTRY_ROOT,
    SessionRegistry,
    close_session,
    new_token_id,
    open_session,
    step_session,
)

__all__ = [
    "DEFAULT_REGISTRY_ROOT",
    "MAX_CONTEXT_BYTES",
    "MAX_STEPS",
    "SESSION_TTL_SEC",
    "SavedContext",
    "SessionError",
    "SessionExpiredError",
    "SessionNotFoundError",
    "SessionPayloadError",
    "SessionRegistry",
    "SessionToken",
    "close_session",
    "new_token_id",
    "open_session",
    "step_session",
]
