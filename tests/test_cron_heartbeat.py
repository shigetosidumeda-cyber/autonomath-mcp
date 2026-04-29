"""Tests for the cron heartbeat helper + /v1/admin/cron_runs read-side.

Coverage:
  1. Success path: rows_processed/rows_skipped/metadata land in cron_runs
     with status='ok'.
  2. Failure path: exception inside the context writes status='error' +
     captures the truncated error_message + re-raises.
  3. The heartbeat connection is autocommit (separate from any cron-side
     transaction) — a rollback in the caller cannot wipe the heartbeat row.
  4. /v1/admin/cron_runs requires the admin key (auth gate).
  5. /v1/admin/cron_runs returns rows + status_counts when the table is
     populated; gracefully no-ops when the table is missing.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helper module unit tests (no FastAPI client needed)
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_db(monkeypatch) -> Path:
    """Standalone temp DB so the heartbeat unit tests don't pollute the
    session-scoped `seeded_db` fixture (which other admin tests rely on).
    """
    fd, path = tempfile.mkstemp(prefix="cron-heartbeat-", suffix=".db")
    os.close(fd)
    db_path = Path(path)
    # Heartbeat helper reads JPINTEL_DB_PATH via os.environ at call time.
    monkeypatch.setenv("JPINTEL_DB_PATH", str(db_path))
    yield db_path
    db_path.unlink(missing_ok=True)


def test_heartbeat_success_writes_ok_row(isolated_db: Path) -> None:
    from jpintel_mcp.observability import heartbeat

    with heartbeat("test_cron_ok") as hb:
        hb["rows_processed"] = 5
        hb["rows_skipped"] = 2
        hb["metadata"] = {"window_hours": 24, "billed": 3}

    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT cron_name, status, rows_processed, rows_skipped, "
            "       error_message, metadata_json, started_at, finished_at "
            "  FROM cron_runs WHERE cron_name = ?",
            ("test_cron_ok",),
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "ok"
    assert row["rows_processed"] == 5
    assert row["rows_skipped"] == 2
    assert row["error_message"] is None
    assert row["started_at"] is not None
    assert row["finished_at"] is not None
    meta = json.loads(row["metadata_json"])
    assert meta["window_hours"] == 24
    assert meta["billed"] == 3


def test_heartbeat_failure_writes_error_row_and_reraises(
    isolated_db: Path,
) -> None:
    from jpintel_mcp.observability import heartbeat

    with pytest.raises(RuntimeError, match="kaboom"):
        with heartbeat("test_cron_fail") as hb:
            hb["rows_processed"] = 7
            raise RuntimeError("kaboom: thing exploded")

    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT cron_name, status, rows_processed, error_message "
            "  FROM cron_runs WHERE cron_name = ?",
            ("test_cron_fail",),
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "error"
    # Counters captured up to the point of failure are persisted.
    assert row["rows_processed"] == 7
    assert row["error_message"] == "RuntimeError: kaboom: thing exploded"


def test_heartbeat_uses_autocommit_separate_from_caller_transaction(
    isolated_db: Path,
) -> None:
    """Heartbeat must not be roll-backable by the caller's own connection.

    The cron's own work might be wrapped in a sqlite transaction. If the
    cron commits its transaction and then the heartbeat write happened to
    share that connection, the heartbeat would commit too — fine. But if
    the cron crashes mid-transaction, ROLLBACK on its own connection
    must NOT wipe the heartbeat row.
    """
    from jpintel_mcp.observability import heartbeat

    # Open a separate connection, start a transaction, and roll it back —
    # mimicking a cron that crashes mid-flight. The heartbeat helper writes
    # via its own autocommit connection, so its row must survive.
    cron_conn = sqlite3.connect(isolated_db)
    try:
        cron_conn.execute("BEGIN")
        try:
            with heartbeat("test_cron_txn") as hb:
                hb["rows_processed"] = 1
            # Caller decides to roll back unrelated work.
            cron_conn.execute("ROLLBACK")
        except Exception:
            cron_conn.execute("ROLLBACK")
            raise
    finally:
        cron_conn.close()

    verify = sqlite3.connect(isolated_db)
    try:
        n = verify.execute(
            "SELECT COUNT(*) FROM cron_runs WHERE cron_name = ?",
            ("test_cron_txn",),
        ).fetchone()[0]
    finally:
        verify.close()
    assert n == 1, "rollback on caller's connection wiped the heartbeat row"


def test_heartbeat_truncates_long_error_message(isolated_db: Path) -> None:
    """error_message is capped (default 500 chars) so a runaway stack
    cannot bloat the DB or leak too much PII into operator views.
    """
    from jpintel_mcp.observability import heartbeat

    big = "x" * 1200
    with pytest.raises(ValueError):
        with heartbeat("test_cron_big_err"):
            raise ValueError(big)

    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT error_message FROM cron_runs WHERE cron_name = ?",
            ("test_cron_big_err",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert len(row["error_message"]) <= 500
    assert row["error_message"].endswith("...")


# ---------------------------------------------------------------------------
# Admin route — /v1/admin/cron_runs
# ---------------------------------------------------------------------------


_ADMIN_KEY = "test-admin-cron-secret"


@pytest.fixture()
def admin_enabled(monkeypatch):
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "admin_api_key", _ADMIN_KEY, raising=False)
    yield _ADMIN_KEY


@pytest.fixture()
def cron_runs_seed(seeded_db: Path):
    """Populate cron_runs in the shared seeded_db so the route returns rows."""
    conn = sqlite3.connect(seeded_db)
    try:
        # Ensure the table exists even on a fresh test DB (mig 102 may not
        # have run via the test harness — the heartbeat helper auto-creates,
        # but the route reads directly).
        conn.execute(
            """CREATE TABLE IF NOT EXISTS cron_runs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                cron_name       TEXT NOT NULL,
                started_at      TEXT NOT NULL,
                finished_at     TEXT,
                status          TEXT NOT NULL,
                rows_processed  INTEGER,
                rows_skipped    INTEGER,
                error_message   TEXT,
                metadata_json   TEXT,
                workflow_run_id TEXT,
                git_sha         TEXT
            )"""
        )
        conn.execute("DELETE FROM cron_runs")
        conn.executemany(
            """INSERT INTO cron_runs (
                   cron_name, started_at, finished_at, status,
                   rows_processed, rows_skipped, error_message,
                   metadata_json, workflow_run_id, git_sha
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                # Two recent runs of run_saved_searches: one ok, one error.
                (
                    "run_saved_searches",
                    "2030-04-29T01:00:00Z",
                    "2030-04-29T01:00:05Z",
                    "ok",
                    7, 0, None,
                    json.dumps({"billed": 7, "frequency": "daily"}),
                    "wf-1", "abc12345",
                ),
                (
                    "run_saved_searches",
                    "2030-04-29T02:00:00Z",
                    "2030-04-29T02:00:01Z",
                    "error",
                    0, 0, "RuntimeError: postmark 503",
                    None, "wf-2", "abc12345",
                ),
                # One ok run of dispatch_webhooks.
                (
                    "dispatch_webhooks",
                    "2030-04-29T01:30:00Z",
                    "2030-04-29T01:30:02Z",
                    "ok",
                    12, 3, None, None, "wf-1", "abc12345",
                ),
            ],
        )
        conn.commit()
        yield
    finally:
        conn.execute("DROP TABLE IF EXISTS cron_runs")
        conn.commit()
        conn.close()


def test_admin_cron_runs_401_without_key(client, admin_enabled):
    r = client.get("/v1/admin/cron_runs")
    assert r.status_code == 401


def test_admin_cron_runs_503_when_admin_key_disabled(client, monkeypatch):
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "admin_api_key", "", raising=False)
    r = client.get(
        "/v1/admin/cron_runs", headers={"X-API-Key": "anything"}
    )
    assert r.status_code == 503


def test_admin_cron_runs_happy_path(client, admin_enabled, cron_runs_seed):
    r = client.get(
        "/v1/admin/cron_runs",
        params={"since": "2030-04-28T00:00:00Z", "limit_per_cron": 10},
        headers={"X-API-Key": _ADMIN_KEY},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["since"] == "2030-04-28T00:00:00Z"
    assert body["limit_per_cron"] == 10
    assert body["note"] is None

    runs = body["runs"]
    # 2 saved-searches rows + 1 dispatch_webhooks row, all within the window.
    assert len(runs) == 3
    saved = [r for r in runs if r["cron_name"] == "run_saved_searches"]
    # ORDER BY cron_name ASC, started_at DESC: latest run_saved_searches first.
    assert [r["status"] for r in saved] == ["error", "ok"]

    counts = {c["cron_name"]: c for c in body["status_counts"]}
    assert counts["run_saved_searches"]["ok"] == 1
    assert counts["run_saved_searches"]["error"] == 1
    assert counts["run_saved_searches"]["last_status"] == "error"
    assert counts["dispatch_webhooks"]["ok"] == 1
    assert counts["dispatch_webhooks"]["error"] == 0


def test_admin_cron_runs_missing_table_graceful(client, admin_enabled):
    """Migration 102 not applied → return 200 with note + empty arrays."""
    from jpintel_mcp.config import settings

    db_path = settings.db_path
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS cron_runs")
        conn.commit()
    finally:
        conn.close()

    r = client.get(
        "/v1/admin/cron_runs",
        headers={"X-API-Key": _ADMIN_KEY},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["runs"] == []
    assert body["status_counts"] == []
    assert body["note"] and "missing" in body["note"].lower()


def test_admin_cron_runs_400_on_bad_since(client, admin_enabled):
    r = client.get(
        "/v1/admin/cron_runs",
        params={"since": "not-an-iso-date"},
        headers={"X-API-Key": _ADMIN_KEY},
    )
    assert r.status_code == 400
