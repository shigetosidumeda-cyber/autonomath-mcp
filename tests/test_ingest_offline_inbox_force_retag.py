"""Tests for `--force-retag` re-tag path (W2-13 caveat #3) and the
migration 113b early-exit gate (W2-13 caveat #4).
"""

from __future__ import annotations

import importlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
CRON_SCRIPT = REPO_ROOT / "scripts" / "cron" / "ingest_offline_inbox.py"


def _make_autonomath_with_113b(db_path: Path, *, jsic_major: str | None) -> None:
    """Create a fake autonomath.db with jpi_programs + 1 seed row.

    `jsic_major=None` simulates the un-tagged path; an existing string
    value simulates the re-tag path the --force-retag flag is supposed
    to overwrite.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE jpi_programs ("
        " unified_id TEXT PRIMARY KEY,"
        " name TEXT,"
        " jsic_major TEXT,"
        " jsic_middle TEXT,"
        " jsic_minor TEXT,"
        " jsic_assigned_at TEXT,"
        " jsic_assigned_method TEXT"
        ")"
    )
    conn.execute(
        "INSERT INTO jpi_programs(unified_id, name, jsic_major, "
        "jsic_assigned_method) VALUES (?, ?, ?, ?)",
        ("u-rt-1", "TestProg", jsic_major, "manual" if jsic_major else None),
    )
    conn.commit()
    conn.close()


def _write_inbox(tmp_path: Path, *, unified_id: str, jsic_major: str) -> Path:
    """Write a 1-row jsonl into a synthetic inbox under tmp_path."""
    inbox = tmp_path / "_inbox" / "jsic_tags"
    inbox.mkdir(parents=True, exist_ok=True)
    f = inbox / "test.jsonl"
    payload = {
        "program_unified_id": unified_id,
        "jsic_major": jsic_major,
        "jsic_middle": "13",
        "jsic_minor": "131",
        "jsic_assigned_method": "classifier",
        "subagent_run_id": "test-1",
        "assigned_at": "2026-05-04T00:00:00Z",
        "confidence": "high",
    }
    f.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return f


@pytest.fixture
def cron_module(monkeypatch, tmp_path):
    """Import the cron module fresh and rebase its INBOX_ROOT to tmp."""
    sys_path_extra = str(REPO_ROOT / "scripts" / "cron")
    if sys_path_extra not in sys.path:
        sys.path.insert(0, sys_path_extra)
    mod_name = "ingest_offline_inbox"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    mod = importlib.import_module(mod_name)
    monkeypatch.setattr(mod, "INBOX_ROOT", tmp_path / "_inbox")
    monkeypatch.setattr(mod, "QUARANTINE_ROOT", tmp_path / "_quarantine")
    yield mod


def test_default_keeps_existing_value_idempotent(cron_module, tmp_path):
    db = tmp_path / "auto.db"
    _make_autonomath_with_113b(db, jsic_major="M")  # already tagged
    _write_inbox(tmp_path, unified_id="u-rt-1", jsic_major="A")

    cron_module.FORCE_RETAG = False
    conn = sqlite3.connect(db)
    try:
        cron_module.assert_migration_113b(conn)  # 113b present → no raise
        # Direct handler call mirrors what process_file does on each row.
        applied = cron_module.insert_jsic_classification(
            conn,
            {
                "program_unified_id": "u-rt-1",
                "jsic_major": "A",
                "jsic_middle": "13",
                "jsic_minor": "131",
                "assigned_at": "2026-05-04T00:00:00Z",
                "jsic_assigned_method": "classifier",
            },
        )
        conn.commit()
        # NULL guard fires → no row updated, idempotent silent no-op.
        assert applied == 0
        row = conn.execute(
            "SELECT jsic_major, jsic_assigned_method FROM jpi_programs WHERE unified_id=?",
            ("u-rt-1",),
        ).fetchone()
        assert row == ("M", "manual")
    finally:
        conn.close()


def test_force_retag_overwrites_existing_value(cron_module, tmp_path):
    db = tmp_path / "auto.db"
    _make_autonomath_with_113b(db, jsic_major="M")  # already tagged
    _write_inbox(tmp_path, unified_id="u-rt-1", jsic_major="A")

    cron_module.FORCE_RETAG = True
    conn = sqlite3.connect(db)
    try:
        applied = cron_module.insert_jsic_classification(
            conn,
            {
                "program_unified_id": "u-rt-1",
                "jsic_major": "A",
                "jsic_middle": "13",
                "jsic_minor": "131",
                "assigned_at": "2026-05-04T00:00:00Z",
                "jsic_assigned_method": "classifier",
            },
        )
        conn.commit()
        assert applied == 1
        row = conn.execute(
            "SELECT jsic_major, jsic_middle, jsic_minor, jsic_assigned_method "
            "FROM jpi_programs WHERE unified_id=?",
            ("u-rt-1",),
        ).fetchone()
        assert row == ("A", "13", "131", "classifier")
    finally:
        cron_module.FORCE_RETAG = False
        conn.close()


def test_force_retag_still_tags_null_rows(cron_module, tmp_path):
    db = tmp_path / "auto.db"
    _make_autonomath_with_113b(db, jsic_major=None)  # un-tagged
    cron_module.FORCE_RETAG = True
    conn = sqlite3.connect(db)
    try:
        applied = cron_module.insert_jsic_classification(
            conn,
            {
                "program_unified_id": "u-rt-1",
                "jsic_major": "B",
                "assigned_at": "2026-05-04T00:00:00Z",
                "jsic_assigned_method": "classifier",
            },
        )
        conn.commit()
        assert applied == 1
        row = conn.execute(
            "SELECT jsic_major FROM jpi_programs WHERE unified_id=?",
            ("u-rt-1",),
        ).fetchone()
        assert row == ("B",)
    finally:
        cron_module.FORCE_RETAG = False
        conn.close()


def test_migration_113b_gate_raises_when_column_missing(cron_module, tmp_path):
    db = tmp_path / "no_113b.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE jpi_programs (unified_id TEXT PRIMARY KEY, name TEXT)")
    conn.commit()
    conn.close()

    conn = sqlite3.connect(db)
    try:
        with pytest.raises(RuntimeError, match="migration 113b not applied"):
            cron_module.assert_migration_113b(conn)
    finally:
        conn.close()


def test_migration_113b_gate_passes_when_column_present(cron_module, tmp_path):
    db = tmp_path / "with_113b.db"
    _make_autonomath_with_113b(db, jsic_major=None)
    conn = sqlite3.connect(db)
    try:
        cron_module.assert_migration_113b(conn)  # no raise
    finally:
        conn.close()


def test_cli_early_exits_on_missing_113b(tmp_path):
    """End-to-end: invoke the script as a subprocess and confirm
    RuntimeError early-exit with non-zero exit code.
    """
    db = tmp_path / "bare.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE jpi_programs (unified_id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    inbox = tmp_path / "_inbox" / "jsic_tags"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "x.jsonl").write_text(
        json.dumps(
            {
                "program_unified_id": "u-1",
                "jsic_major": "A",
                "subagent_run_id": "t",
                "assigned_at": "2026-05-04T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Need to monkeypatch INBOX_ROOT to point at our tmp inbox.
    # Easiest path: invoke via -c with a pre-patched module.
    code = (
        "import sys; sys.path.insert(0, %r); "
        "import importlib, ingest_offline_inbox as m; "
        "from pathlib import Path; "
        "m.INBOX_ROOT = Path(%r); "
        "m.QUARANTINE_ROOT = Path(%r); "
        "sys.argv = ['x', '--tool', 'jsic_tags', "
        "'--autonomath-db', %r, '--jpintel-db', %r]; "
        "raise SystemExit(m.main())"
    ) % (
        str(REPO_ROOT / "scripts" / "cron"),
        str(tmp_path / "_inbox"),
        str(tmp_path / "_quarantine"),
        str(db),
        str(tmp_path / "fake_jpintel.db"),
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode != 0
    assert "migration 113b not applied" in (r.stderr + r.stdout)
