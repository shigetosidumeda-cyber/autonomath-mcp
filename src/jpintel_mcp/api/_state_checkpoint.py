"""Boundary state checkpoint helper (Wave 43.3.6 — AX Resilience cell 6).

Why this exists
---------------
Long-running multi-step workflows (cohort fan-out, NTA bulk ingest,
compose_audit_workpaper) survive Fly machine swaps (~25s p99) and
SIGTERM mid-stream only if they record their progress at idempotent
boundaries. Without checkpoints, a swap mid-step forces full restart
— wastes ¥/req on already-completed steps, breaks 税理士 audit-seal
chain continuity, and (worst case) double-fires customer webhooks.

The pattern is mechanical:

    from jpintel_mcp.api._state_checkpoint import StateCheckpoint
    ck = StateCheckpoint(conn, workflow_id="ULID-xyz",
                        workflow_kind="cohort_fanout")

    if ck.is_done("fetch_corpus"):
        corpus = ck.load_state("fetch_corpus")["corpus"]
    else:
        corpus = expensive_fetch()
        ck.commit("fetch_corpus", {"corpus": corpus})

    if not ck.is_done("score"):
        scores = score(corpus)
        ck.commit("score", {"scores": scores})

The schema (migration 268) keeps a row per (workflow_id, step_index)
so the audit trail survives. The 30-day cleanup sweep lives in
`scripts/cron/dlq_drain.py` (cell 4 + 6 share cron infrastructure).

Constraints
-----------
- No Anthropic / claude / SDK calls. Pure SQLite + stdlib.
- Idempotent: re-committing the same (workflow_id, step_name) replaces
  the state_blob via ON CONFLICT.
- The helper is connection-bound; callers manage their own
  transactional envelope.
"""

from __future__ import annotations

import json
import logging
import sqlite3  # noqa: TC003 — runtime type (connection) + IntegrityError catch
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("jpintel.state_checkpoint")

# Maximum state_blob size we accept (bytes). Larger blobs are an
# anti-pattern (checkpoint should reference work artifacts, not embed
# them). 256 KB matches the replay-token cap so a single connection
# never inflates beyond a known bound.
_MAX_STATE_BLOB_BYTES = 256 * 1024

# Allowed status values must match the migration 268 CHECK constraint.
_STATUSES = frozenset({"committed", "aborted", "expired"})


def _now_iso() -> str:
    """ISO 8601 millisecond UTC stamp matching the SQLite default."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class StateCheckpoint:
    """Connection-bound checkpoint helper for a single workflow.

    A new instance per workflow_id keeps the call sites readable
    without leaking workflow ids across boundary writes. The helper
    does NOT manage its own transaction — the caller wraps as needed.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        workflow_id: str,
        workflow_kind: str,
        default_ttl_seconds: int | None = None,
    ) -> None:
        if not workflow_id or not isinstance(workflow_id, str):
            raise ValueError("workflow_id must be a non-empty string")
        if not workflow_kind or not isinstance(workflow_kind, str):
            raise ValueError("workflow_kind must be a non-empty string")
        if len(workflow_id) > 64:
            raise ValueError("workflow_id must be <= 64 chars")
        if len(workflow_kind) > 64:
            raise ValueError("workflow_kind must be <= 64 chars")
        self.conn = conn
        self.workflow_id = workflow_id
        self.workflow_kind = workflow_kind
        self.default_ttl_seconds = default_ttl_seconds
        # Step index counter is monotonic-per-workflow. We read the
        # current max once at construction and bump locally; the
        # UNIQUE(workflow_id, step_index) constraint catches any race.
        self._next_step_index = self._read_next_step_index()

    def _read_next_step_index(self) -> int:
        cur = self.conn.execute(
            "SELECT COALESCE(MAX(step_index), -1) + 1 FROM am_state_checkpoint "
            "WHERE workflow_id = ?",
            (self.workflow_id,),
        )
        row = cur.fetchone()
        return int(row[0]) if row is not None else 0

    def _expires_iso(self, ttl_seconds: int | None) -> str | None:
        if ttl_seconds is None and self.default_ttl_seconds is None:
            return None
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        if ttl is None or ttl <= 0:
            return None
        when = datetime.now(UTC) + timedelta(seconds=ttl)
        return when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"

    def commit(
        self,
        step_name: str,
        state: dict[str, Any] | list[Any] | None = None,
        *,
        ttl_seconds: int | None = None,
        notes: str | None = None,
    ) -> int:
        """Commit a step. Returns the step_index assigned.

        If a row with the same (workflow_id, step_name) already
        exists (re-commit after partial success), the state_blob is
        replaced and the existing step_index is returned — keeps
        the resume-after-swap path idempotent.
        """
        if not step_name or not isinstance(step_name, str):
            raise ValueError("step_name must be a non-empty string")
        if len(step_name) > 128:
            raise ValueError("step_name must be <= 128 chars")
        # Look up existing step by name (UNIQUE(workflow_id, step_index)
        # not step_name, so we have to query).
        existing = self.conn.execute(
            "SELECT step_index FROM am_state_checkpoint WHERE workflow_id = ? AND step_name = ?",
            (self.workflow_id, step_name),
        ).fetchone()

        try:
            state_text = json.dumps(
                state if state is not None else {}, ensure_ascii=False, default=str
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"state blob not JSON-serializable: {exc}") from exc
        if len(state_text.encode("utf-8")) > _MAX_STATE_BLOB_BYTES:
            raise ValueError(
                f"state blob exceeds {_MAX_STATE_BLOB_BYTES} bytes; "
                "checkpoints should reference work artifacts, not embed them"
            )

        if existing is not None:
            step_index = int(existing[0])
            self.conn.execute(
                """
                UPDATE am_state_checkpoint
                SET state_blob = ?,
                    status = 'committed',
                    committed_at = ?,
                    expires_at = ?,
                    notes = COALESCE(?, notes)
                WHERE workflow_id = ? AND step_index = ?
                """,
                (
                    state_text,
                    _now_iso(),
                    self._expires_iso(ttl_seconds),
                    notes,
                    self.workflow_id,
                    step_index,
                ),
            )
            return step_index

        step_index = self._next_step_index
        self._next_step_index += 1
        self.conn.execute(
            """
            INSERT INTO am_state_checkpoint
                (workflow_id, workflow_kind, step_index, step_name,
                 state_blob, status, committed_at, expires_at, notes)
            VALUES (?, ?, ?, ?, ?, 'committed', ?, ?, ?)
            """,
            (
                self.workflow_id,
                self.workflow_kind,
                step_index,
                step_name,
                state_text,
                _now_iso(),
                self._expires_iso(ttl_seconds),
                notes,
            ),
        )
        return step_index

    def is_done(self, step_name: str) -> bool:
        """Return True if a committed checkpoint exists for step_name."""
        cur = self.conn.execute(
            "SELECT 1 FROM am_state_checkpoint "
            "WHERE workflow_id = ? AND step_name = ? AND status = 'committed' "
            "LIMIT 1",
            (self.workflow_id, step_name),
        )
        return cur.fetchone() is not None

    def load_state(self, step_name: str) -> dict[str, Any] | None:
        """Return the parsed state_blob for step_name, or None if missing."""
        cur = self.conn.execute(
            "SELECT state_blob FROM am_state_checkpoint "
            "WHERE workflow_id = ? AND step_name = ? AND status = 'committed' "
            "ORDER BY step_index DESC LIMIT 1",
            (self.workflow_id, step_name),
        )
        row = cur.fetchone()
        if row is None:
            return None
        try:
            parsed = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(parsed, dict):
            # We promise dict on the type alias; lists / scalars are
            # an unusual shape and should not silently break callers.
            return None
        return parsed

    def latest_step(self) -> dict[str, Any] | None:
        """Return summary of the latest committed step (or None)."""
        cur = self.conn.execute(
            "SELECT step_index, step_name, committed_at "
            "FROM am_state_checkpoint "
            "WHERE workflow_id = ? AND status = 'committed' "
            "ORDER BY step_index DESC LIMIT 1",
            (self.workflow_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "step_index": int(row[0]),
            "step_name": row[1],
            "committed_at": row[2],
        }

    def abort(self, reason: str | None = None) -> int:
        """Flip all remaining 'committed' steps to status='aborted'.

        Returns the count flipped. Use when the workflow encountered
        an unrecoverable error and you want the audit trail to reflect
        the abort (rather than silently leaving the last step as
        committed and never resuming).
        """
        notes_suffix = f" [aborted: {reason}]" if reason else " [aborted]"
        cur = self.conn.execute(
            """
            UPDATE am_state_checkpoint
            SET status = 'aborted',
                notes = COALESCE(notes, '') || ?
            WHERE workflow_id = ? AND status = 'committed'
            """,
            (notes_suffix, self.workflow_id),
        )
        return cur.rowcount or 0


def expire_overdue(conn: sqlite3.Connection) -> int:
    """Flip rows past expires_at to status='expired'. Returns count flipped."""
    cur = conn.execute(
        """
        UPDATE am_state_checkpoint
        SET status = 'expired'
        WHERE status = 'committed'
          AND expires_at IS NOT NULL
          AND expires_at < ?
        """,
        (_now_iso(),),
    )
    return cur.rowcount or 0


__all__ = ["StateCheckpoint", "expire_overdue"]
