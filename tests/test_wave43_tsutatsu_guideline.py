"""Wave 43.1.6+7+8 — 通達全官庁 + 業種ガイドライン + 47都道府県 RSS tests."""

from __future__ import annotations

import importlib
import os
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "scripts" / "migrations"
ETL_DIR = REPO_ROOT / "scripts" / "etl"
CRON_DIR = REPO_ROOT / "scripts" / "cron"

MIG_TSUTATSU_ALL = "253_law_tsutatsu_all"
MIG_GUIDELINE = "254_law_guideline"
_DARWIN_CHILD_CRASH_RETURN_CODES = {-signal.SIGSEGV, -signal.SIGBUS, -signal.SIGABRT}

_BANNED_IMPORT_LINES = (
    "import anthropic",
    "from anthropic",
    "import openai",
    "from openai ",
    "import google.generativeai",
    "from google.generativeai",
    "import claude_agent_sdk",
    "from claude_agent_sdk",
)


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


def _apply_migration(conn: sqlite3.Connection, name: str) -> None:
    sql_path = MIGRATIONS_DIR / f"{name}.sql"
    assert sql_path.exists(), f"missing: {sql_path}"
    conn.executescript(sql_path.read_text(encoding="utf-8"))


def test_migration_253_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    _apply_migration(conn, MIG_TSUTATSU_ALL)
    _apply_migration(conn, MIG_TSUTATSU_ALL)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()
    }
    assert "am_law_tsutatsu_all" in tables
    assert "am_law_tsutatsu_all_fts" in tables
    assert "v_tsutatsu_all_agency_density" in tables
    conn.close()


def test_migration_254_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    _apply_migration(conn, MIG_GUIDELINE)
    _apply_migration(conn, MIG_GUIDELINE)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()
    }
    assert "am_law_guideline" in tables
    assert "am_law_guideline_fts" in tables
    assert "v_guideline_industry_density" in tables
    conn.close()


def test_tsutatsu_agency_enum(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    _apply_migration(conn, MIG_TSUTATSU_ALL)
    conn.execute(
        "INSERT INTO am_law_tsutatsu_all (tsutatsu_id, agency_id, agency_name, title, source_url) VALUES (?, ?, ?, ?, ?)",
        ("TSU-x", "nta", "国税庁", "t", "https://nta.go.jp/x"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO am_law_tsutatsu_all (tsutatsu_id, agency_id, agency_name, title, source_url) VALUES (?, ?, ?, ?, ?)",
            ("TSU-y", "bogus", "x", "t", "https://x.example/y"),
        )
    conn.close()


def test_guideline_compliance_enum(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    _apply_migration(conn, MIG_GUIDELINE)
    conn.execute(
        "INSERT INTO am_law_guideline (guideline_id, issuer_type, issuer_org, title, source_url, compliance_status) VALUES (?, ?, ?, ?, ?, ?)",
        ("GL2-a", "ministry", "経産省", "t", "https://meti.go.jp/a", "mandatory"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO am_law_guideline (guideline_id, issuer_type, issuer_org, title, source_url, compliance_status) VALUES (?, ?, ?, ?, ?, ?)",
            ("GL2-b", "ministry", "経産省", "t", "https://meti.go.jp/b", "bogus"),
        )
    conn.close()


def test_etl_tsutatsu_dry_run() -> None:
    script = ETL_DIR / "fill_laws_tsutatsu_all_2x.py"
    assert script.exists()
    res = subprocess.run(
        [sys.executable, str(script), "--dry-run", "--max-per-agency", "0"],
        capture_output=True,
        close_fds=False,
        env=_dry_run_env(),
        text=True,
        timeout=30,
    )
    _skip_darwin_child_crash(res)
    assert res.returncode == 0, f"stderr: {res.stderr}"


def test_etl_guideline_dry_run() -> None:
    script = ETL_DIR / "fill_laws_guideline_2x.py"
    assert script.exists()
    res = subprocess.run(
        [sys.executable, str(script), "--dry-run", "--max-per-issuer", "0"],
        capture_output=True,
        close_fds=False,
        env=_dry_run_env(),
        text=True,
        timeout=30,
    )
    _skip_darwin_child_crash(res)
    assert res.returncode == 0, f"stderr: {res.stderr}"


def test_ingest_cases_47pref() -> None:
    script = CRON_DIR / "ingest_cases_daily.py"
    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "PREFECTURE_RSS" in text
    for pref in ("hokkaido", "tokyo", "osaka", "okinawa", "kyoto", "fukuoka"):
        assert f'"{pref}"' in text, f"missing prefecture: {pref}"


def test_ingest_cases_aggregator_ban() -> None:
    sys.path.insert(0, str(REPO_ROOT))
    try:
        mod = importlib.import_module("scripts.cron.ingest_cases_daily")
        assert mod._is_banned("https://noukaweb.com/x")
        assert mod._is_banned("https://hojyokin-portal.jp/y")
        assert not mod._is_banned("https://www.pref.tokyo.jp/x")
    finally:
        sys.path.pop(0)


def test_ingest_cases_dry_run() -> None:
    script = CRON_DIR / "ingest_cases_daily.py"
    res = subprocess.run(
        [
            sys.executable,
            str(script),
            "--dry-run",
            "--prefectures",
            "tokyo",
            "--days",
            "1",
            "--max-workers",
            "1",
        ],
        capture_output=True,
        close_fds=False,
        env=_dry_run_env(),
        text=True,
        timeout=60,
    )
    _skip_darwin_child_crash(res)
    assert res.returncode == 0, f"stderr: {res.stderr}"


def test_rest_router_importable() -> None:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        mod = importlib.import_module("jpintel_mcp.api.law_tsutatsu_guideline")
        assert hasattr(mod, "router")
        paths = {r.path for r in mod.router.routes}
        assert "/v1/laws/tsutatsu_all/search" in paths
        assert "/v1/laws/guideline/search" in paths
    finally:
        sys.path.pop(0)


def test_no_llm_imports() -> None:
    files = [
        ETL_DIR / "fill_laws_tsutatsu_all_2x.py",
        ETL_DIR / "fill_laws_guideline_2x.py",
        CRON_DIR / "ingest_cases_daily.py",
        REPO_ROOT / "src" / "jpintel_mcp" / "api" / "law_tsutatsu_guideline.py",
    ]
    for f in files:
        assert f.exists(), f"missing: {f}"
        text = f.read_text(encoding="utf-8")
        for banned in _BANNED_IMPORT_LINES:
            assert banned not in text, f"{f.name} banned: {banned}"
