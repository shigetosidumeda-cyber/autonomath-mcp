"""Wave18 Q1 — vec0 (sqlite-vec) runtime wire-up tests.

Three cases:

1. With AUTONOMATH_VEC0_PATH set to a real .so/.dylib, the vec0 module is
   registered into the connection — `CREATE VIRTUAL TABLE ... USING vec0`
   does NOT raise `no such module: vec0`.
2. With AUTONOMATH_VEC0_PATH unset (or pointing at a non-existent file), the
   connection still comes up cleanly. Graceful degrade: vec failure must
   not break API/MCP boot.
3. The production `am_entities_vec` table (when present) is queryable via a
   bare `SELECT ... LIMIT 1` after wire-up.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.db.session import connect


@pytest.mark.skipif(
    not os.environ.get("AUTONOMATH_VEC0_PATH")
    or not Path(os.environ.get("AUTONOMATH_VEC0_PATH", "")).exists(),
    reason="vec0 .so/.dylib not present (set AUTONOMATH_VEC0_PATH)",
)
def test_vec0_module_registered_on_connect(tmp_path):
    """vec0 module call must not surface `no such module`."""
    db = tmp_path / "vec0_smoke.db"
    conn = connect(db)
    try:
        # Creating a virtual table proves the module is registered into
        # this specific connection (vec0 modules are per-connection).
        conn.execute("CREATE VIRTUAL TABLE t USING vec0(v float[4])")
        conn.execute(
            "INSERT INTO t(rowid, v) VALUES (1, '[0.1,0.2,0.3,0.4]')"
        )
        rows = conn.execute("SELECT rowid FROM t LIMIT 1").fetchall()
        assert rows and rows[0][0] == 1
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        assert "no such module" not in msg, (
            f"vec0 not loaded into connect()-returned conn: {e}"
        )
        raise
    finally:
        conn.close()


def test_vec0_absent_path_graceful_degrade(tmp_path, monkeypatch):
    """Bad/missing vec0 path must not break connect()."""
    monkeypatch.setenv("AUTONOMATH_VEC0_PATH", "/nonexistent/vec0.so")
    db = tmp_path / "vec0_degrade.db"
    conn = connect(db)
    try:
        # Connection must still service ordinary queries.
        row = conn.execute("SELECT 1").fetchone()
        assert row[0] == 1
    finally:
        conn.close()


def test_vec0_unset_env_graceful_degrade(tmp_path, monkeypatch):
    """No AUTONOMATH_VEC0_PATH at all = silent skip + working connection."""
    monkeypatch.delenv("AUTONOMATH_VEC0_PATH", raising=False)
    db = tmp_path / "vec0_unset.db"
    conn = connect(db)
    try:
        row = conn.execute("SELECT 1").fetchone()
        assert row[0] == 1
    finally:
        conn.close()


@pytest.mark.skipif(
    not os.environ.get("AUTONOMATH_VEC0_PATH")
    or not Path(os.environ.get("AUTONOMATH_VEC0_PATH", "")).exists(),
    reason="vec0 .so/.dylib not present (set AUTONOMATH_VEC0_PATH)",
)
def test_am_entities_vec_queryable_when_present():
    """If autonomath.db ships am_entities_vec, a bare SELECT must succeed."""
    from jpintel_mcp.mcp.autonomath_tools.db import (
        AUTONOMATH_DB_PATH,
        connect_autonomath,
    )

    if not AUTONOMATH_DB_PATH.exists():
        pytest.skip(f"autonomath.db not present at {AUTONOMATH_DB_PATH}")

    conn = connect_autonomath()
    try:
        # Confirm the vec0 table exists in schema before attempting query.
        row = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='am_entities_vec'"
        ).fetchone()
        if row is None:
            pytest.skip("am_entities_vec not in this autonomath.db build")
        # Bare COUNT(*) — proves vec0 module is registered in the conn.
        # vec0 virtual tables don't expose rowid as a regular column, so
        # use COUNT(*) which any vec0 table will accept.
        conn.execute("SELECT COUNT(*) FROM am_entities_vec").fetchone()
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        assert "no such module" not in msg, (
            f"vec0 not loaded into connect_autonomath() conn: {e}"
        )
        raise
