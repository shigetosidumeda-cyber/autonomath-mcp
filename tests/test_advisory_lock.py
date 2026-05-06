"""Happy-path tests for `api/_advisory_lock.py`.

Covers the acquire→release round-trip on a real SQLite connection backed
by the migration 063 schema (advisory_locks table).

No mocks — the test opens an in-process sqlite3 connection in autocommit
mode, applies the 063 schema, then exercises the context manager.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS advisory_locks (
    key TEXT PRIMARY KEY,
    holder TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    ttl_s INTEGER NOT NULL DEFAULT 30,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_advisory_locks_expires
    ON advisory_locks(expires_at);
"""


@pytest.fixture()
def lock_db(tmp_path: Path) -> sqlite3.Connection:
    """File-backed SQLite db with the advisory_locks schema applied.

    File-backed (not :memory:) so BEGIN IMMEDIATE locks are real — the
    advisory_lock context manager opens its own transaction and we want
    SQLite's normal locking semantics in play.
    """
    db_file = tmp_path / "advisory.db"
    conn = sqlite3.connect(str(db_file), isolation_level=None)
    conn.executescript(_SCHEMA)
    yield conn
    conn.close()


def test_acquire_releases_correctly(lock_db: sqlite3.Connection):
    """Round-trip: acquire → row exists → exit → row deleted."""
    from jpintel_mcp.api._advisory_lock import advisory_lock

    key = "subscription:sub_test_123"

    with advisory_lock(lock_db, key, ttl_s=30) as holder:
        assert isinstance(holder, str)
        # While inside the with-block, the lock row must exist.
        row = lock_db.execute(
            "SELECT key, holder FROM advisory_locks WHERE key = ?", (key,)
        ).fetchone()
        assert row is not None
        assert row[0] == key
        assert row[1] == holder

    # After the with-block, the row is deleted.
    row = lock_db.execute("SELECT 1 FROM advisory_locks WHERE key = ?", (key,)).fetchone()
    assert row is None


def test_second_acquire_after_release_succeeds(lock_db: sqlite3.Connection):
    """Releasing a lock leaves the key free for the next caller."""
    from jpintel_mcp.api._advisory_lock import advisory_lock

    key = "customer:cus_test_abc"

    with advisory_lock(lock_db, key):
        pass
    with advisory_lock(lock_db, key):
        # Reacquire on the same key works because the prior holder released.
        row = lock_db.execute("SELECT key FROM advisory_locks WHERE key = ?", (key,)).fetchone()
        assert row is not None
