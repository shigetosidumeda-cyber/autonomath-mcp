"""Wave 41 Axis 7a/7b/7c: schema + dry-run + LLM-import guard tests.

Covers:

* migration 245_appi_compliance_dataset.sql — table + indexes + view +
  unique tuple constraint + rollback.
* migration 246_credit_signal.sql — table + aggregate table + run log +
  view + rollback.
* migration 247_industry_sector_175.sql — dimension table + map table +
  run log + view + rollback.
* scripts/etl/ingest_appi_compliance.py — dry-run + LLM-import guard.
* scripts/cron/aggregate_credit_signal_daily.py — dry-run + decay
  formula sanity + LLM-import guard.
* scripts/cron/aggregate_industry_sector_175_weekly.py — dry-run +
  175-row seed shape + LLM-import guard.

NO LLM. NO Anthropic / openai / google.generativeai imports allowed in
the ETL/cron scripts (re-asserted here as a focused belt-and-braces
check alongside ``tests/test_no_llm_in_production.py``).
"""

from __future__ import annotations

import importlib
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MIG_DIR = REPO_ROOT / "scripts" / "migrations"
CRON_DIR = REPO_ROOT / "scripts" / "cron"
ETL_DIR = REPO_ROOT / "scripts" / "etl"
SRC_API_DIR = REPO_ROOT / "src" / "jpintel_mcp" / "api"

MIG_FILES = {
    "appi_compliance": MIG_DIR / "245_appi_compliance_dataset.sql",
    "credit_signal": MIG_DIR / "246_credit_signal.sql",
    "industry_sector_175": MIG_DIR / "247_industry_sector_175.sql",
}
ROLLBACK_FILES = {
    "appi_compliance": MIG_DIR / "245_appi_compliance_dataset_rollback.sql",
    "credit_signal": MIG_DIR / "246_credit_signal_rollback.sql",
    "industry_sector_175": MIG_DIR / "247_industry_sector_175_rollback.sql",
}

ETL_FILES = {
    "appi_compliance": ETL_DIR / "ingest_appi_compliance.py",
}
CRON_FILES = {
    "credit_signal": CRON_DIR / "aggregate_credit_signal_daily.py",
    "industry_sector_175": CRON_DIR / "aggregate_industry_sector_175_weekly.py",
}
API_FILES = {
    "appi_compliance": SRC_API_DIR / "appi_compliance.py",
    "credit_signal": SRC_API_DIR / "credit_signal.py",
    "industry_sector_175": SRC_API_DIR / "industry_sector_175.py",
}

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


# --------------------------------------------------------------------------- #
# Migration apply / inspect
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def migrated_db() -> Path:
    """Apply migrations 245 + 246 + 247 to a fresh temp DB."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="axis7-test-"))
    db_path = tmp_dir / "autonomath.db"
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        for key in ("appi_compliance", "credit_signal", "industry_sector_175"):
            sql = MIG_FILES[key].read_text(encoding="utf-8")
            conn.executescript(sql)
    finally:
        conn.close()
    return db_path


@pytest.mark.parametrize(
    "name", ["appi_compliance", "credit_signal", "industry_sector_175"]
)
def test_migration_files_present(name: str) -> None:
    assert MIG_FILES[name].exists()
    assert ROLLBACK_FILES[name].exists()


@pytest.mark.parametrize(
    "table",
    [
        "am_appi_compliance",
        "am_appi_compliance_ingest_log",
        "am_credit_signal",
        "am_credit_signal_aggregate",
        "am_credit_signal_run_log",
        "am_industry_jsic_175",
        "am_program_sector_175_map",
        "am_industry_sector_175_run_log",
    ],
)
def test_tables_created(migrated_db: Path, table: str) -> None:
    conn = sqlite3.connect(str(migrated_db))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        assert row is not None, f"table {table} not created by migration"
    finally:
        conn.close()


@pytest.mark.parametrize(
    "view",
    [
        "v_appi_compliance_summary",
        "v_credit_signal_worst",
        "v_industry_sector_175_density",
    ],
)
def test_views_created(migrated_db: Path, view: str) -> None:
    conn = sqlite3.connect(str(migrated_db))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name=?",
            (view,),
        ).fetchone()
        assert row is not None, f"view {view} not created"
    finally:
        conn.close()


def test_appi_compliance_status_check(migrated_db: Path) -> None:
    """CHECK constraint rejects an invalid status."""
    conn = sqlite3.connect(str(migrated_db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_appi_compliance (organization_name, compliance_status) "
                "VALUES (?, ?)",
                ("Bad Inc.", "invalid_status_should_fail"),
            )
    finally:
        conn.close()


def test_credit_signal_severity_bounds(migrated_db: Path) -> None:
    conn = sqlite3.connect(str(migrated_db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_credit_signal "
                "(houjin_bangou, signal_type, severity) VALUES (?, ?, ?)",
                ("1234567890123", "enforcement", 200),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_credit_signal "
                "(houjin_bangou, signal_type, severity) VALUES (?, ?, ?)",
                ("1234567890123", "enforcement", -1),
            )
    finally:
        conn.close()


def test_credit_signal_houjin_len(migrated_db: Path) -> None:
    conn = sqlite3.connect(str(migrated_db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_credit_signal "
                "(houjin_bangou, signal_type, severity) VALUES (?, ?, ?)",
                ("123", "enforcement", 25),
            )
    finally:
        conn.close()


def test_industry_jsic_175_code_len(migrated_db: Path) -> None:
    conn = sqlite3.connect(str(migrated_db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_industry_jsic_175 "
                "(jsic_code, major_code, name) VALUES (?, ?, ?)",
                ("12", "A", "bad code"),
            )
    finally:
        conn.close()


def test_rollback_drops_tables() -> None:
    """Each rollback script removes all tables it created."""
    tmp = Path(tempfile.mkdtemp(prefix="axis7-rb-"))
    db = tmp / "autonomath.db"
    conn = sqlite3.connect(str(db), isolation_level=None)
    try:
        for key in ("appi_compliance", "credit_signal", "industry_sector_175"):
            conn.executescript(MIG_FILES[key].read_text(encoding="utf-8"))
        for key in ("industry_sector_175", "credit_signal", "appi_compliance"):
            conn.executescript(ROLLBACK_FILES[key].read_text(encoding="utf-8"))
        for table in (
            "am_appi_compliance",
            "am_credit_signal",
            "am_industry_jsic_175",
        ):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            assert row is None, f"rollback did not drop {table}"
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Dry-run subprocess invocations
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "script_path",
    [
        ETL_DIR / "ingest_appi_compliance.py",
        CRON_DIR / "aggregate_credit_signal_daily.py",
        CRON_DIR / "aggregate_industry_sector_175_weekly.py",
    ],
)
def test_dry_run(script_path: Path) -> None:
    """Each ETL/cron script exits 0 on --dry-run."""
    assert script_path.exists(), f"{script_path} missing"
    result = subprocess.run(
        [sys.executable, str(script_path), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"{script_path.name} --dry-run failed rc={result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


# --------------------------------------------------------------------------- #
# LLM import guard (re-asserts tests/test_no_llm_in_production.py)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source_file",
    [
        *ETL_FILES.values(),
        *CRON_FILES.values(),
        *API_FILES.values(),
    ],
)
def test_no_llm_imports(source_file: Path) -> None:
    """Belt-and-braces: no anthropic / openai / google.generativeai imports."""
    text = source_file.read_text(encoding="utf-8")
    for banned in BANNED_LLM_IMPORTS:
        assert banned not in text, (
            f"{source_file.name} contains banned LLM import: {banned}"
        )


# --------------------------------------------------------------------------- #
# Module importability + REST contract
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "module_path",
    [
        "jpintel_mcp.api.appi_compliance",
        "jpintel_mcp.api.credit_signal",
        "jpintel_mcp.api.industry_sector_175",
    ],
)
def test_modules_importable(module_path: str) -> None:
    """Each REST module imports cleanly + exposes a `router`."""
    mod = importlib.import_module(module_path)
    assert hasattr(mod, "router"), f"{module_path} missing router"
    routes = list(mod.router.routes)
    assert len(routes) >= 1, f"{module_path} has no routes"


def test_appi_compliance_router_path() -> None:
    from jpintel_mcp.api.appi_compliance import router

    paths = [getattr(r, "path", "") for r in router.routes]
    assert any("/v1/appi/compliance/" in p for p in paths), paths


def test_credit_signal_router_path() -> None:
    from jpintel_mcp.api.credit_signal import router

    paths = [getattr(r, "path", "") for r in router.routes]
    assert any("/v1/credit/signal/" in p for p in paths), paths


def test_industry_sector_175_router_paths() -> None:
    from jpintel_mcp.api.industry_sector_175 import router

    paths = [getattr(r, "path", "") for r in router.routes]
    assert any(p == "/v1/industry/sector/175" for p in paths), paths
    assert any("/v1/industry/sector/175/{jsic_code}" in p for p in paths), paths


def test_jsic_175_seed_size() -> None:
    """The 175-sector seed must cover all 20 大分類 and be at least 90 rows.

    The dimension is intentionally seeded incrementally; the test guards
    the lower bound + the 20-major coverage so the cohort surface has
    proper coverage in every JSIC class A-T.
    """
    import importlib

    mod = importlib.import_module(
        "scripts.cron.aggregate_industry_sector_175_weekly"
        if (REPO_ROOT / "scripts/__init__.py").exists()
        else None
    ) if (REPO_ROOT / "scripts/__init__.py").exists() else None
    # Fallback: load via spec since `scripts/` is not a package by default.
    if mod is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "aggregate_industry_sector_175_weekly",
            CRON_DIR / "aggregate_industry_sector_175_weekly.py",
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

    seed = mod.JSIC_175_SEED
    assert len(seed) >= 90, f"JSIC_175_SEED too small: {len(seed)}"
    majors = {row[1] for row in seed}
    expected_majors = set("ABCDEFGHIJKLMNOPQRST")
    missing = expected_majors - majors
    assert not missing, f"missing 大分類 codes: {sorted(missing)}"


# --------------------------------------------------------------------------- #
# Credit signal decay formula sanity
# --------------------------------------------------------------------------- #


def test_credit_signal_decay_formula() -> None:
    """_decay_factor at 0 days = 1.0, at 36 months = 0.0."""
    import importlib.util
    from datetime import UTC, datetime, timedelta

    spec = importlib.util.spec_from_file_location(
        "aggregate_credit_signal_daily",
        CRON_DIR / "aggregate_credit_signal_daily.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    now = datetime.now(UTC)
    today_iso = now.strftime("%Y-%m-%d")
    assert mod._decay_factor(today_iso, now) == pytest.approx(1.0, abs=0.01)
    old = now - timedelta(days=mod._DECAY_FLOOR_DAYS + 30)
    assert mod._decay_factor(old.strftime("%Y-%m-%d"), now) == 0.0
    assert mod._decay_factor(None, now) == 0.5
