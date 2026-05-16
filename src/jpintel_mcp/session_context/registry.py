"""Wave 51 dim L — file-backed session registry (state/sessions/<token>.json).

The :class:`SessionRegistry` persists each :class:`SavedContext` row as
a self-contained JSON file under ``state/sessions/`` (or any caller-
supplied root). One file per session means:

  * a process restart on Fly does not lose mid-flight conversations
    that were opened in the last 24h;
  * a post-hoc auditor can ``ls state/sessions/ | wc -l`` to confirm
    the live cohort without an extra index file;
  * the registry can be inspected (or surgically expired) with stdlib
    JSON tools — no Redis / sqlite operator overhead per memo
    ``feedback_zero_touch_solo``.

The three public entry points
-----------------------------
* :func:`open_session(subject_id, current_state)` — issue a fresh
  state token + persist an empty step history.
* :func:`step_session(token_id, action, payload)` — append one turn
  to the open session and return the updated SavedContext.
* :func:`close_session(token_id)` — read the final snapshot and
  delete the on-disk row. Second close on the same token is a no-op
  raise of :class:`SessionNotFoundError` (audit logged).

NO LLM imports, NO HTTP imports — pure file IO + ``json`` stdlib.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Final

from .errors import (
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

logger = logging.getLogger("jpintel.session_context.registry")

# Default disk root. Lives at repo-root ``state/sessions/`` so Fly
# volume + GHA runner + dev shell all share a stable path. Callers
# override via ``SessionRegistry(root=...)``.
DEFAULT_REGISTRY_ROOT: Final[Path] = Path("state") / "sessions"


def new_token_id() -> str:
    """Generate a 32-hex-char token.

    Uses :func:`secrets.token_hex(16)` so the token is generated from
    the OS CSPRNG, matching the existing REST surface. Returning a
    stable shape (hex32) means the file-backed and in-process
    registries are byte-equivalent on the wire.
    """
    return secrets.token_hex(16)


def _utf8_size(payload: dict[str, Any]) -> int:
    """Estimate the UTF-8 byte size of a JSON-encoded dict.

    Used to enforce :data:`MAX_CONTEXT_BYTES`. We never persist a row
    whose serialised form would exceed the cap, so the on-disk file
    size is always bounded.
    """
    try:
        return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        # An un-serialisable payload counts as oversize so the caller
        # gets a deterministic rejection instead of a write-time crash.
        return MAX_CONTEXT_BYTES + 1


class SessionRegistry:
    """File-backed registry for dim L sessions.

    One JSON file per token_id under ``<root>/<token_id>.json``. A
    process-level :class:`threading.Lock` serialises writes so two
    concurrent ``step_session`` calls on the same token cannot lose an
    update. Concurrent **different** tokens fan out across separate
    files and remain safe under the lock because each branch operates
    on its own path.
    """

    def __init__(self, *, root: Path | str | None = None) -> None:
        self.root: Path = Path(root) if root is not None else DEFAULT_REGISTRY_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _path_for(self, token_id: str) -> Path:
        # Hex32 validation up-front prevents directory traversal —
        # ``../`` cannot survive a hex-only character class.
        if (
            not token_id
            or len(token_id) != 32
            or not all(c in "0123456789abcdef" for c in token_id)
        ):
            raise SessionPayloadError(
                code="invalid_token_id",
                detail="token_id must be 32 lowercase hex chars",
            )
        return self.root / f"{token_id}.json"

    def _load(self, token_id: str) -> SavedContext:
        """Read a SavedContext from disk; raises if missing or expired."""
        path = self._path_for(token_id)
        if not path.exists():
            raise SessionNotFoundError(token_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            # A corrupt row is treated as not-found for the caller's
            # purposes; the audit log will surface the corruption.
            logger.warning(
                "session_context: corrupt row %s (%s) — treating as not_found",
                token_id,
                exc,
            )
            raise SessionNotFoundError(token_id) from exc
        ctx = SavedContext.model_validate(raw)
        if ctx.is_expired():
            # Audit-log line then propagate. We delete the on-disk row
            # so a follow-up open_session for the same subject does not
            # trip over the stale file.
            logger.info(
                "session_context: token expired %s expired_at=%s",
                token_id,
                ctx.expires_at,
            )
            self._delete_if_exists(token_id)
            raise SessionExpiredError(token_id, ctx.expires_at)
        return ctx

    def _write(self, ctx: SavedContext) -> None:
        """Atomically persist a SavedContext to disk.

        Writes go to ``<token>.json.tmp`` then ``os.replace`` to the
        final name so a crash mid-write cannot leave a half-row that
        :func:`_load` would treat as corrupt. ``os.replace`` is the
        POSIX-rename guarantee (atomic on the same filesystem).
        """
        path = self._path_for(ctx.token_id)
        tmp = path.with_suffix(".json.tmp")
        body = ctx.model_dump_json()
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)

    def _delete_if_exists(self, token_id: str) -> None:
        try:
            path = self._path_for(token_id)
        except SessionPayloadError:
            return
        try:
            path.unlink()
        except FileNotFoundError:
            return

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_session(
        self,
        *,
        subject_id: str,
        current_state: dict[str, Any] | None = None,
    ) -> SessionToken:
        """Issue a new state token and persist an empty session row.

        Parameters
        ----------
        subject_id:
            Caller-supplied opaque id (API key id, agent run id, ...).
            NEVER PII — the caller is responsible for normalising
            upstream per dim N redact rules.
        current_state:
            Initial saved-context payload. Capped at
            :data:`MAX_CONTEXT_BYTES`. Defaults to an empty dict.

        Returns
        -------
        SessionToken
            The freshly issued token (32 hex chars, 24h TTL).

        Raises
        ------
        SessionPayloadError
            If ``current_state`` exceeds :data:`MAX_CONTEXT_BYTES` or
            ``subject_id`` is empty / oversized.
        """
        if not subject_id or len(subject_id) > 128:
            raise SessionPayloadError(
                code="invalid_subject_id",
                detail="subject_id must be 1..128 chars",
            )
        state = dict(current_state or {})
        if _utf8_size(state) > MAX_CONTEXT_BYTES:
            raise SessionPayloadError(
                code="saved_context_too_large",
                detail=f"current_state exceeds {MAX_CONTEXT_BYTES} bytes",
            )
        now = time.time()
        token_id = new_token_id()
        expires_at = now + SESSION_TTL_SEC
        ctx = SavedContext(
            token_id=token_id,
            subject_id=subject_id,
            created_at=now,
            expires_at=expires_at,
            current_state=state,
            step_history=[],
        )
        with self._lock:
            self._write(ctx)
        return SessionToken(
            token_id=token_id,
            subject_id=subject_id,
            created_at=now,
            expires_at=expires_at,
        )

    def step_session(
        self,
        token_id: str,
        *,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> SavedContext:
        """Append one step to an open session.

        Parameters
        ----------
        token_id:
            Token returned by :func:`open_session`. 32 hex chars.
        action:
            Short stable identifier of the agent's action (e.g.
            ``"search_programs"``, ``"narrow_industry"``). Capped at
            64 chars so a single step entry stays well under
            :data:`MAX_CONTEXT_BYTES`.
        payload:
            Per-step payload to record. Capped at
            :data:`MAX_CONTEXT_BYTES`. Defaults to an empty dict.

        Returns
        -------
        SavedContext
            The updated context (with the new step appended).

        Raises
        ------
        SessionNotFoundError
            Token does not exist on disk.
        SessionExpiredError
            Token's TTL has lapsed (on-disk row deleted as a side
            effect so the same token cannot be replayed).
        SessionPayloadError
            ``action`` is empty / oversize, ``payload`` exceeds the
            byte cap, or the step cap (:data:`MAX_STEPS`) is full.
        """
        if not action or len(action) > 64:
            raise SessionPayloadError(
                code="invalid_action",
                detail="action must be 1..64 chars",
            )
        step_payload = dict(payload or {})
        if _utf8_size(step_payload) > MAX_CONTEXT_BYTES:
            raise SessionPayloadError(
                code="step_payload_too_large",
                detail=f"payload exceeds {MAX_CONTEXT_BYTES} bytes",
            )
        with self._lock:
            ctx = self._load(token_id)
            if ctx.steps_count() >= MAX_STEPS:
                raise SessionPayloadError(
                    code="step_cap_exceeded",
                    detail=f"max {MAX_STEPS} steps per session",
                )
            ctx.step_history.append(
                {
                    "at": time.time(),
                    "action": action,
                    "data": step_payload,
                }
            )
            self._write(ctx)
        return ctx

    def close_session(self, token_id: str) -> SavedContext:
        """Return the final snapshot and delete the on-disk row.

        Idempotency: a second close on the same token raises
        :class:`SessionNotFoundError`. Tests assert this so an audit
        log reader can confirm that the token is single-use after
        close.

        Parameters
        ----------
        token_id:
            Token returned by :func:`open_session`.

        Returns
        -------
        SavedContext
            The terminal context (including the full step history).

        Raises
        ------
        SessionNotFoundError
            Token does not exist (e.g. already closed, never opened).
        SessionExpiredError
            Token's TTL has lapsed.
        """
        with self._lock:
            ctx = self._load(token_id)
            self._delete_if_exists(token_id)
        return ctx

    # Convenience surface --------------------------------------------------

    def get_context(self, token_id: str) -> SavedContext:
        """Read a SavedContext without mutating it.

        Useful for read-only audit / debug paths. Same error contract
        as :func:`step_session` (404 / 410) so a caller can probe a
        token's liveness without recording a step.
        """
        with self._lock:
            return self._load(token_id)

    def list_active_tokens(self) -> list[str]:
        """Return live (non-expired) token_ids currently on disk.

        Walks ``<root>/*.json`` and filters out expired rows. NOT a hot
        path — intended for ops introspection. Bounded by the on-disk
        file count, which is bounded by the 24h TTL × open rate.
        """
        out: list[str] = []
        for path in self.root.glob("*.json"):
            token_id = path.stem
            try:
                ctx = self._load(token_id)
            except (SessionNotFoundError, SessionExpiredError):
                continue
            except SessionPayloadError:
                continue
            out.append(ctx.token_id)
        return out

    def purge_expired(self) -> int:
        """Delete every expired row under ``root``.

        Returns the count purged. Intended for a periodic cron task —
        running it never blocks the open / step / close hot paths.
        """
        purged = 0
        for path in list(self.root.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                ctx = SavedContext.model_validate(raw)
            except (json.JSONDecodeError, ValueError):
                # Corrupt rows count as purgeable garbage.
                with self._lock:
                    try:
                        path.unlink()
                        purged += 1
                    except FileNotFoundError:
                        pass
                continue
            if ctx.is_expired():
                with self._lock:
                    try:
                        path.unlink()
                        purged += 1
                    except FileNotFoundError:
                        pass
        return purged


# ---------------------------------------------------------------------
# Module-level convenience wrappers — let callers use the default
# registry root without instantiating SessionRegistry explicitly.
# ---------------------------------------------------------------------

_DEFAULT_REGISTRY: SessionRegistry | None = None
_DEFAULT_LOCK = threading.Lock()


def _default_registry() -> SessionRegistry:
    global _DEFAULT_REGISTRY
    with _DEFAULT_LOCK:
        if _DEFAULT_REGISTRY is None:
            _DEFAULT_REGISTRY = SessionRegistry()
        return _DEFAULT_REGISTRY


def open_session(
    *,
    subject_id: str,
    current_state: dict[str, Any] | None = None,
) -> SessionToken:
    """Convenience wrapper around the default :class:`SessionRegistry`."""
    return _default_registry().open_session(
        subject_id=subject_id,
        current_state=current_state,
    )


def step_session(
    token_id: str,
    *,
    action: str,
    payload: dict[str, Any] | None = None,
) -> SavedContext:
    """Convenience wrapper around the default :class:`SessionRegistry`."""
    return _default_registry().step_session(
        token_id, action=action, payload=payload
    )


def close_session(token_id: str) -> SavedContext:
    """Convenience wrapper around the default :class:`SessionRegistry`."""
    return _default_registry().close_session(token_id)


__all__ = [
    "DEFAULT_REGISTRY_ROOT",
    "SessionRegistry",
    "close_session",
    "new_token_id",
    "open_session",
    "step_session",
]
