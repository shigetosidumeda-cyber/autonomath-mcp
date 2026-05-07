"""App-level advisory locks for SQLite.

audit: a23909ea8a7d67d64 (2026-04-25).

SQLite has no native advisory-lock primitive (no `pg_advisory_lock(int)`,
no `SELECT ... FOR UPDATE`). The Stripe subscription refresh path runs
from BOTH the `customer.subscription.updated` webhook AND the
`_refresh_subscription_status_from_stripe_bg` BackgroundTask helper (now
also via the durable bg_task_queue worker), so two refreshes for the
same subscription_id can race the UPDATE on api_keys -- whichever
writer's stale-by-a-few-ms read of Stripe wins last.

This module gives a `with advisory_lock(conn, key, ttl_s=...)` context
manager that gates a critical section on a single TEXT key, with a TTL
so a crashed holder cannot wedge the key forever.

Implementation outline (see migration 063_advisory_locks.sql for table):

    BEGIN IMMEDIATE                                  -- acquire RESERVED lock
    DELETE FROM advisory_locks WHERE expires_at < ?  -- cleanup
    INSERT OR IGNORE INTO advisory_locks(...)        -- claim
    -- if rowcount == 1: we own it; COMMIT and yield
    -- else: another holder owns it; ROLLBACK and retry/raise

    -- on exit:
    DELETE FROM advisory_locks WHERE key = ? AND holder = ?

The holder string is `f"{os.getpid()}:{threading.get_ident()}:{time.monotonic_ns()}"`
so concurrent threads in the same process do not collide AND a quick
acquire/release/acquire cycle by the same thread cannot accidentally
release a successor's lock if the DELETE-on-exit lands after the next
acquire.

Failure modes:
  * `LockNotAcquired` -- another holder owns the key (after retries)
  * Any sqlite3 error during BEGIN IMMEDIATE / INSERT -- propagates as-is

Concurrency model: each call to `advisory_lock(conn, ...)` MUST be made
with a connection that is NOT in autocommit-with-an-open-transaction
state (i.e. plain `_db_connect()` from db.session). The helper itself
opens / closes a BEGIN IMMEDIATE transaction on the connection for the
acquire phase.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("jpintel.advisory_lock")


class LockNotAcquired(Exception):  # noqa: N818 (public name; rename touches cross-module callers)
    """Raised when the advisory lock could not be acquired after retries.

    Carries the key that was contended and the current holder (best-effort
    -- by the time the caller inspects it the lock may already have been
    released, but the snapshot is still useful for log triage).
    """

    def __init__(self, key: str, current_holder: str | None = None) -> None:
        self.key = key
        self.current_holder = current_holder
        super().__init__(
            f"advisory lock not acquired key={key!r} current_holder={current_holder!r}"
        )


def _make_holder() -> str:
    """Identity string for the current thread/process at this instant.

    monotonic_ns suffix prevents (pid, tid) accidental release of a
    successor lock after a quick acquire/release/acquire cycle.
    """
    return f"{os.getpid()}:{threading.get_ident()}:{time.monotonic_ns()}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _expires_iso(ttl_s: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=ttl_s)).isoformat()


@contextmanager
def advisory_lock(
    conn,
    key: str,
    *,
    ttl_s: int = 30,
    retry_count: int = 3,
    retry_backoff_s: float = 0.05,
) -> Iterator[str]:
    """Context manager that holds an app-level advisory lock on `key`.

    Yields the holder string so callers can correlate logs.

    Args:
        conn: sqlite3.Connection in autocommit mode (isolation_level=None).
        key: free-form TEXT key to lock on (e.g. "subscription:sub_xyz").
        ttl_s: maximum lock duration before expiry. Default 30s.
        retry_count: extra acquire attempts on contention. Total attempts =
            retry_count + 1 (i.e. retry_count=3 → 4 total tries).
        retry_backoff_s: sleep between retries. Linear (no jitter, kept
            simple — Stripe webhook contention is rare and bounded).

    Raises:
        LockNotAcquired: if another holder owns the key after all retries.
    """
    holder = _make_holder()
    attempts = retry_count + 1
    acquired = False
    current_holder: str | None = None

    for attempt in range(attempts):
        try:
            conn.execute("BEGIN IMMEDIATE")
        except Exception:
            # Another writer already holds the SQLite RESERVED lock.
            # Treat as contention and retry.
            time.sleep(retry_backoff_s)
            continue

        try:
            now = _now_iso()
            # Cleanup expired rows on every acquire so a crashed holder
            # cannot wedge the key forever.
            conn.execute(
                "DELETE FROM advisory_locks WHERE expires_at < ?",
                (now,),
            )
            cur = conn.execute(
                "INSERT OR IGNORE INTO advisory_locks"
                " (key, holder, acquired_at, ttl_s, expires_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (key, holder, now, ttl_s, _expires_iso(ttl_s)),
            )
            if cur.rowcount == 1:
                conn.execute("COMMIT")
                acquired = True
                break
            # Another holder beat us. Capture their identity for the
            # eventual LockNotAcquired exception message.
            row = conn.execute(
                "SELECT holder FROM advisory_locks WHERE key = ?",
                (key,),
            ).fetchone()
            current_holder = row[0] if row else None
            conn.execute("ROLLBACK")
        except Exception:
            with suppress(Exception):
                conn.execute("ROLLBACK")
            raise

        if attempt < attempts - 1:
            time.sleep(retry_backoff_s)

    if not acquired:
        raise LockNotAcquired(key=key, current_holder=current_holder)

    try:
        yield holder
    finally:
        # Only the holder can release. A different holder's DELETE is a
        # no-op (rowcount=0), so an accidental cross-holder release is
        # impossible. We do NOT wrap this in BEGIN/COMMIT because
        # autocommit single-statement DELETE is atomic in SQLite.
        try:
            conn.execute(
                "DELETE FROM advisory_locks WHERE key = ? AND holder = ?",
                (key, holder),
            )
        except Exception:
            # Release MUST NOT raise back into the caller -- the body of
            # the with-block may already be raising and we do not want
            # to mask that with a release-time DB error. Log + swallow.
            logger.warning(
                "advisory_lock_release_failed key=%s holder=%s",
                key,
                holder,
                exc_info=True,
            )
