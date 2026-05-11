"""Wave 43.1.2 — JETRO / METI / JBIC / NEXI overseas ETL test suite.

Covers migration 249, the fill ETL dry-run, aggregator URL refusal, and
the LLM API import scan on the ETL surface. Schema-only tests; we do
NOT spin the FastAPI app here so the ¥3/req billing path is not
exercised in unit tests.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "scripts" / "migrations"
ETL_DIR = REPO_ROOT / "scripts" / "etl"
API_DIR = REPO_ROOT / "src" / "jpintel_mcp" / "api"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "overseas-subsidy-weekly.yml"

_BANNED_LLM_IMPORTS = (
    "import anthropic", "from anthropic",
    "import openai", "from openai ",
    "import google.generativeai", "from google.generativeai",
    "import claude_agent_sdk", "from claude_agent_sdk",
)


def test_migration_files_exist() -> None:
    forward = MIGRATIONS_DIR / "249_program_overseas_jetro.sql"
    rollback = MIGRATIONS_DIR / "249_program_overseas_jetro_rollback.sql"
    assert forward.exists(), forward
    assert rollback.exists(), rollback
    text = forward.read_text(encoding="utf-8")
    assert text.splitlines()[0].strip() == "-- target_db: autonomath"
    assert "am_program_overseas" in text
    assert "ck_overseas_country_len" in text
    assert "ck_overseas_program_type" in text


def test_migration_creates_table_and_view(tmp_path: Path) -> None:
    db = tmp_path / "auto.db"
    conn = sqlite3.connect(db)
    conn.executescript((MIGRATIONS_DIR / "249_program_overseas_jetro.sql").read_text(encoding="utf-8"))
    # Confirm idempotent re-run.
    conn.executescript((MIGRATIONS_DIR / "249_program_overseas_jetro.sql").read_text(encoding="utf-8"))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    views = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    assert "am_program_overseas" in tables
    assert "am_overseas_run_log" in tables
    assert "v_program_overseas_country_density" in views
    conn.close()


def test_migration_country_length_check(tmp_path: Path) -> None:
    db = tmp_path / "auto.db"
    conn = sqlite3.connect(db)
    conn.executescript((MIGRATIONS_DIR / "249_program_overseas_jetro.sql").read_text(encoding="utf-8"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO am_program_overseas(program_id, country_code, program_type, source_url) "
            "VALUES ('p1','USA','METI','https://www.meti.go.jp/x')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO am_program_overseas(program_id, country_code, program_type, source_url) "
            "VALUES ('p1','US','aggregator','https://www.meti.go.jp/x')"
        )
    conn.close()


def test_migration_rollback_drops_everything(tmp_path: Path) -> None:
    db = tmp_path / "auto.db"
    conn = sqlite3.connect(db)
    conn.executescript((MIGRATIONS_DIR / "249_program_overseas_jetro.sql").read_text(encoding="utf-8"))
    conn.executescript((MIGRATIONS_DIR / "249_program_overseas_jetro_rollback.sql").read_text(encoding="utf-8"))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "am_program_overseas" not in tables
    assert "am_overseas_run_log" not in tables
    conn.close()


def test_fill_script_dry_run_no_network(tmp_path: Path) -> None:
    db = tmp_path / "auto.db"
    conn = sqlite3.connect(db)
    conn.executescript((MIGRATIONS_DIR / "249_program_overseas_jetro.sql").read_text(encoding="utf-8"))
    conn.close()
    proc = subprocess.run(
        [
            sys.executable,
            str(ETL_DIR / "fill_programs_jetro_overseas_2x.py"),
            "--db",
            str(db),
            "--dry-run",
            "--no-network",
            "--max-rows",
            "50",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "rows_inserted" in proc.stdout


def test_fill_script_writes_rows_when_not_dry_run(tmp_path: Path) -> None:
    db = tmp_path / "auto.db"
    conn = sqlite3.connect(db)
    conn.executescript((MIGRATIONS_DIR / "249_program_overseas_jetro.sql").read_text(encoding="utf-8"))
    conn.close()
    proc = subprocess.run(
        [
            sys.executable,
            str(ETL_DIR / "fill_programs_jetro_overseas_2x.py"),
            "--db",
            str(db),
            "--no-network",
            "--max-rows",
            "60",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    conn = sqlite3.connect(db)
    (count,) = conn.execute("SELECT COUNT(*) FROM am_program_overseas").fetchone()
    assert count >= 30, count  # primary-domain rows survive the gate
    (log_count,) = conn.execute("SELECT COUNT(*) FROM am_overseas_run_log").fetchone()
    assert log_count == 1
    types = {r[0] for r in conn.execute("SELECT DISTINCT program_type FROM am_program_overseas")}
    assert types <= {
        "JETRO海外進出支援",
        "JETRO対日投資",
        "METI",
        "JBIC",
        "NEXI",
        "other",
    }
    conn.close()


def test_no_llm_imports_in_etl_or_router() -> None:
    targets = [
        ETL_DIR / "fill_programs_jetro_overseas_2x.py",
        API_DIR / "programs_overseas_v2.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for needle in _BANNED_LLM_IMPORTS:
            assert needle not in text, f"{path} contains banned import: {needle}"


def test_workflow_present_and_no_llm() -> None:
    assert WORKFLOW.exists()
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "overseas-subsidy-weekly" in text
    for needle in _BANNED_LLM_IMPORTS:
        assert needle not in text
