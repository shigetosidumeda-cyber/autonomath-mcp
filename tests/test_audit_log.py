"""Happy-path tests for `api/_audit_log.py::log_event`.

Migration 058 created the `audit_log` table; the `init_db` schema dump
includes it. Each test seeds a real sqlite file, calls `log_event`, then
reads the row back to verify shape.

The helper swallows every exception (the contract is "audit logging must
never break the user request"), so a happy-path test that asserts the row
landed is the only meaningful coverage.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  event_type TEXT NOT NULL,
  key_hash TEXT,
  key_hash_new TEXT,
  customer_id TEXT,
  ip TEXT,
  user_agent TEXT,
  metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_log_event_type
    ON audit_log(event_type, ts DESC);
"""


@pytest.fixture()
def audit_db(tmp_path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(tmp_path / "audit.db"))
    db.executescript(_SCHEMA)
    db.commit()
    yield db
    db.close()


def test_log_event_writes_row(audit_db: sqlite3.Connection):
    """1 event recorded → 1 row readable with all fields populated."""
    from jpintel_mcp.api._audit_log import log_event

    log_event(
        audit_db,
        event_type="key_rotate",
        key_hash="abcd1234",
        key_hash_new="efgh5678",
        customer_id="cus_test_42",
        request=None,
        reason="user-initiated",
    )

    rows = audit_db.execute(
        "SELECT event_type, key_hash, key_hash_new, customer_id, metadata "
        "FROM audit_log"
    ).fetchall()
    assert len(rows) == 1
    event_type, key_hash, key_hash_new, customer_id, metadata = rows[0]
    assert event_type == "key_rotate"
    assert key_hash == "abcd1234"
    assert key_hash_new == "efgh5678"
    assert customer_id == "cus_test_42"
    assert metadata is not None
    md = json.loads(metadata)
    assert md["reason"] == "user-initiated"


def test_log_event_without_metadata_or_request(audit_db: sqlite3.Connection):
    """Minimal event (just event_type) lands as a row with nullable cols NULL."""
    from jpintel_mcp.api._audit_log import log_event

    log_event(audit_db, event_type="login")

    rows = audit_db.execute(
        "SELECT event_type, key_hash, customer_id, ip, user_agent, metadata "
        "FROM audit_log"
    ).fetchall()
    assert len(rows) == 1
    event_type, key_hash, customer_id, ip, ua, metadata = rows[0]
    assert event_type == "login"
    assert key_hash is None
    assert customer_id is None
    assert ip is None
    assert ua is None
    assert metadata is None


def test_log_event_swallows_missing_table(tmp_path: Path):
    """Contract: a missing schema during partial migration must not raise."""
    from jpintel_mcp.api._audit_log import log_event

    db = sqlite3.connect(str(tmp_path / "no-schema.db"))
    try:
        # No audit_log table exists. Helper must swallow the error silently.
        log_event(db, event_type="login_failed")
    finally:
        db.close()
