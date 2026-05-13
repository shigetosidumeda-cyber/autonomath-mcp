"""Wave 43.1.3: schema + dry-run + LLM-import guard tests for 民間助成財団 ETL.

Covers:

* migration 250_program_private_foundation.sql — table + indexes + view +
  unique tuple + rollback.
* scripts/etl/fill_programs_foundation_2x.py — dry-run + LLM-import guard.
* scripts/cron/refresh_foundation_weekly.py — LLM-import guard.
* src/jpintel_mcp/api/foundation.py — LLM-import guard.

NO LLM. NO Anthropic / openai / google.generativeai imports allowed
(re-asserted here as a focused belt-and-braces check alongside
``tests/test_no_llm_in_production.py``).
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIG_DIR = REPO_ROOT / "scripts" / "migrations"
ETL_FILE = REPO_ROOT / "scripts" / "etl" / "fill_programs_foundation_2x.py"
CRON_FILE = REPO_ROOT / "scripts" / "cron" / "refresh_foundation_weekly.py"
API_FILE = REPO_ROOT / "src" / "jpintel_mcp" / "api" / "foundation.py"

MIG_FILE = MIG_DIR / "250_program_private_foundation.sql"
ROLLBACK_FILE = MIG_DIR / "250_program_private_foundation_rollback.sql"

BANNED_LLM_IMPORTS = (
    "import anthropic",
    "from anthropic",
    "import openai",
    "from openai",
    "import google.generativeai",
    "from google.generativeai",
    "import claude_agent_sdk",
    "from claude_agent_sdk",
)


def test_migration_files_present() -> None:
    assert MIG_FILE.exists(), MIG_FILE
    assert ROLLBACK_FILE.exists(), ROLLBACK_FILE


def test_migration_first_line_target_db() -> None:
    """entrypoint.sh §4 picks up only files whose first line is target_db marker."""
    first_line = MIG_FILE.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.strip() == "-- target_db: autonomath", first_line


def test_migration_apply_and_rollback_idempotent() -> None:
    """Apply + rollback + re-apply on a temp DB; everything must be idempotent."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="wave43-1-3-test-"))
    db_path = tmp_dir / "autonomath.db"
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        # Forward
        conn.executescript(MIG_FILE.read_text(encoding="utf-8"))
        # Tables present?
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "am_program_private_foundation" in names
        assert "am_program_private_foundation_ingest_log" in names
        # View present?
        views = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()
        }
        assert "v_program_private_foundation_summary" in views
        # CHECK constraint: enum guards.
        try:
            conn.execute(
                "INSERT INTO am_program_private_foundation "
                "(foundation_name, foundation_type) VALUES (?, ?)",
                ("bad type test", "INVALID_TYPE"),
            )
            raise AssertionError("CHECK constraint should have rejected invalid type")
        except sqlite3.IntegrityError:
            pass
        # Happy-path insert.
        conn.execute(
            "INSERT INTO am_program_private_foundation "
            "(foundation_name, foundation_type, grant_program_name, "
            " donation_category) VALUES (?, ?, ?, ?)",
            ("テスト財団", "公益財団", "テスト助成", "public_interest"),
        )
        count = conn.execute("SELECT COUNT(*) FROM am_program_private_foundation").fetchone()[0]
        assert count == 1
        # Re-apply (idempotent — should not raise).
        conn.executescript(MIG_FILE.read_text(encoding="utf-8"))
        # Rollback
        conn.executescript(ROLLBACK_FILE.read_text(encoding="utf-8"))
        names_after = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "am_program_private_foundation" not in names_after
        # Re-apply after rollback (forward must remain idempotent).
        conn.executescript(MIG_FILE.read_text(encoding="utf-8"))
    finally:
        conn.close()


def test_etl_dry_run_works() -> None:
    """Dry-run path must exit 0 without touching the DB."""
    assert ETL_FILE.exists()
    r = subprocess.run(
        [sys.executable, str(ETL_FILE), "--dry-run", "--source", "koeki_info"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


def test_etl_no_llm_imports() -> None:
    body = ETL_FILE.read_text(encoding="utf-8")
    for banned in BANNED_LLM_IMPORTS:
        assert banned not in body, banned


def test_cron_no_llm_imports() -> None:
    body = CRON_FILE.read_text(encoding="utf-8")
    for banned in BANNED_LLM_IMPORTS:
        assert banned not in body, banned


def test_api_no_llm_imports() -> None:
    body = API_FILE.read_text(encoding="utf-8")
    for banned in BANNED_LLM_IMPORTS:
        assert banned not in body, banned


def test_api_router_has_disclaimer_const() -> None:
    """Sensitive surface MUST stamp _disclaimer on every 2xx response."""
    body = API_FILE.read_text(encoding="utf-8")
    assert "_FOUNDATION_DISCLAIMER" in body
    assert "税理士法" in body  # mandatory士業 fence
    assert "_disclaimer" in body


def test_api_readonly_connection_sets_query_only(tmp_path: Path, monkeypatch) -> None:
    """Foundation autonomath handle must be read-only and query-only."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE am_program_private_foundation (foundation_id INTEGER)")
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))

    from jpintel_mcp.api import foundation

    ro = foundation._open_am_ro()
    assert ro is not None
    try:
        assert ro.execute("PRAGMA query_only").fetchone()[0] == 1
        try:
            ro.execute("CREATE TABLE should_not_write (id INTEGER)")
            raise AssertionError("query_only connection should reject writes")
        except sqlite3.DatabaseError as exc:
            assert "readonly" in str(exc).lower() or "query only" in str(exc).lower()
    finally:
        ro.close()


def test_api_summary_query_is_bounded() -> None:
    body = API_FILE.read_text(encoding="utf-8")
    assert "_FOUNDATION_SUMMARY_LIMIT" in body
    assert "_FOUNDATION_MAX_OFFSET" in body
    assert "LIMIT ?" in body
    assert "Query(ge=0, le=_FOUNDATION_MAX_OFFSET)" in body
    assert "FROM v_program_private_foundation_summary" not in body
    assert '"scope": "current_page"' in body


def test_api_bounded_summary_uses_current_page_only() -> None:
    from jpintel_mcp.api.foundation import _bounded_summary

    rows = [
        {
            "foundation_type": "公益財団",
            "donation_category": "research",
            "foundation_name": "A財団",
        },
        {
            "foundation_type": "公益財団",
            "donation_category": "research",
            "foundation_name": "A財団",
        },
        {
            "foundation_type": "NPO",
            "donation_category": "community",
            "foundation_name": "B法人",
        },
    ]

    summary = _bounded_summary(rows, "公益財団", "研究")

    assert summary["scope"] == "current_page"
    assert summary["filtered_by"] == {"foundation_type": "公益財団", "grant_theme": "研究"}
    assert summary["by_type"][0] == {
        "foundation_type": "公益財団",
        "donation_category": "research",
        "program_count": 2,
        "foundation_count": 1,
    }


def test_etl_banned_hosts_present() -> None:
    """Aggregator ban list must include hojyokin-portal + noukaweb at minimum."""
    body = ETL_FILE.read_text(encoding="utf-8")
    assert "hojyokin-portal.com" in body
    assert "noukaweb.com" in body


def test_etl_curated_foundations_have_primary_urls() -> None:
    """Every curated 公益財団 URL MUST be on a primary domain (not aggregator)."""
    body = ETL_FILE.read_text(encoding="utf-8")
    # Aggregator hosts must NOT appear in the curated list URLs.
    assert "hojyokin-portal.com/foundations" not in body
    assert "助成財団検索サイト/" not in body
