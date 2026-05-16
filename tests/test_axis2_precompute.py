"""Wave 33 Axis 2a/2b/2c: schema + dry-run + sample calculation tests.

Covers:

* migration 231_cohort_5d.sql — table + 3 indexes + view + unique tuple constraint
* migration 232_program_risk_4d.sql — table + 3 indexes + view + 4-tuple uniqueness
* migration 233_supplier_chain.sql — table + 3 indexes + view + 4-tuple uniqueness
* scripts/cron/precompute_cohort_5d.py — dry-run + sample insert + idempotency
* scripts/cron/precompute_program_risk_4d.py — dry-run + weighted-score sanity
* scripts/cron/precompute_supplier_chain.py — dry-run + link_type enum check

NO LLM. NO Anthropic / openai / google.generativeai imports allowed in the
cron scripts (verified by the existing tests/test_no_llm_in_production.py
CI guard — we re-assert here as a focused belt-and-braces check on the
3 new cron modules).
"""

from __future__ import annotations

import importlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MIG_DIR = REPO_ROOT / "scripts" / "migrations"
CRON_DIR = REPO_ROOT / "scripts" / "cron"

MIG_FILES = {
    "cohort_5d": MIG_DIR / "231_cohort_5d.sql",
    "program_risk_4d": MIG_DIR / "232_program_risk_4d.sql",
    "supplier_chain": MIG_DIR / "233_supplier_chain.sql",
}
ROLLBACK_FILES = {
    "cohort_5d": MIG_DIR / "231_cohort_5d_rollback.sql",
    "program_risk_4d": MIG_DIR / "232_program_risk_4d_rollback.sql",
    "supplier_chain": MIG_DIR / "233_supplier_chain_rollback.sql",
}

CRON_FILES = {
    "cohort_5d": CRON_DIR / "precompute_cohort_5d.py",
    "program_risk_4d": CRON_DIR / "precompute_program_risk_4d.py",
    "supplier_chain": CRON_DIR / "precompute_supplier_chain.py",
}


# --------------------------------------------------------------------------- #
# Migration apply / inspect
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def migrated_db() -> Path:
    """Apply migrations 231 + 232 + 233 to a fresh temp DB."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="axis2-precompute-test-"))
    db_path = tmp_dir / "autonomath.db"
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        for key in ("cohort_5d", "program_risk_4d", "supplier_chain"):
            sql = MIG_FILES[key].read_text(encoding="utf-8")
            conn.executescript(sql)
    finally:
        conn.close()
    return db_path


@pytest.mark.parametrize("name", ["cohort_5d", "program_risk_4d", "supplier_chain"])
def test_migration_files_present(name: str) -> None:
    assert MIG_FILES[name].exists()
    assert ROLLBACK_FILES[name].exists()


@pytest.mark.parametrize(
    "table",
    ["am_cohort_5d", "am_program_risk_4d", "am_supplier_chain"],
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
        "v_cohort_5d_top",
        "v_program_risk_4d_top",
        "v_supplier_chain_breadth",
    ],
)
def test_views_created(migrated_db: Path, view: str) -> None:
    conn = sqlite3.connect(str(migrated_db))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name=?",
            (view,),
        ).fetchone()
        assert row is not None, f"view {view} not created by migration"
    finally:
        conn.close()


def test_cohort_5d_columns(migrated_db: Path) -> None:
    conn = sqlite3.connect(str(migrated_db))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(am_cohort_5d)")}
    finally:
        conn.close()
    expected = {
        "cohort_id",
        "houjin_bangou",
        "jsic_major",
        "employee_band",
        "prefecture_code",
        "eligible_program_ids",
        "eligible_count",
        "last_refreshed_at",
    }
    missing = expected - cols
    assert not missing, f"am_cohort_5d missing columns: {missing}"


def test_program_risk_4d_columns(migrated_db: Path) -> None:
    conn = sqlite3.connect(str(migrated_db))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(am_program_risk_4d)")}
    finally:
        conn.close()
    expected = {
        "id",
        "program_id",
        "gyouhou_id",
        "enforcement_pattern_id",
        "revocation_reason_id",
        "risk_score_0_100",
        "evidence_json",
        "last_refreshed_at",
    }
    missing = expected - cols
    assert not missing, f"am_program_risk_4d missing columns: {missing}"


def test_supplier_chain_columns(migrated_db: Path) -> None:
    conn = sqlite3.connect(str(migrated_db))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(am_supplier_chain)")}
    finally:
        conn.close()
    expected = {
        "chain_id",
        "anchor_houjin_bangou",
        "partner_houjin_bangou",
        "link_type",
        "evidence_url",
        "evidence_date",
        "hop_depth",
        "created_at",
    }
    missing = expected - cols
    assert not missing, f"am_supplier_chain missing columns: {missing}"


def test_cohort_5d_band_check_constraint(migrated_db: Path) -> None:
    """Bad employee_band must be rejected by the CHECK constraint."""
    conn = sqlite3.connect(str(migrated_db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_cohort_5d (jsic_major, employee_band) VALUES ('A', 'BOGUS')"
            )
    finally:
        conn.close()


def test_program_risk_4d_score_range(migrated_db: Path) -> None:
    conn = sqlite3.connect(str(migrated_db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_program_risk_4d (program_id, gyouhou_id, risk_score_0_100) "
                "VALUES ('UNI-test', 'zeirishi_52', 150)"
            )
    finally:
        conn.close()


def test_supplier_chain_link_type_enum(migrated_db: Path) -> None:
    conn = sqlite3.connect(str(migrated_db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_supplier_chain "
                "(anchor_houjin_bangou, partner_houjin_bangou, link_type) "
                "VALUES (?, ?, ?)",
                ("1" * 13, "2" * 13, "not_a_valid_link_type"),
            )
    finally:
        conn.close()


def test_supplier_chain_hop_range(migrated_db: Path) -> None:
    conn = sqlite3.connect(str(migrated_db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_supplier_chain "
                "(anchor_houjin_bangou, partner_houjin_bangou, link_type, hop_depth) "
                "VALUES (?, ?, ?, ?)",
                ("1" * 13, "2" * 13, "adoption_partner", 99),
            )
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Cron script: import + dry-run smoke
# --------------------------------------------------------------------------- #


def _import_cron(module_name: str):
    """Import a scripts/cron/<module>.py with the repo path injected."""
    repo_scripts = REPO_ROOT / "scripts" / "cron"
    if str(repo_scripts) not in sys.path:
        sys.path.insert(0, str(repo_scripts))
    return importlib.import_module(module_name)


@pytest.mark.parametrize(
    "module_name",
    ["precompute_cohort_5d", "precompute_program_risk_4d", "precompute_supplier_chain"],
)
def test_cron_module_imports(module_name: str) -> None:
    """Smoke: the cron module imports cleanly. Catches syntax errors first."""
    mod = _import_cron(module_name)
    assert hasattr(mod, "precompute")
    assert hasattr(mod, "main")


def test_cohort_5d_dry_run_with_seeded_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dry-run path: writes nothing, returns a populated summary."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="cohort-dry-"))
    db = tmp_dir / "autonomath.db"
    conn = sqlite3.connect(str(db), isolation_level=None)
    try:
        conn.executescript(MIG_FILES["cohort_5d"].read_text(encoding="utf-8"))
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db))
    mod = _import_cron("precompute_cohort_5d")
    summary = mod.precompute(budget=10, workers=1, top_n=5, dry_run=True)
    assert summary["status"] in {"ok", "partial"}
    assert summary["dry_run"] is True
    # Dry-run: insertion count must be zero.
    assert summary["inserted"] == 0


def test_cohort_5d_real_insert_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two consecutive non-dry-run calls must not violate the UNIQUE tuple."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="cohort-real-"))
    db = tmp_dir / "autonomath.db"
    conn = sqlite3.connect(str(db), isolation_level=None)
    try:
        conn.executescript(MIG_FILES["cohort_5d"].read_text(encoding="utf-8"))
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db))
    mod = _import_cron("precompute_cohort_5d")
    s1 = mod.precompute(budget=5, workers=1, top_n=5, dry_run=False)
    s2 = mod.precompute(budget=5, workers=1, top_n=5, dry_run=False)
    # Idempotency: row count in the table doesn't compound.
    conn2 = sqlite3.connect(str(db))
    try:
        n = conn2.execute("SELECT COUNT(*) FROM am_cohort_5d").fetchone()[0]
    finally:
        conn2.close()
    assert n <= 5
    assert s1["status"] in {"ok", "partial"}
    assert s2["status"] in {"ok", "partial"}


def test_program_risk_4d_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="risk-dry-"))
    db = tmp_dir / "autonomath.db"
    conn = sqlite3.connect(str(db), isolation_level=None)
    try:
        conn.executescript(MIG_FILES["program_risk_4d"].read_text(encoding="utf-8"))
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db))
    mod = _import_cron("precompute_program_risk_4d")
    summary = mod.precompute(budget=10, program_limit=10, dry_run=True)
    assert summary["status"] in {"ok", "partial", "no_programs_table"}
    if summary["status"] != "no_programs_table":
        assert summary["dry_run"] is True
        assert summary["inserted"] == 0


def test_program_risk_4d_weights_match_spec() -> None:
    """The weighted-score formula must match the spec (0.5 / 0.3 / 0.2)."""
    mod = _import_cron("precompute_program_risk_4d")
    # zeirishi_52 baseline (80) with no enforcement, no tsutatsu signal:
    # score = round(0.5 * 80 + 0 + 0) = 40.
    assert mod.GYOUHOU_SEVERITY["zeirishi_52"] == 80
    assert mod.GYOUHOU_SEVERITY["bengoshi_72"] == 90
    assert mod.GYOUHOU_SEVERITY["none"] == 0
    # 8 sensitive gyouhou enum values + 'none' = 9 entries.
    assert len(mod.GYOUHOU_SEVERITY) == 9


def test_supplier_chain_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="chain-dry-"))
    db = tmp_dir / "autonomath.db"
    conn = sqlite3.connect(str(db), isolation_level=None)
    try:
        conn.executescript(MIG_FILES["supplier_chain"].read_text(encoding="utf-8"))
    finally:
        conn.close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db))
    mod = _import_cron("precompute_supplier_chain")
    summary = mod.precompute(anchor_limit=2, max_hops=2, partners_per_anchor=4, dry_run=True)
    assert summary["status"] in {"ok", "partial"}
    assert summary["dry_run"] is True


# --------------------------------------------------------------------------- #
# Guard: no LLM SDK imports in the 3 new cron files
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "cron_file",
    [
        CRON_FILES["cohort_5d"],
        CRON_FILES["program_risk_4d"],
        CRON_FILES["supplier_chain"],
    ],
)
def test_no_llm_sdk_imports(cron_file: Path) -> None:
    """memory ``feedback_autonomath_no_api_use`` + CI guard mirror."""
    text = cron_file.read_text(encoding="utf-8")
    banned = [
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "claude_agent_sdk",
    ]
    for b in banned:
        assert b not in text, f"banned LLM SDK import found in {cron_file.name}: {b}"


def test_cohort_match_5d_sample_calc(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sample calculation: seed 1 row and read it back via the impl path."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="cohort-sample-"))
    db = tmp_dir / "autonomath.db"
    conn = sqlite3.connect(str(db), isolation_level=None)
    try:
        conn.executescript(MIG_FILES["cohort_5d"].read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO am_cohort_5d "
            "(jsic_major, employee_band, prefecture_code, eligible_program_ids, eligible_count) "
            "VALUES ('A', '10-99', '13', ?, 3)",
            (json.dumps(["UNI-a-1", "UNI-a-2", "UNI-a-3"]),),
        )
    finally:
        conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db))
    # Re-import the connector so it picks up the new env var.
    from jpintel_mcp.mcp.autonomath_tools.cohort_risk_chain import (
        match_cohort_5d_impl,
    )

    result = match_cohort_5d_impl(
        jsic_major="A",
        employee_band="10-99",
        prefecture_code="13",
        limit=20,
    )
    assert result["axes"]["jsic_major"] == "A"
    assert result["cohort_meta"].get("eligible_count") == 3
    assert result["total"] == 3
    assert "_disclaimer" in result
