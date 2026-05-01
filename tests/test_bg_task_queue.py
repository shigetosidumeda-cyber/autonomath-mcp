"""Durable background-task queue tests (migration 060).

Covers the contract documented in `src/jpintel_mcp/api/_bg_task_queue.py`
and `_bg_task_worker.py`:

  * enqueue() idempotency via dedup_key
  * claim_next() atomicity inside BEGIN IMMEDIATE
  * mark_failed exponential backoff schedule
  * max_attempts -> status='failed'
  * worker dispatches by `kind` to the registered handler

Each test gets its own throw-away SQLite DB built from `db/schema.sql`
so no fixture seeded by the global conftest leaks state between cases.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path


# The conftest already sets JPINTEL_DB_PATH for the integration suite,
# but for these focused unit tests we want a clean per-test DB. We build
# one straight from db/schema.sql.
from jpintel_mcp.api._bg_task_queue import (
    claim_next,
    enqueue,
    mark_done,
    mark_failed,
)
from jpintel_mcp.api._bg_task_worker import (
    _HANDLERS,
    _dispatch_one,
    run_worker_loop,
)
from jpintel_mcp.db.session import SCHEMA_PATH


def _fresh_db(tmp_path: Path) -> sqlite3.Connection:
    """Build a temp SQLite from the canonical schema."""
    db_path = tmp_path / "queue.db"
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(schema)
    return conn


# ---------------------------------------------------------------------------
# enqueue idempotency via dedup_key
# ---------------------------------------------------------------------------


def test_enqueue_inserts_row(tmp_path):
    conn = _fresh_db(tmp_path)
    task_id = enqueue(
        conn,
        kind="welcome_email",
        payload={"to": "user@example.com", "raw_key": "abcdef1234", "tier": "paid"},
    )
    assert task_id > 0

    row = conn.execute(
        "SELECT kind, payload_json, status, attempts FROM bg_task_queue WHERE id = ?",
        (task_id,),
    ).fetchone()
    assert row is not None
    assert row["kind"] == "welcome_email"
    payload = json.loads(row["payload_json"])
    assert payload["to"] == "user@example.com"
    assert payload["tier"] == "paid"
    assert row["status"] == "pending"
    assert row["attempts"] == 0


def test_enqueue_dedup_returns_existing_id(tmp_path):
    """A second call with the same dedup_key must NOT insert a new row."""
    conn = _fresh_db(tmp_path)
    first = enqueue(
        conn,
        kind="welcome_email",
        payload={"to": "a@example.com", "raw_key": "k1", "tier": "paid"},
        dedup_key="welcome:sub_xxx",
    )
    second = enqueue(
        conn,
        kind="welcome_email",
        payload={"to": "DIFFERENT@example.com", "raw_key": "k2", "tier": "paid"},
        dedup_key="welcome:sub_xxx",
    )
    assert first == second

    rows = conn.execute("SELECT COUNT(*) FROM bg_task_queue").fetchone()
    assert rows[0] == 1

    # Original payload preserved (ON CONFLICT DO NOTHING; not DO UPDATE).
    row = conn.execute(
        "SELECT payload_json FROM bg_task_queue WHERE id = ?", (first,)
    ).fetchone()
    payload = json.loads(row["payload_json"])
    assert payload["to"] == "a@example.com"


def test_enqueue_no_dedup_allows_duplicates(tmp_path):
    """Without dedup_key, a duplicate enqueue gets a fresh id."""
    conn = _fresh_db(tmp_path)
    a = enqueue(
        conn, kind="welcome_email", payload={"to": "x@example.com", "raw_key": "k", "tier": "paid"}
    )
    b = enqueue(
        conn, kind="welcome_email", payload={"to": "x@example.com", "raw_key": "k", "tier": "paid"}
    )
    assert a != b
    rows = conn.execute("SELECT COUNT(*) FROM bg_task_queue").fetchone()
    assert rows[0] == 2


# ---------------------------------------------------------------------------
# claim_next atomicity (BEGIN IMMEDIATE)
# ---------------------------------------------------------------------------


def test_claim_next_returns_none_on_empty_queue(tmp_path):
    conn = _fresh_db(tmp_path)
    assert claim_next(conn) is None


def test_claim_next_picks_oldest_pending(tmp_path):
    conn = _fresh_db(tmp_path)
    # Insert in reverse temporal order so id != next_attempt_at order.
    later = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    earlier = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    conn.execute(
        "INSERT INTO bg_task_queue(kind,payload_json,status,attempts,max_attempts,"
        "updated_at,next_attempt_at) VALUES "
        "('welcome_email','{}','pending',0,5,?,?)",
        (later, later),
    )
    conn.execute(
        "INSERT INTO bg_task_queue(kind,payload_json,status,attempts,max_attempts,"
        "updated_at,next_attempt_at) VALUES "
        "('dunning_email','{}','pending',0,5,?,?)",
        (earlier, earlier),
    )
    row = claim_next(conn)
    assert row is not None
    # Earlier next_attempt_at wins.
    assert row["kind"] == "dunning_email"
    # Status flipped to 'processing' atomically.
    assert row["status"] == "processing"


def test_claim_next_skips_future_tasks(tmp_path):
    conn = _fresh_db(tmp_path)
    # Schedule a task 1h into the future. claim_next should skip it.
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO bg_task_queue(kind,payload_json,status,attempts,max_attempts,"
        "updated_at,next_attempt_at) VALUES ('x','{}','pending',0,5,?,?)",
        (now, future),
    )
    assert claim_next(conn) is None


def test_claim_next_atomic_no_duplicate_claim(tmp_path):
    """Two threads racing claim_next on one row -> exactly one wins."""
    db_path = tmp_path / "race.db"
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    setup = sqlite3.connect(db_path, isolation_level=None)
    setup.executescript(schema)
    setup.execute("PRAGMA journal_mode = WAL")
    now = datetime.now(UTC).isoformat()
    setup.execute(
        "INSERT INTO bg_task_queue(kind,payload_json,status,attempts,max_attempts,"
        "updated_at,next_attempt_at) VALUES ('welcome_email','{}','pending',0,5,?,?)",
        (now, now),
    )
    setup.close()

    results: list[sqlite3.Row | None] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker():
        try:
            conn = sqlite3.connect(db_path, isolation_level=None, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000")
            barrier.wait()
            results.append(claim_next(conn))
            conn.close()
        except BaseException as e:  # pragma: no cover
            errors.append(e)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert not errors, errors

    claimed = [r for r in results if r is not None]
    not_claimed = [r for r in results if r is None]
    assert len(claimed) == 1
    assert len(not_claimed) == 1


# ---------------------------------------------------------------------------
# Exponential backoff retry
# ---------------------------------------------------------------------------


def test_mark_failed_schedules_exponential_retry(tmp_path):
    conn = _fresh_db(tmp_path)
    task_id = enqueue(
        conn,
        kind="welcome_email",
        payload={"to": "x@example.com", "raw_key": "k", "tier": "paid"},
    )
    # Move to processing so mark_failed reflects a real attempt.
    claimed = claim_next(conn)
    assert claimed is not None
    t0 = datetime.now(UTC)
    mark_failed(conn, task_id, "transport hiccup")
    row = conn.execute(
        "SELECT status, attempts, next_attempt_at, last_error "
        "FROM bg_task_queue WHERE id=?",
        (task_id,),
    ).fetchone()
    assert row["status"] == "pending"  # rescheduled
    assert row["attempts"] == 1
    assert row["last_error"] == "transport hiccup"

    # Retry scheduled ~60s out (+/- 5s slack for test execution).
    next_at = datetime.fromisoformat(row["next_attempt_at"].replace("Z", "+00:00"))
    delta = (next_at - t0).total_seconds()
    assert 55 <= delta <= 70, delta


def test_mark_failed_doubles_each_attempt(tmp_path):
    """1st->60s, 2nd->120s, 3rd->240s."""
    conn = _fresh_db(tmp_path)
    task_id = enqueue(
        conn, kind="welcome_email", payload={}
    )

    expected = [60, 120, 240]
    for attempt, exp_delay in enumerate(expected, start=1):
        # Make the row pending+due first.
        conn.execute(
            "UPDATE bg_task_queue SET status='processing', "
            "next_attempt_at=? WHERE id=?",
            (datetime.now(UTC).isoformat(), task_id),
        )
        t0 = datetime.now(UTC)
        mark_failed(conn, task_id, f"attempt {attempt}")
        row = conn.execute(
            "SELECT attempts, status, next_attempt_at FROM bg_task_queue WHERE id=?",
            (task_id,),
        ).fetchone()
        assert row["attempts"] == attempt
        assert row["status"] == "pending"
        next_at = datetime.fromisoformat(
            row["next_attempt_at"].replace("Z", "+00:00")
        )
        delta = (next_at - t0).total_seconds()
        assert (exp_delay - 5) <= delta <= (exp_delay + 5), (
            attempt, delta, exp_delay,
        )


def test_mark_failed_caps_backoff_at_one_hour(tmp_path):
    """For attempts much greater than log2(3600/60)=~5.9 the cap kicks in."""
    conn = _fresh_db(tmp_path)
    task_id = enqueue(
        conn,
        kind="welcome_email",
        payload={},
        max_attempts=20,  # need room for the 10th attempt
    )
    # Pretend we've already failed 9 times.
    conn.execute(
        "UPDATE bg_task_queue SET attempts=9, status='processing' WHERE id=?",
        (task_id,),
    )
    t0 = datetime.now(UTC)
    mark_failed(conn, task_id, "still failing")
    row = conn.execute(
        "SELECT next_attempt_at FROM bg_task_queue WHERE id=?", (task_id,)
    ).fetchone()
    next_at = datetime.fromisoformat(row["next_attempt_at"].replace("Z", "+00:00"))
    delta = (next_at - t0).total_seconds()
    # Cap is 1h. Allow a few seconds of test-execution slack.
    assert 3590 <= delta <= 3610, delta


# ---------------------------------------------------------------------------
# max_attempts -> failed
# ---------------------------------------------------------------------------


def test_max_attempts_flips_status_to_failed(tmp_path):
    conn = _fresh_db(tmp_path)
    task_id = enqueue(
        conn, kind="welcome_email", payload={}, max_attempts=3
    )
    # Burn 3 attempts.
    for i in range(3):
        conn.execute(
            "UPDATE bg_task_queue SET status='processing' WHERE id=?", (task_id,)
        )
        mark_failed(conn, task_id, f"err {i}")
    row = conn.execute(
        "SELECT status, attempts, last_error FROM bg_task_queue WHERE id=?",
        (task_id,),
    ).fetchone()
    assert row["status"] == "failed"
    assert row["attempts"] == 3
    assert "err" in row["last_error"]


def test_mark_done_idempotent(tmp_path):
    conn = _fresh_db(tmp_path)
    task_id = enqueue(conn, kind="welcome_email", payload={})
    conn.execute("UPDATE bg_task_queue SET status='processing' WHERE id=?", (task_id,))
    mark_done(conn, task_id)
    mark_done(conn, task_id)  # second call must not raise
    row = conn.execute(
        "SELECT status FROM bg_task_queue WHERE id=?", (task_id,)
    ).fetchone()
    assert row["status"] == "done"


# ---------------------------------------------------------------------------
# Worker dispatcher: handler-by-kind correctness
# ---------------------------------------------------------------------------


def test_dispatch_unknown_kind_marks_failed(tmp_path):
    conn = _fresh_db(tmp_path)
    enqueue(conn, kind="unknown_handler", payload={})
    row = claim_next(conn)
    assert row is not None
    ok, err = _dispatch_one(row)
    assert ok is False
    assert err is not None and "unknown kind" in err


def test_dispatch_invokes_correct_handler(tmp_path, monkeypatch):
    """Each registered `kind` routes to exactly its handler."""
    calls: list[tuple[str, dict]] = []

    def make_recorder(label):
        def _rec(payload):
            calls.append((label, payload))
        return _rec

    # Patch the dispatch table directly so we don't touch real Postmark / Stripe.
    monkeypatch.setitem(_HANDLERS, "welcome_email", make_recorder("welcome_email"))
    monkeypatch.setitem(_HANDLERS, "key_rotated_email", make_recorder("key_rotated_email"))
    monkeypatch.setitem(_HANDLERS, "stripe_status_refresh", make_recorder("stripe_status_refresh"))
    monkeypatch.setitem(_HANDLERS, "dunning_email", make_recorder("dunning_email"))
    monkeypatch.setitem(_HANDLERS, "stripe_usage_sync", make_recorder("stripe_usage_sync"))

    conn = _fresh_db(tmp_path)
    enqueue(conn, kind="welcome_email", payload={"to": "a@b"})
    enqueue(conn, kind="key_rotated_email", payload={"to": "a@b"})
    enqueue(conn, kind="stripe_status_refresh", payload={"sub_id": "sub_x"})
    enqueue(conn, kind="dunning_email", payload={"to": "a@b"})
    enqueue(conn, kind="stripe_usage_sync", payload={"subscription_id": "sub_y"})

    seen_labels = []
    for _ in range(5):
        row = claim_next(conn)
        assert row is not None
        ok, err = _dispatch_one(row)
        assert ok, err
        seen_labels.append(row["kind"])

    # All five kinds dispatched in some order (FIFO by next_attempt_at, but
    # rows enqueued back-to-back may share timestamps).
    assert set(seen_labels) == {
        "welcome_email",
        "key_rotated_email",
        "stripe_status_refresh",
        "dunning_email",
        "stripe_usage_sync",
    }
    assert {label for (label, _) in calls} == set(seen_labels)


def test_dispatch_handler_exception_marks_failed(tmp_path, monkeypatch):
    """Handler raise -> _dispatch_one returns ok=False with error string."""

    def boom(payload):
        raise RuntimeError("postmark transient outage")

    monkeypatch.setitem(_HANDLERS, "welcome_email", boom)

    conn = _fresh_db(tmp_path)
    task_id = enqueue(
        conn,
        kind="welcome_email",
        payload={"to": "x@example.com"},
    )
    row = claim_next(conn)
    assert row is not None
    assert row["id"] == task_id

    ok, err = _dispatch_one(row)
    assert ok is False
    assert err is not None and "postmark transient outage" in err


# ---------------------------------------------------------------------------
# Worker loop end-to-end: enqueue -> drain -> done
# ---------------------------------------------------------------------------


def test_run_worker_loop_drains_and_stops(tmp_path, monkeypatch):
    """Worker drains a queued task and exits cleanly on stop_event."""
    calls: list[dict] = []

    def handler(payload):
        calls.append(payload)

    monkeypatch.setitem(_HANDLERS, "welcome_email", handler)

    # Point JPINTEL_DB_PATH at a fresh db so worker's _db_connect picks it up.
    db_path = tmp_path / "worker.db"
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    bootstrap = sqlite3.connect(db_path, isolation_level=None)
    bootstrap.executescript(schema)
    bootstrap.close()

    monkeypatch.setenv("JPINTEL_DB_PATH", str(db_path))
    # Force settings module to reload its db_path attribute.
    from jpintel_mcp.config import settings as _settings

    monkeypatch.setattr(_settings, "db_path", db_path, raising=False)

    # Enqueue one row.
    setup = sqlite3.connect(db_path, isolation_level=None)
    setup.row_factory = sqlite3.Row
    enqueue(
        setup,
        kind="welcome_email",
        payload={"to": "a@example.com", "raw_key": "k", "tier": "paid"},
    )
    setup.close()

    # Speed the worker poll from 2s to 0.05s for the test.
    monkeypatch.setattr(
        "jpintel_mcp.api._bg_task_worker.POLL_INTERVAL_S", 0.05, raising=False
    )

    async def run():
        stop = asyncio.Event()
        task = asyncio.create_task(run_worker_loop(stop))
        # Give the worker time to drain.
        await asyncio.sleep(0.5)
        stop.set()
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(run())

    assert len(calls) == 1
    assert calls[0]["to"] == "a@example.com"

    # DB row is now status='done'.
    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    row = check.execute("SELECT status FROM bg_task_queue").fetchone()
    check.close()
    assert row["status"] == "done"
