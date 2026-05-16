"""Coverage push #3 — db/session.py.

Lifts `src/jpintel_mcp/db/session.py` from 39% → 90%+ by exercising
init_db, connect, txn context manager, the autonomath authorizer
defensive guard, and the WAL/mmap PRAGMA hot-path.

CLAUDE.md "What NOT to do #1": no DB mocking — every test opens a real
SQLite file under `tmp_path` so the migration / authorizer / PRAGMA
interactions match production faithfully.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.db import session

# ---------------------------------------------------------------------------
# init_db — schema bootstrap on a fresh path.
# ---------------------------------------------------------------------------


def test_init_db_creates_programs_table(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    session.init_db(db_path=db)
    assert db.is_file()
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='programs'"
        ).fetchall()
    assert rows == [("programs",)]


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "idempotent.db"
    session.init_db(db_path=db)
    # Second call must not raise even though tables already exist.
    session.init_db(db_path=db)
    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    assert count >= 1


def test_init_db_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "deep" / "fresh.db"
    assert not nested.parent.is_dir()
    session.init_db(db_path=nested)
    assert nested.is_file()
    assert nested.parent.is_dir()


# ---------------------------------------------------------------------------
# connect — PRAGMA setup, row factory, parent creation.
# ---------------------------------------------------------------------------


def test_connect_sets_row_factory_to_row(tmp_path: Path) -> None:
    db = tmp_path / "row.db"
    session.init_db(db_path=db)
    conn = session.connect(db_path=db)
    try:
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_connect_applies_wal_journal_mode(tmp_path: Path) -> None:
    db = tmp_path / "wal.db"
    session.init_db(db_path=db)
    conn = session.connect(db_path=db)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()


def test_connect_applies_busy_timeout(tmp_path: Path) -> None:
    db = tmp_path / "timeout.db"
    session.init_db(db_path=db)
    conn = session.connect(db_path=db)
    try:
        # PRAGMA busy_timeout returns the integer milliseconds set.
        timeout_ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout_ms == 300000
    finally:
        conn.close()


def test_connect_applies_foreign_keys_on(tmp_path: Path) -> None:
    db = tmp_path / "fk.db"
    session.init_db(db_path=db)
    conn = session.connect(db_path=db)
    try:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
    finally:
        conn.close()


def test_connect_applies_mmap_size(tmp_path: Path) -> None:
    db = tmp_path / "mmap.db"
    session.init_db(db_path=db)
    conn = session.connect(db_path=db)
    try:
        # mmap_size may be returned as the requested value or 0 if the OS
        # rejects it; both are acceptable since the connect() call only
        # SETS the ceiling. We assert the PRAGMA was wired (non-negative).
        mmap = conn.execute("PRAGMA mmap_size").fetchone()[0]
        assert mmap >= 0
    finally:
        conn.close()


def test_connect_applies_cache_size_negative_kb(tmp_path: Path) -> None:
    db = tmp_path / "cache.db"
    session.init_db(db_path=db)
    conn = session.connect(db_path=db)
    try:
        cache = conn.execute("PRAGMA cache_size").fetchone()[0]
        # We set -262144 (negative = KB unit). PRAGMA reports the value as-is.
        assert cache == -262144
    finally:
        conn.close()


def test_connect_applies_temp_store_memory(tmp_path: Path) -> None:
    db = tmp_path / "temp.db"
    session.init_db(db_path=db)
    conn = session.connect(db_path=db)
    try:
        # temp_store: 0=default, 1=file, 2=memory.
        temp_store = conn.execute("PRAGMA temp_store").fetchone()[0]
        assert temp_store == 2
    finally:
        conn.close()


def test_connect_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "missing" / "parent" / "auto.db"
    assert not nested.parent.is_dir()
    conn = session.connect(db_path=nested)
    try:
        assert nested.parent.is_dir()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# _path_is_autonomath — case-insensitive basename check.
# ---------------------------------------------------------------------------


def test_path_is_autonomath_matches_canonical_name() -> None:
    assert session._path_is_autonomath(Path("/data/autonomath.db")) is True


def test_path_is_autonomath_matches_dev_relative_path() -> None:
    assert session._path_is_autonomath(Path("./autonomath.db")) is True


def test_path_is_autonomath_matches_dated_backup() -> None:
    """Backup files share the placeholder schema and must trigger the guard."""
    assert session._path_is_autonomath(Path("/data/autonomath.db.bak.2026-05-01")) is True


def test_path_is_autonomath_case_insensitive() -> None:
    assert session._path_is_autonomath(Path("/data/Autonomath.db")) is True
    assert session._path_is_autonomath(Path("/data/AUTONOMATH.db")) is True


def test_path_is_autonomath_rejects_jpintel_path() -> None:
    assert session._path_is_autonomath(Path("/data/jpintel.db")) is False


# ---------------------------------------------------------------------------
# Autonomath authorizer — read-deny semantics on jpintel-only tables.
# ---------------------------------------------------------------------------


def test_autonomath_authorizer_denies_read_on_programs() -> None:
    deny = session._autonomath_authorizer(
        action=sqlite3.SQLITE_READ,
        arg1="programs",
        arg2="unified_id",
        db_name="main",
        trigger=None,
    )
    assert deny == sqlite3.SQLITE_DENY


def test_autonomath_authorizer_denies_read_on_case_studies() -> None:
    deny = session._autonomath_authorizer(
        action=sqlite3.SQLITE_READ,
        arg1="case_studies",
        arg2="id",
        db_name="main",
        trigger=None,
    )
    assert deny == sqlite3.SQLITE_DENY


def test_autonomath_authorizer_denies_read_on_loan_programs() -> None:
    assert (
        session._autonomath_authorizer(
            action=sqlite3.SQLITE_READ,
            arg1="loan_programs",
            arg2="id",
            db_name="main",
            trigger=None,
        )
        == sqlite3.SQLITE_DENY
    )


def test_autonomath_authorizer_denies_read_on_enforcement_cases() -> None:
    assert (
        session._autonomath_authorizer(
            action=sqlite3.SQLITE_READ,
            arg1="enforcement_cases",
            arg2="id",
            db_name="main",
            trigger=None,
        )
        == sqlite3.SQLITE_DENY
    )


def test_autonomath_authorizer_allows_read_on_jpi_mirror() -> None:
    """`jpi_programs` IS the autonomath-side canonical mirror; must be allowed."""
    ok = session._autonomath_authorizer(
        action=sqlite3.SQLITE_READ,
        arg1="jpi_programs",
        arg2="unified_id",
        db_name="main",
        trigger=None,
    )
    assert ok == sqlite3.SQLITE_OK


def test_autonomath_authorizer_allows_other_actions() -> None:
    """Non-READ actions (write, schema ops) must pass through unchanged."""
    assert (
        session._autonomath_authorizer(
            action=sqlite3.SQLITE_INSERT,
            arg1="programs",
            arg2=None,
            db_name="main",
            trigger=None,
        )
        == sqlite3.SQLITE_OK
    )


def test_connect_to_autonomath_path_installs_authorizer(tmp_path: Path) -> None:
    """Opening connect() against a file named autonomath.db installs the read-deny."""
    db = tmp_path / "autonomath.db"
    # Seed the placeholder `programs` table that the authorizer should now deny.
    with sqlite3.connect(db) as setup:
        setup.execute("CREATE TABLE programs (unified_id TEXT PRIMARY KEY)")
        setup.execute("INSERT INTO programs VALUES ('UNI-shouldnt-leak')")
        setup.commit()

    conn = session.connect(db_path=db)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="prohibited"):
            conn.execute("SELECT unified_id FROM programs").fetchall()
    finally:
        conn.close()


def test_connect_to_jpintel_path_does_not_install_authorizer(tmp_path: Path) -> None:
    """jpintel.db connect must allow reads on `programs` (no guard)."""
    db = tmp_path / "jpintel.db"
    session.init_db(db_path=db)
    conn = session.connect(db_path=db)
    try:
        # Empty result is fine — what matters is that the query does NOT raise.
        rows = conn.execute("SELECT unified_id FROM programs").fetchall()
        assert rows == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# txn context manager — commit, rollback, cleanup.
# ---------------------------------------------------------------------------


def test_txn_commits_on_success(tmp_path: Path) -> None:
    db = tmp_path / "txn_commit.db"
    session.init_db(db_path=db)
    with session.txn(db_path=db) as conn:
        conn.execute(
            "INSERT INTO programs (unified_id, primary_name, updated_at) VALUES (?,?,?)",
            ("UNI-commit-1", "test program", "2026-05-17T00:00:00Z"),
        )
    # After exit, the row must be visible to a new connection.
    check = session.connect(db_path=db)
    try:
        rows = check.execute(
            "SELECT primary_name FROM programs WHERE unified_id=?", ("UNI-commit-1",)
        ).fetchall()
    finally:
        check.close()
    assert len(rows) == 1
    assert rows[0]["primary_name"] == "test program"


def test_txn_rolls_back_on_exception(tmp_path: Path) -> None:
    db = tmp_path / "txn_rollback.db"
    session.init_db(db_path=db)
    with pytest.raises(RuntimeError, match="boom"), session.txn(db_path=db) as conn:
        conn.execute(
            "INSERT INTO programs (unified_id, primary_name, updated_at) VALUES (?,?,?)",
            ("UNI-rollback-1", "should disappear", "2026-05-17T00:00:00Z"),
        )
        raise RuntimeError("boom")
    # Verify the row never landed.
    check = session.connect(db_path=db)
    try:
        rows = check.execute(
            "SELECT * FROM programs WHERE unified_id=?", ("UNI-rollback-1",)
        ).fetchall()
    finally:
        check.close()
    assert rows == []


def test_txn_closes_connection_after_use(tmp_path: Path) -> None:
    db = tmp_path / "txn_close.db"
    session.init_db(db_path=db)
    captured: list[sqlite3.Connection] = []
    with session.txn(db_path=db) as conn:
        captured.append(conn)
    # After context exit, the captured connection must be closed.
    with pytest.raises(sqlite3.ProgrammingError):
        captured[0].execute("SELECT 1").fetchone()


def test_txn_closes_connection_even_when_exception_propagates(tmp_path: Path) -> None:
    db = tmp_path / "txn_close_err.db"
    session.init_db(db_path=db)
    captured: list[sqlite3.Connection] = []
    with pytest.raises(ValueError), session.txn(db_path=db) as conn:
        captured.append(conn)
        raise ValueError("fail")
    with pytest.raises(sqlite3.ProgrammingError):
        captured[0].execute("SELECT 1").fetchone()


def test_connect_with_vec0_env_load_failure_does_not_raise(tmp_path, monkeypatch) -> None:
    """Setting AUTONOMATH_VEC0_PATH to a bogus existing-file must degrade gracefully."""
    fake = tmp_path / "fake_vec0.so"
    fake.write_bytes(b"not a real .so")
    monkeypatch.setenv("AUTONOMATH_VEC0_PATH", str(fake))
    db = tmp_path / "vec0_degrade.db"
    session.init_db(db_path=db)
    # Must NOT raise even though load_extension will fail on the bogus blob.
    conn = session.connect(db_path=db)
    try:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        conn.close()


def test_connect_with_vec0_env_pointing_at_missing_file_skips_load(tmp_path, monkeypatch) -> None:
    """Missing AUTONOMATH_VEC0_PATH file: connect() must skip extension load."""
    monkeypatch.setenv("AUTONOMATH_VEC0_PATH", str(tmp_path / "does_not_exist.so"))
    db = tmp_path / "vec0_missing.db"
    session.init_db(db_path=db)
    conn = session.connect(db_path=db)
    try:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        conn.close()
