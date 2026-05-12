"""Wave 43.3 AX Resilience cells 4-6 unit tests.

Covers:
  - migration 267 (am_dlq + dlq_drain_log) shape + constraints
  - migration 268 (am_state_checkpoint + v_state_checkpoint_latest) shape
  - scripts/cron/dlq_drain.py end-to-end replay flow (bg_task path)
  - src/jpintel_mcp/api/_replay_token.py TTL + cache-key isolation
  - src/jpintel_mcp/api/_state_checkpoint.py StateCheckpoint API surface

All tests use an in-memory / temp-file SQLite DB so we never touch
production autonomath.db. Tests do NOT exercise the LLM, Stripe, or
any external service.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "scripts" / "migrations"
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Ensure the cron script's parent dir is importable for the drain test.
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    """Temp DB pre-loaded with migrations 267 + 268 + bg_task_queue stub."""
    db_path = tmp_path / "am_test.db"
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Apply migration 267 (DLQ).
    mig_267 = (MIGRATIONS_DIR / "267_dlq.sql").read_text(encoding="utf-8")
    conn.executescript(mig_267)
    # Apply migration 268 (state checkpoint).
    mig_268 = (MIGRATIONS_DIR / "268_state_checkpoint.sql").read_text(encoding="utf-8")
    conn.executescript(mig_268)

    # Stub bg_task_queue (migration 060 — would be present in prod).
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bg_task_queue (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            kind            TEXT NOT NULL,
            payload         TEXT NOT NULL,
            dedup_key       TEXT UNIQUE,
            status          TEXT NOT NULL DEFAULT 'pending',
            attempts        INTEGER NOT NULL DEFAULT 0,
            max_attempts    INTEGER NOT NULL DEFAULT 5,
            created_at      TEXT NOT NULL,
            next_attempt_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            webhook_id      TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            event_id        TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            attempts        INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL,
            next_attempt_at TEXT NOT NULL,
            UNIQUE(webhook_id, event_type, event_id)
        );
        """
    )
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Migration 267 shape
# ---------------------------------------------------------------------------


def test_267_am_dlq_table_exists(db: sqlite3.Connection) -> None:
    """am_dlq + dlq_drain_log tables present after migration 267."""
    tables = {
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('am_dlq','dlq_drain_log')"
        )
    }
    assert tables == {"am_dlq", "dlq_drain_log"}


def test_267_am_dlq_unique_source(db: sqlite3.Connection) -> None:
    """UNIQUE(source_kind, source_id) enforced on am_dlq."""
    now = datetime.now(UTC).isoformat()
    db.execute(
        """
        INSERT INTO am_dlq
            (source_kind, source_id, kind, payload,
             first_failed_at, last_failed_at)
        VALUES ('bg_task', '101', 'welcome_email', '{}', ?, ?)
        """,
        (now, now),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO am_dlq
                (source_kind, source_id, kind, payload,
                 first_failed_at, last_failed_at)
            VALUES ('bg_task', '101', 'welcome_email', '{}', ?, ?)
            """,
            (now, now),
        )


def test_267_status_check_constraint(db: sqlite3.Connection) -> None:
    """status must be quarantined/replayed/abandoned."""
    now = datetime.now(UTC).isoformat()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO am_dlq
                (source_kind, source_id, kind, payload, status,
                 first_failed_at, last_failed_at)
            VALUES ('bg_task', '102', 'k', '{}', 'invalid', ?, ?)
            """,
            (now, now),
        )


def test_267_summary_view(db: sqlite3.Connection) -> None:
    """v_am_dlq_quarantine_summary aggregates by source/kind/status."""
    now = datetime.now(UTC).isoformat()
    for i in range(3):
        db.execute(
            """
            INSERT INTO am_dlq
                (source_kind, source_id, kind, payload,
                 first_failed_at, last_failed_at)
            VALUES ('bg_task', ?, 'welcome_email', '{}', ?, ?)
            """,
            (f"row-{i}", now, now),
        )
    rows = list(db.execute("SELECT * FROM v_am_dlq_quarantine_summary"))
    assert len(rows) == 1
    assert rows[0]["cnt"] == 3
    assert rows[0]["source_kind"] == "bg_task"
    assert rows[0]["status"] == "quarantined"


# ---------------------------------------------------------------------------
# Migration 268 shape
# ---------------------------------------------------------------------------


def test_268_am_state_checkpoint_table(db: sqlite3.Connection) -> None:
    """am_state_checkpoint + view present after migration 268."""
    tables = {
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='am_state_checkpoint'"
        )
    }
    assert tables == {"am_state_checkpoint"}
    views = {
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='view' "
            "AND name='v_state_checkpoint_latest'"
        )
    }
    assert views == {"v_state_checkpoint_latest"}


def test_268_unique_workflow_step(db: sqlite3.Connection) -> None:
    """UNIQUE(workflow_id, step_index) enforced."""
    db.execute(
        """
        INSERT INTO am_state_checkpoint
            (workflow_id, workflow_kind, step_index, step_name, state_blob)
        VALUES ('wf-1', 'fanout', 0, 'fetch', '{}')
        """
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO am_state_checkpoint
                (workflow_id, workflow_kind, step_index, step_name, state_blob)
            VALUES ('wf-1', 'fanout', 0, 'fetch2', '{}')
            """
        )


def test_268_latest_view(db: sqlite3.Connection) -> None:
    """v_state_checkpoint_latest returns MAX(step_index) per workflow."""
    for idx, name in enumerate(("fetch", "score", "emit")):
        db.execute(
            """
            INSERT INTO am_state_checkpoint
                (workflow_id, workflow_kind, step_index, step_name, state_blob)
            VALUES ('wf-2', 'fanout', ?, ?, '{}')
            """,
            (idx, name),
        )
    row = db.execute(
        "SELECT * FROM v_state_checkpoint_latest WHERE workflow_id='wf-2'"
    ).fetchone()
    assert row is not None
    assert row["latest_step_index"] == 2
    assert row["total_steps"] == 3


# ---------------------------------------------------------------------------
# _replay_token module
# ---------------------------------------------------------------------------


def test_replay_token_validation() -> None:
    from jpintel_mcp.api._replay_token import validate_token

    assert validate_token("a" * 16)[0] is True
    assert validate_token("short")[0] is False
    assert validate_token(None)[0] is False
    assert validate_token("a" * 300)[0] is False
    assert validate_token("has space")[0] is False
    assert validate_token("a" * 15 + "!")[0] is False  # bad char


def test_replay_token_store_and_lookup(db: sqlite3.Connection) -> None:
    from jpintel_mcp.api._replay_token import lookup, store

    tok = "tok_" + "a" * 20
    ak = "akhash-1"
    body = {"data": [{"id": 1, "name": "test"}]}
    assert (
        store(
            db, tok, ak,
            request_path="/v1/programs",
            request_method="GET",
            response_body=body,
        )
        is True
    )
    hit = lookup(
        db, tok, ak,
        request_path="/v1/programs",
        request_method="GET",
    )
    assert hit is not None
    assert hit["body"] == body
    assert hit["status"] == 200


def test_replay_token_isolation_across_keys(db: sqlite3.Connection) -> None:
    """Same token used by two api_key_hashes must produce two cache rows."""
    from jpintel_mcp.api._replay_token import lookup, store

    tok = "shared-" + "x" * 20
    body_a = {"who": "a"}
    body_b = {"who": "b"}
    store(db, tok, "ak-a", request_path="/v1/x", request_method="GET",
          response_body=body_a)
    store(db, tok, "ak-b", request_path="/v1/x", request_method="GET",
          response_body=body_b)
    assert lookup(db, tok, "ak-a", request_path="/v1/x",
                  request_method="GET")["body"] == body_a
    assert lookup(db, tok, "ak-b", request_path="/v1/x",
                  request_method="GET")["body"] == body_b


def test_replay_token_path_mismatch_returns_none(db: sqlite3.Connection) -> None:
    from jpintel_mcp.api._replay_token import lookup, store

    tok = "tok_" + "a" * 20
    store(db, tok, "ak-1", request_path="/v1/programs",
          request_method="GET", response_body={"ok": True})
    miss = lookup(db, tok, "ak-1", request_path="/v1/different",
                  request_method="GET")
    assert miss is None


def test_replay_token_purge_expired(db: sqlite3.Connection) -> None:
    """Rows with expires_at in the past are deleted by purge_expired."""
    from jpintel_mcp.api._replay_token import (
        compute_cache_key,
        ensure_schema,
        purge_expired,
    )

    ensure_schema(db)
    past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    key = compute_cache_key("tok_" + "a" * 20, "ak-1")
    db.execute(
        """
        INSERT INTO am_replay_cache
            (cache_key, api_key_hash, request_path, request_method,
             response_body, response_status, expires_at)
        VALUES (?, 'ak-1', '/v1/x', 'GET', '{}', 200, ?)
        """,
        (key, past),
    )
    purged = purge_expired(db)
    assert purged == 1


# ---------------------------------------------------------------------------
# _state_checkpoint module
# ---------------------------------------------------------------------------


def test_state_checkpoint_commit_and_resume(db: sqlite3.Connection) -> None:
    from jpintel_mcp.api._state_checkpoint import StateCheckpoint

    ck = StateCheckpoint(db, workflow_id="wf-3", workflow_kind="fanout")
    assert not ck.is_done("fetch")
    ck.commit("fetch", {"corpus": [1, 2, 3]})
    assert ck.is_done("fetch")
    state = ck.load_state("fetch")
    assert state == {"corpus": [1, 2, 3]}

    # Resume: a fresh helper sees the prior step as done.
    ck2 = StateCheckpoint(db, workflow_id="wf-3", workflow_kind="fanout")
    assert ck2.is_done("fetch")
    assert ck2.load_state("fetch") == {"corpus": [1, 2, 3]}


def test_state_checkpoint_recommit_replaces_blob(db: sqlite3.Connection) -> None:
    from jpintel_mcp.api._state_checkpoint import StateCheckpoint

    ck = StateCheckpoint(db, workflow_id="wf-4", workflow_kind="fanout")
    ck.commit("step", {"v": 1})
    ck.commit("step", {"v": 2})
    assert ck.load_state("step") == {"v": 2}


def test_state_checkpoint_abort(db: sqlite3.Connection) -> None:
    from jpintel_mcp.api._state_checkpoint import StateCheckpoint

    ck = StateCheckpoint(db, workflow_id="wf-5", workflow_kind="fanout")
    ck.commit("a", {})
    ck.commit("b", {})
    flipped = ck.abort("upstream API down")
    assert flipped == 2
    assert not ck.is_done("a")
    # After abort the helper returns no committed rows for these
    # step names, but the audit row remains in the table.
    row = db.execute(
        "SELECT status, notes FROM am_state_checkpoint "
        "WHERE workflow_id='wf-5' AND step_name='a'"
    ).fetchone()
    assert row is not None
    assert row["status"] == "aborted"
    assert "upstream API down" in (row["notes"] or "")


def test_state_checkpoint_rejects_oversized_blob(db: sqlite3.Connection) -> None:
    from jpintel_mcp.api._state_checkpoint import StateCheckpoint

    ck = StateCheckpoint(db, workflow_id="wf-6", workflow_kind="fanout")
    huge = {"x": "y" * (300 * 1024)}
    with pytest.raises(ValueError, match="exceeds"):
        ck.commit("step", huge)


# ---------------------------------------------------------------------------
# dlq_drain.py end-to-end
# ---------------------------------------------------------------------------


def test_dlq_drain_bg_task_replay(db: sqlite3.Connection, tmp_path: Path) -> None:
    """dlq_drain re-enqueues a quarantined bg_task into bg_task_queue."""
    # Seed a quarantined DLQ row.
    now = datetime.now(UTC).isoformat()
    payload = json.dumps({"to": "x@example.com", "tier": "ord"})
    db.execute(
        """
        INSERT INTO am_dlq
            (source_kind, source_id, kind, payload, attempts,
             first_failed_at, last_failed_at)
        VALUES ('bg_task', 'orig-101', 'welcome_email', ?, 5, ?, ?)
        """,
        (payload, now, now),
    )

    # Re-export the DB path to the cron script via env override.
    from cron.dlq_drain import main  # type: ignore[import-not-found]

    rc = main(["--db", str(tmp_path / "am_test.db"), "--batch-size", "10"])
    # The cron opens its OWN connection, so we sync. The above main()
    # used the same file path as the `db` fixture so its work is
    # already persisted to disk.
    db.commit()
    assert rc == 0

    # Re-open the file and verify state.
    fresh = sqlite3.connect(str(tmp_path / "am_test.db"))
    fresh.row_factory = sqlite3.Row
    dlq_row = fresh.execute(
        "SELECT status FROM am_dlq WHERE source_id='orig-101'"
    ).fetchone()
    assert dlq_row is not None
    assert dlq_row["status"] == "replayed"
    bg_row = fresh.execute(
        "SELECT kind, status FROM bg_task_queue WHERE kind='welcome_email'"
    ).fetchone()
    assert bg_row is not None
    assert bg_row["status"] == "pending"
    fresh.close()


def test_dlq_drain_dry_run_no_mutation(db: sqlite3.Connection,
                                       tmp_path: Path) -> None:
    """--dry-run leaves DLQ rows quarantined."""
    now = datetime.now(UTC).isoformat()
    db.execute(
        """
        INSERT INTO am_dlq
            (source_kind, source_id, kind, payload, attempts,
             first_failed_at, last_failed_at)
        VALUES ('bg_task', 'orig-202', 'welcome_email', '{}', 5, ?, ?)
        """,
        (now, now),
    )
    from cron.dlq_drain import main  # type: ignore[import-not-found]

    rc = main([
        "--db", str(tmp_path / "am_test.db"),
        "--batch-size", "10", "--dry-run",
    ])
    assert rc == 0
    fresh = sqlite3.connect(str(tmp_path / "am_test.db"))
    row = fresh.execute(
        "SELECT status FROM am_dlq WHERE source_id='orig-202'"
    ).fetchone()
    fresh.close()
    assert row[0] == "quarantined"
