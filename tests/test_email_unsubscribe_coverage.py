"""Coverage tests for `jpintel_mcp.email.unsubscribe` (lane #5).

Uses real SQLite with the email_unsubscribes table. The module's surface is
small (is_unsubscribed / record_unsubscribe) and its behaviour is
load-bearing (特電法 §3 master suppression list), so we exercise both
happy / error / dedup paths.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import tempfile
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.db.session import init_db
from jpintel_mcp.email import unsubscribe as unsub

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
else:
    from pathlib import Path


@pytest.fixture()
def db_path(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    fd, raw = tempfile.mkstemp(prefix="jpintel-unsub-", suffix=".db")
    os.close(fd)
    p = Path(raw)
    monkeypatch.setenv("JPINTEL_DB_PATH", str(p))
    monkeypatch.setenv("JPCITE_DB_PATH", str(p))
    init_db(p)
    yield p
    for ext in ("", "-wal", "-shm"):
        target = Path(str(p) + ext)
        if target.exists():
            with contextlib.suppress(OSError):
                target.unlink()


@pytest.fixture()
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


# ---------------------------------------------------------------------------
# is_unsubscribed
# ---------------------------------------------------------------------------


def test_is_unsubscribed_returns_false_when_empty_string(conn: sqlite3.Connection) -> None:
    assert unsub.is_unsubscribed(conn, "") is False


def test_is_unsubscribed_returns_false_when_address_absent(conn: sqlite3.Connection) -> None:
    assert unsub.is_unsubscribed(conn, "nobody@example.com") is False


def test_is_unsubscribed_returns_true_after_record(conn: sqlite3.Connection) -> None:
    unsub.record_unsubscribe(conn, "user@example.com")
    assert unsub.is_unsubscribed(conn, "user@example.com") is True


def test_is_unsubscribed_normalises_email_case(conn: sqlite3.Connection) -> None:
    unsub.record_unsubscribe(conn, "User@Example.COM")
    # Lookup by mixed-case lookalike — module canonicalises both sides.
    assert unsub.is_unsubscribed(conn, "user@example.com") is True
    assert unsub.is_unsubscribed(conn, "USER@example.com") is True


def test_is_unsubscribed_strips_surrounding_whitespace(conn: sqlite3.Connection) -> None:
    unsub.record_unsubscribe(conn, "  spaced@example.com  ")
    assert unsub.is_unsubscribed(conn, "spaced@example.com") is True


def test_is_unsubscribed_fails_closed_on_db_error() -> None:
    # Close the connection so the SELECT raises sqlite3.Error.
    c = sqlite3.connect(":memory:")
    c.close()
    # Operating on a closed connection raises ProgrammingError (subclass of Error).
    assert unsub.is_unsubscribed(c, "x@example.com") is True


# ---------------------------------------------------------------------------
# record_unsubscribe
# ---------------------------------------------------------------------------


def test_record_unsubscribe_returns_true_when_new(conn: sqlite3.Connection) -> None:
    assert unsub.record_unsubscribe(conn, "new@example.com") is True


def test_record_unsubscribe_returns_false_when_duplicate(
    conn: sqlite3.Connection,
) -> None:
    assert unsub.record_unsubscribe(conn, "dup@example.com") is True
    assert unsub.record_unsubscribe(conn, "dup@example.com") is False


def test_record_unsubscribe_empty_email_returns_false(conn: sqlite3.Connection) -> None:
    assert unsub.record_unsubscribe(conn, "") is False


def test_record_unsubscribe_truncates_overlong_reason(
    conn: sqlite3.Connection,
) -> None:
    long_reason = "x" * 200
    unsub.record_unsubscribe(conn, "trunc@example.com", reason=long_reason)
    stored = conn.execute(
        "SELECT reason FROM email_unsubscribes WHERE email = ?",
        ("trunc@example.com",),
    ).fetchone()
    assert stored is not None
    assert len(stored[0]) == unsub.REASON_MAX_LEN


def test_record_unsubscribe_with_reason_bounce(conn: sqlite3.Connection) -> None:
    unsub.record_unsubscribe(conn, "bounce@example.com", reason=unsub.REASON_BOUNCE)
    row = conn.execute(
        "SELECT reason FROM email_unsubscribes WHERE email = ?",
        ("bounce@example.com",),
    ).fetchone()
    assert row[0] == unsub.REASON_BOUNCE


def test_record_unsubscribe_returns_false_on_db_error() -> None:
    c = sqlite3.connect(":memory:")
    c.close()
    assert unsub.record_unsubscribe(c, "x@example.com") is False


def test_record_unsubscribe_duplicate_does_not_overwrite_original_time(
    conn: sqlite3.Connection,
) -> None:
    unsub.record_unsubscribe(conn, "orig@example.com")
    first = conn.execute(
        "SELECT unsubscribed_at FROM email_unsubscribes WHERE email = ?",
        ("orig@example.com",),
    ).fetchone()[0]
    # A subsequent INSERT OR IGNORE must NOT update unsubscribed_at.
    unsub.record_unsubscribe(conn, "orig@example.com")
    second = conn.execute(
        "SELECT unsubscribed_at FROM email_unsubscribes WHERE email = ?",
        ("orig@example.com",),
    ).fetchone()[0]
    assert first == second


# ---------------------------------------------------------------------------
# _redact + _normalise
# ---------------------------------------------------------------------------


def test_redact_short_local_part() -> None:
    assert unsub._redact("a@example.com") == "*@example.com"


def test_redact_normal_address() -> None:
    assert unsub._redact("alice@example.com") == "a***@example.com"


def test_redact_no_at_sign_returns_mask() -> None:
    assert unsub._redact("not-an-email") == "***"


def test_normalise_lowercases_and_strips() -> None:
    assert unsub._normalise("  Mixed@Example.COM  ") == "mixed@example.com"


# ---------------------------------------------------------------------------
# Module surface invariants
# ---------------------------------------------------------------------------


def test_module_exports_canonical_names() -> None:
    expected = {
        "REASON_BOUNCE",
        "REASON_MANUAL_OPS",
        "REASON_MAX_LEN",
        "REASON_SPAM_COMPLAINT",
        "REASON_USER_SELF_SERVE",
        "is_unsubscribed",
        "record_unsubscribe",
    }
    assert set(unsub.__all__) == expected


def test_reason_max_len_is_sensible() -> None:
    assert unsub.REASON_MAX_LEN == 64
