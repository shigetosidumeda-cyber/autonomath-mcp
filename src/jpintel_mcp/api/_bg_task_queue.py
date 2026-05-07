"""Durable background-task queue (migration 060).

FastAPI BackgroundTasks are in-memory only. A SIGTERM between enqueue and
execute (rolling deploy, Fly machine replace, OOM) drops the task silently.
For things like the D+0 welcome email — which is the ONE mail carrying the
raw API key — that means the customer paid, the key issued, and the customer
never sees the key. 詐欺 / 景表法 risk.

`bg_task_queue` (created by 060_bg_task_queue.sql) gives us the durability
contract:

  enqueue(conn, kind, payload, dedup_key=None, run_at=None) -> int
      Persist a task. Returns the row id. ON CONFLICT(dedup_key) DO NOTHING
      so a Stripe webhook retry (which Stripe does for ~3d on 5xx) does not
      double-dispatch.

  claim_next(conn) -> Optional[Row]
      Pull the oldest pending-and-due row, atomically flipping its status
      to 'processing'. Wrapped in BEGIN IMMEDIATE so two workers (e.g. a
      future scaling event with multiple machines) cannot race the same row.

  mark_done(conn, task_id)
      Flip 'processing' -> 'done'. Idempotent.

  mark_failed(conn, task_id, error, retry_after_s=None)
      Increment attempts. If attempts < max_attempts, schedule retry with
      exponential backoff (60s * 2^attempts, cap 1h). Else flip to 'failed'
      so an operator can spot it via SQL.

The worker (`_bg_task_worker.py`) polls every 2s and dispatches by `kind`.

This module is intentionally framework-free — it takes a sqlite3.Connection
explicitly so tests can inject a temp-DB connection without spinning up
the FastAPI app.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("jpintel.bg_task_queue")

# Backoff: 60s, 120s, 240s, 480s, 960s, ..., capped at 3600s (1h). After
# max_attempts (default 5) attempts the task flips to 'failed'.
_BACKOFF_BASE_S = 60
_BACKOFF_CAP_S = 3600


def _now_iso() -> str:
    """Wall-clock UTC, ISO 8601 with millisecond precision + Z suffix.

    Matches the `strftime('%Y-%m-%dT%H:%M:%fZ', 'now')` shape SQLite
    produces in the migration's DEFAULT clause so timestamps from Python
    inserts and SQLite-default inserts sort lexicographically together.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{datetime.now(UTC).microsecond // 1000:03d}Z"
    )


def enqueue(
    conn: sqlite3.Connection,
    kind: str,
    payload: dict[str, Any],
    dedup_key: str | None = None,
    run_at: datetime | None = None,
    max_attempts: int = 5,
) -> int:
    """Persist a task. Returns the inserted-or-existing row id.

    `dedup_key` is the idempotency contract: if provided and a row with
    the same key already exists, the existing id is returned and no new
    row is created. Use it when the caller (e.g. a webhook handler) might
    legitimately fire twice for the same logical event.

    `run_at` defers first execution. None = run as soon as the worker picks
    up. Used for retries from `mark_failed` and could be used for delayed
    reminders later.
    """
    now = _now_iso()
    if run_at is None:
        next_at = now
    else:
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=UTC)
        next_at = (
            run_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{run_at.astimezone(UTC).microsecond // 1000:03d}Z"
        )

    payload_str = json.dumps(payload, ensure_ascii=False, default=str)

    if dedup_key is not None:
        # ON CONFLICT(dedup_key) DO NOTHING — but `RETURNING id` only fires
        # when a row was actually inserted (sqlite >= 3.35). Fall back to
        # SELECT for the conflict path.
        try:
            cur = conn.execute(
                """INSERT INTO bg_task_queue
                       (kind, payload_json, status, attempts, max_attempts,
                        updated_at, next_attempt_at, dedup_key)
                   VALUES (?, ?, 'pending', 0, ?, ?, ?, ?)
                   ON CONFLICT(dedup_key) DO NOTHING
                   RETURNING id""",
                (kind, payload_str, max_attempts, now, next_at, dedup_key),
            )
            row = cur.fetchone()
            if row is not None:
                return int(row[0])
        except sqlite3.OperationalError:
            # Older sqlite without RETURNING: fall through to the explicit
            # path so the conflict still short-circuits to existing id.
            with contextlib.suppress(sqlite3.IntegrityError):
                conn.execute(
                    """INSERT INTO bg_task_queue
                           (kind, payload_json, status, attempts, max_attempts,
                            updated_at, next_attempt_at, dedup_key)
                       VALUES (?, ?, 'pending', 0, ?, ?, ?, ?)
                       ON CONFLICT(dedup_key) DO NOTHING""",
                    (kind, payload_str, max_attempts, now, next_at, dedup_key),
                )

        existing = conn.execute(
            "SELECT id FROM bg_task_queue WHERE dedup_key = ?", (dedup_key,)
        ).fetchone()
        if existing is None:
            # Should never happen — both branches above are no-op only on
            # an existing row. Surface as RuntimeError so a regression in
            # the conflict path is loud.
            raise RuntimeError(
                f"bg_task_queue.enqueue: dedup row vanished kind={kind} dedup_key={dedup_key!r}"
            )
        return int(existing[0])

    # No dedup: plain INSERT. lastrowid is the id.
    cur = conn.execute(
        """INSERT INTO bg_task_queue
               (kind, payload_json, status, attempts, max_attempts,
                updated_at, next_attempt_at)
           VALUES (?, ?, 'pending', 0, ?, ?, ?)""",
        (kind, payload_str, max_attempts, now, next_at),
    )
    return int(cur.lastrowid or 0)


def claim_next(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Atomically claim the oldest due-and-pending task.

    Two phases inside BEGIN IMMEDIATE so a multi-process / multi-worker
    deployment (post-launch scale) cannot race the same row:
      1. SELECT pending+due ORDER BY next_attempt_at LIMIT 1
      2. UPDATE status='processing', updated_at=now() WHERE id=? AND status='pending'

    The WHERE-clause `status='pending'` on the UPDATE is the actual
    serialization guard: if a competing transaction already flipped the
    same row to 'processing', our UPDATE matches 0 rows and we return None.
    BEGIN IMMEDIATE alone is not enough — SQLite shares reader snapshots
    so two workers could SELECT the same id; the conditional UPDATE is
    what distinguishes the winner.
    """
    now = _now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            """SELECT id, kind, payload_json, attempts, max_attempts
                 FROM bg_task_queue
                WHERE status = 'pending' AND next_attempt_at <= ?
                ORDER BY next_attempt_at ASC, id ASC
                LIMIT 1""",
            (now,),
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        task_id = row["id"]
        n = conn.execute(
            "UPDATE bg_task_queue SET status='processing', updated_at=? "
            "WHERE id=? AND status='pending'",
            (now, task_id),
        ).rowcount
        if n == 0:
            # Lost the race to another worker. Roll back, return None so
            # the caller polls again on the next tick.
            conn.execute("ROLLBACK")
            return None
        # Re-read so we return the updated row (status='processing').
        claimed = conn.execute(
            """SELECT id, kind, payload_json, attempts, max_attempts,
                      status, updated_at, next_attempt_at, dedup_key
                 FROM bg_task_queue WHERE id = ?""",
            (task_id,),
        ).fetchone()
        conn.execute("COMMIT")
        return claimed
    except Exception:
        with contextlib.suppress(Exception):  # pragma: no cover — defensive
            conn.execute("ROLLBACK")
        raise


def mark_done(conn: sqlite3.Connection, task_id: int) -> None:
    """Flip status to 'done'. Idempotent (no-op on already-done rows)."""
    now = _now_iso()
    conn.execute(
        "UPDATE bg_task_queue SET status='done', updated_at=?, last_error=NULL "
        "WHERE id=? AND status IN ('processing', 'pending')",
        (now, task_id),
    )


def mark_failed(
    conn: sqlite3.Connection,
    task_id: int,
    error: str,
    retry_after_s: int | None = None,
) -> None:
    """Record a failure. Schedules a retry until max_attempts is exhausted.

    `retry_after_s` overrides the default exponential schedule (used by
    handlers that know the backend's retry-after hint, e.g. a 429 from
    Postmark with a Retry-After header). When None we apply the standard
    schedule: 60s * 2^attempts, capped at 1h.
    """
    now = _now_iso()
    row = conn.execute(
        "SELECT attempts, max_attempts FROM bg_task_queue WHERE id = ?",
        (task_id,),
    ).fetchone()
    if row is None:
        return
    attempts = int(row["attempts"]) + 1
    max_attempts = int(row["max_attempts"])

    # Truncate `error` to keep the row compact; full traceback should
    # already be captured in logs / Sentry by the worker.
    error_short = (error or "")[:1024]

    if attempts >= max_attempts:
        conn.execute(
            "UPDATE bg_task_queue SET status='failed', attempts=?, "
            "updated_at=?, last_error=? WHERE id=?",
            (attempts, now, error_short, task_id),
        )
        return

    if retry_after_s is None:
        # Exponential backoff. attempts is 1-based here (we just incremented).
        # 1st failure -> 60s, 2nd -> 120s, 3rd -> 240s, ..., cap 1h.
        retry_after_s = min(_BACKOFF_BASE_S * (2 ** (attempts - 1)), _BACKOFF_CAP_S)
    next_at = (datetime.now(UTC) + timedelta(seconds=int(retry_after_s))).strftime(
        "%Y-%m-%dT%H:%M:%S."
    ) + f"{datetime.now(UTC).microsecond // 1000:03d}Z"
    conn.execute(
        "UPDATE bg_task_queue SET status='pending', attempts=?, "
        "updated_at=?, next_attempt_at=?, last_error=? WHERE id=?",
        (attempts, now, next_at, error_short, task_id),
    )


__all__ = ["enqueue", "claim_next", "mark_done", "mark_failed"]
