"""Integration tests for Dim L session-context storage (Wave 47).

Closes the Wave 46 dim L storage gap: persists session metadata in
``am_session_context`` and per-step audit in ``am_session_step_log``
(mig 272) and proves the 24h TTL purge (``clean_session_context_expired.py``)
behaves correctly. Also asserts wiring discipline against PR #144's
in-process LRU REST surface (``src/jpintel_mcp/api/session_context.py``):
the kernel must remain in-process, but its boundary contract must align
with the SQL row shape (state_token len=32, TTL_SEC=86400, saved_context
cap 16 KiB, step cap 32).

Six case bundles:
  1. Migration 272 applies cleanly on a fresh SQLite db (idempotent re-apply).
  2. Migration 272 rollback drops every artefact created.
  3. TTL purge marks expired rows + deletes 7-day-old expired/closed rows.
  4. TTL purge cleans orphan step-log rows + 7-day-aged step-log rows.
  5. ``--dry-run`` reports counts but writes nothing.
  6. REST kernel boundary contract (TTL_SEC, token length, step cap)
     matches the SQL schema (CHECK constraints in mig 272).

Hard constraints exercised
--------------------------
  * No LLM SDK import in any new file (Dim L cleanup is deterministic).
  * Migration table names match the REST surface comments
    (am_session_context / am_session_step_log).
  * Idempotent re-apply: a 2nd run of mig 272 is a no-op.
  * Brand: only jpcite (and historical autonomath db filename). No
    legacy ``税務会計AI`` / ``zeimu-kaikei.ai``.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sqlite3
import subprocess
import sys
import time

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_272 = REPO_ROOT / "scripts" / "migrations" / "272_session_context.sql"
MIG_272_RB = REPO_ROOT / "scripts" / "migrations" / "272_session_context_rollback.sql"
ETL_CLEAN = REPO_ROOT / "scripts" / "etl" / "clean_session_context_expired.py"
SRC_SESSION = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "session_context.py"
MANIFEST_JPCITE = REPO_ROOT / "scripts" / "migrations" / "jpcite_boot_manifest.txt"
MANIFEST_AM = REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_session_module():
    """Load the session_context module by file path (avoids package init)."""
    spec = importlib.util.spec_from_file_location("_session_test_w47_mod", SRC_SESSION)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_session_test_w47_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def _apply_migration(db_path: pathlib.Path, sql_path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        sql = sql_path.read_text(encoding="utf-8")
        conn.executescript(sql)
    finally:
        conn.close()


def _fresh_db_with_migration(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "session_test.db"
    _apply_migration(db, MIG_272)
    return db


def _insert_session(
    db_path: pathlib.Path,
    *,
    session_id: str,
    expires_at: int,
    saved_context: str = "{}",
    status: str = "open",
    closed_at: int | None = None,
    last_step_at: int | None = None,
) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO am_session_context "
            "(session_id, state_token, saved_context, expires_at, "
            " status, closed_at, last_step_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                session_id,
                saved_context,
                expires_at,
                status,
                closed_at,
                last_step_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_step(
    db_path: pathlib.Path,
    *,
    session_id: str,
    step_index: int,
    created_at: str | None = None,
) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        if created_at is None:
            conn.execute(
                "INSERT INTO am_session_step_log "
                "(session_id, step_index, request_hash, response_hash) "
                "VALUES (?, ?, ?, ?)",
                (
                    session_id,
                    step_index,
                    "req_" + str(step_index).rjust(3, "0"),
                    "res_" + str(step_index).rjust(3, "0"),
                ),
            )
        else:
            conn.execute(
                "INSERT INTO am_session_step_log "
                "(session_id, step_index, request_hash, response_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    step_index,
                    "req_" + str(step_index).rjust(3, "0"),
                    "res_" + str(step_index).rjust(3, "0"),
                    created_at,
                ),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case 1 — Migration apply + idempotent
# ---------------------------------------------------------------------------


def test_migration_272_creates_tables(tmp_path: pathlib.Path) -> None:
    """Migration 272 creates am_session_context + am_session_step_log + view."""
    db = _fresh_db_with_migration(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "am_session_context" in names
    assert "am_session_step_log" in names
    assert "v_session_context_alive" in names


def test_migration_272_idempotent(tmp_path: pathlib.Path) -> None:
    """Re-applying migration 272 is a no-op (every CREATE uses IF NOT EXISTS)."""
    db = _fresh_db_with_migration(tmp_path)
    # Second apply must not raise.
    _apply_migration(db, MIG_272)
    conn = sqlite3.connect(str(db))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='am_session_context'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


# ---------------------------------------------------------------------------
# Case 2 — Migration rollback drops everything
# ---------------------------------------------------------------------------


def test_migration_272_rollback_drops(tmp_path: pathlib.Path) -> None:
    """Rollback drops the storage surface cleanly."""
    db = _fresh_db_with_migration(tmp_path)
    _apply_migration(db, MIG_272_RB)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "am_session_context" not in names
    assert "am_session_step_log" not in names
    assert "v_session_context_alive" not in names


# ---------------------------------------------------------------------------
# Case 3 — TTL purge: mark expired + delete aged
# ---------------------------------------------------------------------------


def _run_clean(db: pathlib.Path, *, dry_run: bool = False) -> dict:
    args = [sys.executable, str(ETL_CLEAN), "--db", str(db)]
    if dry_run:
        args.append("--dry-run")
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"stderr={result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_purge_marks_expired_rows(tmp_path: pathlib.Path) -> None:
    """TTL purge flips status='open' → 'expired' for rows past their TTL."""
    db = _fresh_db_with_migration(tmp_path)
    now = int(time.time())
    # Two expired (TTL elapsed), one still alive.
    _insert_session(db, session_id="a" * 32, expires_at=now - 100)
    _insert_session(db, session_id="b" * 32, expires_at=now - 1)
    _insert_session(db, session_id="c" * 32, expires_at=now + 3600)
    payload = _run_clean(db)
    assert payload["purge_stats"]["expired_marked"] == 2
    assert payload["purge_stats"]["alive_remaining"] == 1
    conn = sqlite3.connect(str(db))
    try:
        status_a = conn.execute(
            "SELECT status FROM am_session_context WHERE session_id=?",
            ("a" * 32,),
        ).fetchone()[0]
        status_c = conn.execute(
            "SELECT status FROM am_session_context WHERE session_id=?",
            ("c" * 32,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert status_a == "expired"
    assert status_c == "open"


def test_purge_deletes_aged_expired_rows(tmp_path: pathlib.Path) -> None:
    """Rows past the 7-day forensic window get deleted."""
    db = _fresh_db_with_migration(tmp_path)
    now = int(time.time())
    eight_days_ago = now - 8 * 24 * 3600
    one_day_ago = now - 1 * 24 * 3600
    _insert_session(
        db,
        session_id="o" * 32,
        expires_at=eight_days_ago,
        status="expired",
    )
    _insert_session(
        db,
        session_id="n" * 32,
        expires_at=one_day_ago,
        status="expired",
    )
    _insert_session(
        db,
        session_id="c" * 32,
        expires_at=eight_days_ago,
        status="closed",
        closed_at=eight_days_ago,
    )
    payload = _run_clean(db)
    assert payload["purge_stats"]["context_deleted"] == 2
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT session_id FROM am_session_context ORDER BY session_id"
        ).fetchall()
    finally:
        conn.close()
    remaining = {r[0] for r in rows}
    assert remaining == {"n" * 32}


# ---------------------------------------------------------------------------
# Case 4 — Step log: orphan deletion + 7-day aging
# ---------------------------------------------------------------------------


def test_purge_deletes_orphan_step_log(tmp_path: pathlib.Path) -> None:
    """Step-log rows without a parent session row get deleted."""
    db = _fresh_db_with_migration(tmp_path)
    # Live parent + step.
    now = int(time.time())
    _insert_session(db, session_id="x" * 32, expires_at=now + 3600)
    _insert_step(db, session_id="x" * 32, step_index=1)
    # Orphan step (no parent in am_session_context).
    _insert_step(db, session_id="y" * 32, step_index=1)
    _insert_step(db, session_id="y" * 32, step_index=2)
    payload = _run_clean(db)
    assert payload["purge_stats"]["step_log_orphan_deleted"] == 2
    conn = sqlite3.connect(str(db))
    try:
        sessions = {
            r[0]
            for r in conn.execute("SELECT DISTINCT session_id FROM am_session_step_log").fetchall()
        }
    finally:
        conn.close()
    assert sessions == {"x" * 32}


def test_purge_deletes_aged_step_log(tmp_path: pathlib.Path) -> None:
    """Step-log rows older than 7 days get deleted even with a live parent."""
    db = _fresh_db_with_migration(tmp_path)
    now = int(time.time())
    _insert_session(db, session_id="z" * 32, expires_at=now + 3600)
    aged_iso = time.strftime("%Y-%m-%dT%H:%M:%fZ", time.gmtime(now - 9 * 24 * 3600))
    fresh_iso = time.strftime("%Y-%m-%dT%H:%M:%fZ", time.gmtime(now - 1 * 24 * 3600))
    _insert_step(db, session_id="z" * 32, step_index=1, created_at=aged_iso)
    _insert_step(db, session_id="z" * 32, step_index=2, created_at=fresh_iso)
    payload = _run_clean(db)
    assert payload["purge_stats"]["step_log_aged_deleted"] == 1
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT step_index FROM am_session_step_log ORDER BY step_index"
        ).fetchall()
    finally:
        conn.close()
    assert [r[0] for r in rows] == [2]


# ---------------------------------------------------------------------------
# Case 5 — Dry-run writes nothing
# ---------------------------------------------------------------------------


def test_dry_run_writes_nothing(tmp_path: pathlib.Path) -> None:
    """--dry-run reports counts identical to a real run, but DB stays put."""
    db = _fresh_db_with_migration(tmp_path)
    now = int(time.time())
    _insert_session(db, session_id="d" * 32, expires_at=now - 100)
    _insert_session(
        db,
        session_id="e" * 32,
        expires_at=now - 8 * 24 * 3600,
        status="expired",
    )
    payload = _run_clean(db, dry_run=True)
    assert payload["dry_run"] is True
    assert payload["purge_stats"]["expired_marked"] == 1
    assert payload["purge_stats"]["context_deleted"] == 1
    # Real state unchanged.
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_session_context").fetchone()[0]
        n_expired = conn.execute(
            "SELECT COUNT(*) FROM am_session_context WHERE status='expired'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 2
    # Only `e` was inserted as expired; `d` should still be 'open' after dry-run.
    assert n_expired == 1


# ---------------------------------------------------------------------------
# Case 6 — REST kernel boundary contract aligns with SQL schema
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def session_module():
    return _import_session_module()


def test_kernel_ttl_matches_24h(session_module) -> None:
    """REST kernel SESSION_TTL_SEC = 24h (mirrored by mig 272 expires_at)."""
    assert session_module.SESSION_TTL_SEC == 24 * 60 * 60


def test_kernel_token_length_matches_schema(session_module) -> None:
    """REST kernel mints hex 32-char tokens; mig 272 enforces len=32."""
    # The kernel's _new_token() is hex(16) → 32 chars. Mig 272 CHECK ensures it.
    db_path = pathlib.Path("/tmp/_w47_kernel_token_probe.db")
    if db_path.exists():
        db_path.unlink()
    try:
        _apply_migration(db_path, MIG_272)
        token = session_module._new_token()
        assert len(token) == 32
        # Inserting a malformed (len != 32) token must be rejected by CHECK.
        conn = sqlite3.connect(str(db_path))
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO am_session_context "
                    "(session_id, state_token, expires_at) VALUES (?, ?, ?)",
                    ("bad", "bad", int(time.time()) + 3600),
                )
        finally:
            conn.close()
    finally:
        if db_path.exists():
            db_path.unlink()


def test_kernel_step_cap_matches_schema(session_module) -> None:
    """REST kernel _MAX_STEPS_PER_SESSION = 32; SQL step_log step_index CHECK >= 1."""
    assert session_module._MAX_STEPS_PER_SESSION == 32
    db_path = pathlib.Path("/tmp/_w47_kernel_step_cap_probe.db")
    if db_path.exists():
        db_path.unlink()
    try:
        _apply_migration(db_path, MIG_272)
        conn = sqlite3.connect(str(db_path))
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO am_session_step_log "
                    "(session_id, step_index, request_hash, response_hash) "
                    "VALUES (?, ?, ?, ?)",
                    ("a" * 32, 0, "r", "s"),
                )
        finally:
            conn.close()
    finally:
        if db_path.exists():
            db_path.unlink()


# ---------------------------------------------------------------------------
# Boot-manifest integrity
# ---------------------------------------------------------------------------


def test_manifest_jpcite_lists_272() -> None:
    """jpcite boot manifest registers migration 272_session_context.sql."""
    assert "272_session_context.sql" in MANIFEST_JPCITE.read_text(encoding="utf-8")


def test_manifest_autonomath_lists_272() -> None:
    """autonomath boot manifest (mirror) registers migration 272."""
    assert "272_session_context.sql" in MANIFEST_AM.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# No-LLM-import + brand discipline + REST kernel untouched
# ---------------------------------------------------------------------------


_FORBIDDEN_LLM_IMPORTS = ("anthropic", "openai", "google.generativeai")


def test_no_llm_import_in_etl_or_migration() -> None:
    """Dim L storage MUST stay LLM-free (feedback_no_operator_llm_api)."""
    sources = [
        ETL_CLEAN.read_text(encoding="utf-8"),
        MIG_272.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in _FORBIDDEN_LLM_IMPORTS:
            assert f"import {bad}" not in src
            assert f"from {bad}" not in src


def test_no_legacy_brand_in_new_files() -> None:
    """No 税務会計AI / zeimu-kaikei.ai legacy brand in new files."""
    legacy_phrases = ("税務会計AI", "zeimu-kaikei.ai")
    sources = [
        ETL_CLEAN.read_text(encoding="utf-8"),
        MIG_272.read_text(encoding="utf-8"),
        MIG_272_RB.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in legacy_phrases:
            assert bad not in src, f"legacy brand `{bad}` found in new file"


def test_rest_surface_untouched_by_w47() -> None:
    """Wave 47 must NOT rewire PR #144's REST kernel to read/write SQL.

    Guard: the REST surface continues to rely on the in-process LRU `dict`
    primitive (`_SESSIONS: OrderedDict`). Wave 47 is purely additive at
    the storage layer. If a follow-up wave wires SQL sync, this test
    should be relaxed deliberately, not silently.
    """
    src = SRC_SESSION.read_text(encoding="utf-8")
    # The REST kernel must still reference its in-process primitive.
    assert "_SESSIONS: OrderedDict" in src
    # Wave 47 has not introduced an SQL import path into the REST kernel.
    assert "am_session_context" not in src
    assert "am_session_step_log" not in src
