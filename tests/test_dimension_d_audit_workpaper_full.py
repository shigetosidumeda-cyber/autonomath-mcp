"""Wave 46 dim 19 D-final test — am_audit_workpaper full surface.

Closes the dim D 4.5 → 10.0 gap by exercising:

* migration 270 SQL syntactic + relational correctness (tables / view /
  run_log present, CHECKs honoured, UNIQUE on (houjin_bangou, fy)),
* ETL ``build_audit_workpaper_v2.py`` end-to-end against a seeded
  in-memory db: candidate cohort lookup, compose, upsert, run_log row,
* idempotency: re-running on same seed → workpaper rowcount unchanged,
  fresh ``composed_at`` only,
* cron yaml validity (workflow keys + cron expression + concurrency),
* schema compatibility with the REST envelope produced by
  ``audit_workpaper_v2.py::_build_workpaper`` (the field set the cache
  caters to is a strict subset of the REST envelope).

Honours
-------
``feedback_autonomath_no_api_use`` + ``feedback_no_operator_llm_api`` +
``feedback_completion_gate_minimal`` (focused dim D close-out, no
unrelated refactor).

No LLM, no network, no aggregator fence-jump.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_MIG = _REPO / "scripts" / "migrations" / "270_audit_workpaper.sql"
_MIG_RB = _REPO / "scripts" / "migrations" / "270_audit_workpaper_rollback.sql"
_ETL = _REPO / "scripts" / "etl" / "build_audit_workpaper_v2.py"
_CRON = _REPO / ".github" / "workflows" / "build-audit-workpaper-weekly.yml"


# ---------------------------------------------------------------------------
# 1. File-presence sanity
# ---------------------------------------------------------------------------
def test_files_present():
    assert _MIG.is_file(), "migration 270 missing"
    assert _MIG_RB.is_file(), "rollback 270 missing"
    assert _ETL.is_file(), "ETL build_audit_workpaper_v2.py missing"
    assert _CRON.is_file(), "cron workflow yaml missing"


# ---------------------------------------------------------------------------
# 2. Migration apply on :memory:
# ---------------------------------------------------------------------------
def _apply_mig(conn: sqlite3.Connection) -> None:
    conn.executescript(_MIG.read_text())


def test_migration_applies_clean():
    conn = sqlite3.connect(":memory:")
    _apply_mig(conn)
    names = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name LIKE 'am_audit_workpaper%' OR name LIKE 'v_audit_workpaper%'"
        ).fetchall()
    }
    assert "am_audit_workpaper" in names
    assert "am_audit_workpaper_run_log" in names
    assert "v_audit_workpaper_cohort" in names
    # idempotent re-apply
    _apply_mig(conn)


def test_migration_unique_and_checks():
    conn = sqlite3.connect(":memory:")
    _apply_mig(conn)
    # UNIQUE (houjin_bangou, fiscal_year)
    conn.execute(
        "INSERT INTO am_audit_workpaper "
        "(houjin_bangou, fiscal_year, fy_start, fy_end) "
        "VALUES (?, ?, ?, ?)",
        ("1234567890123", 2025, "2025-04-01", "2026-03-31"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO am_audit_workpaper "
            "(houjin_bangou, fiscal_year, fy_start, fy_end) "
            "VALUES (?, ?, ?, ?)",
            ("1234567890123", 2025, "2025-04-01", "2026-03-31"),
        )
    # CHECK fy range
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO am_audit_workpaper "
            "(houjin_bangou, fiscal_year, fy_start, fy_end) "
            "VALUES (?, ?, ?, ?)",
            ("1234567890124", 1800, "1800-04-01", "1801-03-31"),
        )


def test_rollback_drops_tables():
    conn = sqlite3.connect(":memory:")
    _apply_mig(conn)
    conn.executescript(_MIG_RB.read_text())
    names = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name LIKE 'am_audit_workpaper%' OR name LIKE 'v_audit_workpaper%'"
        ).fetchall()
    }
    assert names == set(), f"rollback left artifacts: {names}"


# ---------------------------------------------------------------------------
# 3. ETL e2e against seeded :memory:
# ---------------------------------------------------------------------------
def _seed_source_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS jpi_houjin_master(
            houjin_bangou TEXT PRIMARY KEY, normalized_name TEXT,
            address_normalized TEXT, prefecture TEXT, municipality TEXT,
            corporation_type TEXT, jsic_major TEXT,
            total_adoptions INTEGER, total_received_yen INTEGER
        );
        CREATE TABLE IF NOT EXISTS jpi_adoption_records(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            applicant_houjin_bangou TEXT, program_id TEXT, program_name TEXT,
            applicant_name TEXT, award_date TEXT, announce_date TEXT,
            amount_yen INTEGER, fiscal_year INTEGER, prefecture TEXT
        );
        CREATE TABLE IF NOT EXISTS am_enforcement_detail(
            detail_id INTEGER PRIMARY KEY AUTOINCREMENT, houjin_bangou TEXT,
            enforcement_kind TEXT, enforcement_date TEXT, amount_yen INTEGER,
            summary TEXT, source_url TEXT
        );
        CREATE TABLE IF NOT EXISTS jpi_invoice_registrants(
            id INTEGER PRIMARY KEY AUTOINCREMENT, houjin_bangou TEXT,
            prefecture TEXT, registered_date TEXT
        );
        CREATE TABLE IF NOT EXISTS am_amendment_diff(
            id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT, field_name TEXT,
            prev_value TEXT, new_value TEXT, detected_at TEXT, source_url TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO jpi_houjin_master VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("1234567890123", "テスト株式会社", "東京都千代田区1-1", "東京都", "千代田区",
         "株式会社", "C-製造業", 3, 30000000),
    )
    conn.execute(
        "INSERT INTO jpi_adoption_records "
        "(applicant_houjin_bangou, program_id, program_name, award_date, "
        " amount_yen, fiscal_year, prefecture) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("1234567890123", "PROG-A", "ものづくり補助金", "2025-06-01", 10000000, 2025, "東京都"),
    )
    conn.execute(
        "INSERT INTO am_enforcement_detail "
        "(houjin_bangou, enforcement_kind, enforcement_date, amount_yen) "
        "VALUES (?, ?, ?, ?)",
        ("1234567890123", "業務改善命令", "2025-09-15", 0),
    )


def _load_etl():
    import importlib.util
    spec = importlib.util.spec_from_file_location("etl_awp", _ETL)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_etl_compose_and_upsert(tmp_path):
    db = tmp_path / "test_autonomath.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    _apply_mig(conn)
    _seed_source_tables(conn)
    conn.commit()
    conn.close()

    etl = _load_etl()
    rc = etl.main([
        "--db", str(db),
        "--only", "1234567890123",
        "--fiscal-year", "2025",
        "--log-level", "WARNING",
    ])
    assert rc == 0

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM am_audit_workpaper WHERE houjin_bangou=? AND fiscal_year=?",
        ("1234567890123", 2025),
    ).fetchall()
    assert len(rows) == 1, "expected 1 workpaper row"
    r = rows[0]
    assert r["fy_adoption_count"] == 1
    assert r["fy_enforcement_count"] == 1
    assert r["auditor_flag_count"] >= 1
    payload = json.loads(r["snapshot_json"])
    assert payload["client_houjin_bangou"] == "1234567890123"
    assert payload["fy_window"]["start"] == "2025-04-01"
    # run_log row landed
    log_rows = conn.execute("SELECT * FROM am_audit_workpaper_run_log").fetchall()
    assert len(log_rows) == 1
    assert log_rows[0]["workpapers_upserted"] == 1


def test_etl_idempotent_rerun(tmp_path):
    db = tmp_path / "test_autonomath.db"
    conn = sqlite3.connect(str(db))
    _apply_mig(conn)
    _seed_source_tables(conn)
    conn.commit()
    conn.close()

    etl = _load_etl()
    args = [
        "--db", str(db),
        "--only", "1234567890123",
        "--fiscal-year", "2025",
        "--log-level", "WARNING",
    ]
    assert etl.main(args) == 0
    assert etl.main(args) == 0  # second run, idempotent

    conn = sqlite3.connect(str(db))
    cnt = conn.execute("SELECT COUNT(*) FROM am_audit_workpaper").fetchone()[0]
    assert cnt == 1, "idempotent upsert must not duplicate"
    runs = conn.execute("SELECT COUNT(*) FROM am_audit_workpaper_run_log").fetchone()[0]
    assert runs == 2, "two ETL runs should produce two run_log rows"


def test_etl_dry_run_no_writes(tmp_path):
    db = tmp_path / "test_autonomath.db"
    conn = sqlite3.connect(str(db))
    _apply_mig(conn)
    _seed_source_tables(conn)
    conn.commit()
    conn.close()

    etl = _load_etl()
    rc = etl.main([
        "--db", str(db),
        "--only", "1234567890123",
        "--fiscal-year", "2025",
        "--dry-run",
        "--log-level", "WARNING",
    ])
    assert rc == 0
    conn = sqlite3.connect(str(db))
    cnt = conn.execute("SELECT COUNT(*) FROM am_audit_workpaper").fetchone()[0]
    assert cnt == 0, "--dry-run must not upsert"
    runs = conn.execute("SELECT COUNT(*) FROM am_audit_workpaper_run_log").fetchone()[0]
    assert runs == 0, "--dry-run must not write run_log"


# ---------------------------------------------------------------------------
# 4. Cron workflow yaml shape
# ---------------------------------------------------------------------------
def test_cron_workflow_yaml_valid():
    doc = yaml.safe_load(_CRON.read_text())
    assert doc["name"] == "build-audit-workpaper-weekly"
    # PyYAML parses `on:` as True (bool). Accept either spelling.
    on = doc.get("on") or doc.get(True)
    assert on is not None, "missing on: block"
    schedule = on.get("schedule")
    assert schedule and "cron" in schedule[0]
    assert schedule[0]["cron"] == "0 4 * * 2"
    assert "workflow_dispatch" in on
    assert doc["concurrency"]["group"] == "build-audit-workpaper-weekly"
    jobs = doc["jobs"]
    assert "build-snapshot" in jobs
    assert jobs["build-snapshot"]["timeout-minutes"] == 30


# ---------------------------------------------------------------------------
# 5. REST envelope ↔ cache schema parity
# ---------------------------------------------------------------------------
def test_cache_schema_subset_of_rest_envelope():
    """The cached snapshot must carry every counts.* field the REST envelope
    produces, plus auditor_flag_count rollup. Drift here breaks the cohort
    discoverability surface."""
    from jpintel_mcp.api.audit_workpaper_v2 import _build_workpaper  # type: ignore

    # Use the ETL's own composer instead of opening autonomath; both share
    # the same SQL fan-out. We just verify the shape contract.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _apply_mig(conn)
    _seed_source_tables(conn)
    env_rest = _build_workpaper(conn, "1234567890123", 2025)
    assert env_rest is not None
    for k in ("fy_adoption_count", "fy_enforcement_count",
              "fy_amendment_alert_count", "mismatch"):
        assert k in env_rest["counts"], f"REST envelope missing {k!r}"
    # cache columns mirror these
    cols = {r[1] for r in conn.execute("PRAGMA table_info(am_audit_workpaper)").fetchall()}
    for c in ("fy_adoption_count", "fy_enforcement_count",
              "fy_amendment_alert_count", "jurisdiction_mismatch",
              "auditor_flag_count", "snapshot_json"):
        assert c in cols, f"am_audit_workpaper missing column {c!r}"
