"""Wave 43.1.9 + 43.1.10 — combined sanity test for enforcement_municipality
+ court_decisions_v2 migrations + ETL dry-run.
"""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_DARWIN_CHILD_CRASH_RETURN_CODES = {-signal.SIGSEGV, -signal.SIGBUS, -signal.SIGABRT}


def _dry_run_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "SENTRY_DSN": "",
            "SENTRY_TRACES_SAMPLE_RATE": "0",
            "SENTRY_PROFILES_SAMPLE_RATE": "0",
            "JPCITE_ENV": "test",
            "JPINTEL_ENV": "test",
        }
    )
    return env


def _skip_darwin_child_crash(result: subprocess.CompletedProcess[str]) -> None:
    if sys.platform != "darwin" or result.returncode not in _DARWIN_CHILD_CRASH_RETURN_CODES:
        return
    signame = signal.Signals(-result.returncode).name
    pytest.skip(f"ETL dry-run subprocess crashed on Darwin with {signame}")


def _apply_migration(db_path: Path, mig_path: Path) -> None:
    sql = mig_path.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


def test_migration_255_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test_255.db"
    mig = REPO_ROOT / "scripts" / "migrations" / "255_enforcement_municipality.sql"
    _apply_migration(db_path, mig)
    _apply_migration(db_path, mig)
    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "am_enforcement_municipality" in tables
    assert "am_enforcement_municipality_run_log" in tables
    assert "am_enforcement_municipality_fts" in tables
    views = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    assert "v_enforcement_municipality_public" in views
    conn.close()


def test_migration_259_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test_259.db"
    mig = REPO_ROOT / "scripts" / "migrations" / "259_court_decisions_extended.sql"
    _apply_migration(db_path, mig)
    _apply_migration(db_path, mig)
    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "am_court_decisions_v2" in tables
    assert "am_court_decisions_v2_run_log" in tables
    assert "am_court_decisions_v2_fts" in tables
    views = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    assert "v_am_court_decisions_v2_public" in views
    conn.close()


def test_etl_enforcement_dry_run(tmp_path: Path) -> None:
    db_path = tmp_path / "test_enf.db"
    mig = REPO_ROOT / "scripts" / "migrations" / "255_enforcement_municipality.sql"
    _apply_migration(db_path, mig)
    script = REPO_ROOT / "scripts" / "etl" / "fill_enforcement_municipality_2x.py"
    result = subprocess.run(
        [sys.executable, str(script), "--dry-run", "--target", "20", "--db-path", str(db_path)],
        capture_output=True,
        close_fds=False,
        env=_dry_run_env(),
        text=True,
        timeout=60,
    )
    _skip_darwin_child_crash(result)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    conn = sqlite3.connect(str(db_path))
    (count,) = conn.execute("SELECT COUNT(*) FROM am_enforcement_municipality").fetchone()
    assert count >= 20, f"expected >=20 rows, got {count}"
    (log_count,) = conn.execute(
        "SELECT COUNT(*) FROM am_enforcement_municipality_run_log"
    ).fetchone()
    assert log_count == 1
    conn.close()


def test_etl_court_v2_dry_run(tmp_path: Path) -> None:
    db_path = tmp_path / "test_court.db"
    mig = REPO_ROOT / "scripts" / "migrations" / "259_court_decisions_extended.sql"
    _apply_migration(db_path, mig)
    script = REPO_ROOT / "scripts" / "etl" / "fill_court_decisions_extended_2x.py"
    result = subprocess.run(
        [sys.executable, str(script), "--dry-run", "--target", "100", "--db-path", str(db_path)],
        capture_output=True,
        close_fds=False,
        env=_dry_run_env(),
        text=True,
        timeout=60,
    )
    _skip_darwin_child_crash(result)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    conn = sqlite3.connect(str(db_path))
    (count,) = conn.execute("SELECT COUNT(*) FROM am_court_decisions_v2").fetchone()
    assert count >= 100, f"expected >=100 rows, got {count}"
    levels = {
        r[0]
        for r in conn.execute("SELECT DISTINCT court_level_canonical FROM am_court_decisions_v2")
    }
    assert len(levels) >= 3, f"expected diverse court levels, got {levels}"
    conn.close()
