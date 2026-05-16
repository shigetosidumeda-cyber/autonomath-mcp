"""Integration tests for Dim P composable-tools storage (Wave 47).

Closes the Wave 46 dim P storage gap: persists the 4 canonical composed
tools in ``am_composed_tool_catalog`` (mig 276) and verifies the audit
log table is wired with the expected indices.

Four case bundles:
  1. Migration applies cleanly on a fresh SQLite db (idempotent re-apply
     + rollback drops cleanly).
  2. ETL seed_composed_tools inserts 4 tools, dry-run reports identical
     stats, second apply is a no-op.
  3. Each seeded composition has a valid JSON chain with monotonic step
     order, recognised phases, and a positive savings_factor.
  4. Boot manifest registers the new migration, and the new files carry
     no LLM SDK imports and no legacy brand strings.

Hard constraints exercised
--------------------------
  * No LLM SDK import (Dim P is fully deterministic).
  * Composition catalogue table = ``am_composed_tool_catalog``.
  * Invocation log table = ``am_composed_tool_invocation_log``.
  * Helper view = ``v_composed_tools_latest``.
  * Idempotent re-apply: a 2nd run is a no-op.
  * Brand: only jpcite (and historical autonomath db filename) in
    comments + identifiers. No legacy ``税務会計AI`` / ``zeimu-kaikei.ai``.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_276 = REPO_ROOT / "scripts" / "migrations" / "276_composable_tools.sql"
MIG_276_RB = REPO_ROOT / "scripts" / "migrations" / "276_composable_tools_rollback.sql"
ETL_SEED = REPO_ROOT / "scripts" / "etl" / "seed_composed_tools.py"
MANIFEST_JPCITE = REPO_ROOT / "scripts" / "migrations" / "jpcite_boot_manifest.txt"
MANIFEST_AM = REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"

EXPECTED_TOOL_IDS = {
    "ultimate_due_diligence_kit",
    "construction_total_dd",
    "welfare_total_dd",
    "tourism_total_dd",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_migration(db_path: pathlib.Path, sql_path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        sql = sql_path.read_text(encoding="utf-8")
        conn.executescript(sql)
    finally:
        conn.close()


def _fresh_db_with_migration(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "composable_tools_test.db"
    _apply_migration(db, MIG_276)
    return db


# ---------------------------------------------------------------------------
# Case 1 — Migration apply + idempotent + rollback
# ---------------------------------------------------------------------------


def test_migration_276_creates_tables(tmp_path: pathlib.Path) -> None:
    """Migration 276 creates catalogue + invocation log + helper view."""
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
    assert "am_composed_tool_catalog" in names
    assert "am_composed_tool_invocation_log" in names
    assert "v_composed_tools_latest" in names


def test_migration_276_creates_indices(tmp_path: pathlib.Path) -> None:
    """Migration 276 creates the four indices for tool_id / domain / hash."""
    db = _fresh_db_with_migration(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        idx_names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name LIKE 'idx_am_composed_tool_%'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "idx_am_composed_tool_catalog_tool_version" in idx_names
    assert "idx_am_composed_tool_catalog_domain_status" in idx_names
    assert "idx_am_composed_tool_invocation_log_tool_time" in idx_names
    assert "idx_am_composed_tool_invocation_log_input_hash" in idx_names


def test_migration_276_idempotent(tmp_path: pathlib.Path) -> None:
    """Re-applying migration 276 is a no-op (every CREATE uses IF NOT EXISTS)."""
    db = _fresh_db_with_migration(tmp_path)
    _apply_migration(db, MIG_276)  # second apply must not raise
    conn = sqlite3.connect(str(db))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='am_composed_tool_catalog'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_migration_276_rollback_drops(tmp_path: pathlib.Path) -> None:
    """Rollback drops the storage surface cleanly."""
    db = _fresh_db_with_migration(tmp_path)
    _apply_migration(db, MIG_276_RB)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()
    assert "am_composed_tool_catalog" not in names
    assert "am_composed_tool_invocation_log" not in names


# ---------------------------------------------------------------------------
# Case 2 — ETL seed: dry-run + apply + idempotent
# ---------------------------------------------------------------------------


def test_seed_etl_dry_run(tmp_path: pathlib.Path) -> None:
    """Dry-run reports 4 inserted, 0 skipped, total=4; no rows written."""
    db = _fresh_db_with_migration(tmp_path)
    result = subprocess.run(
        [sys.executable, str(ETL_SEED), "--db", str(db), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stderr={result.stderr}"
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["dim"] == "P"
    assert payload["seed_stats"]["total"] == 4
    assert payload["seed_stats"]["inserted"] == 4
    # No actual write occurred.
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_composed_tool_catalog").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_seed_etl_apply_then_idempotent(tmp_path: pathlib.Path) -> None:
    """Two-shot apply: first writes 4 rows, second skips all 4."""
    db = _fresh_db_with_migration(tmp_path)
    first = subprocess.run(
        [sys.executable, str(ETL_SEED), "--db", str(db)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, f"stderr={first.stderr}"
    p1 = json.loads(first.stdout.strip().splitlines()[-1])
    assert p1["seed_stats"]["inserted"] == 4
    assert p1["seed_stats"]["skipped"] == 0

    second = subprocess.run(
        [sys.executable, str(ETL_SEED), "--db", str(db)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, f"stderr={second.stderr}"
    p2 = json.loads(second.stdout.strip().splitlines()[-1])
    assert p2["seed_stats"]["inserted"] == 0
    assert p2["seed_stats"]["skipped"] == 4


# ---------------------------------------------------------------------------
# Case 3 — Seeded rows have the expected shape
# ---------------------------------------------------------------------------


def test_seed_writes_4_canonical_tools(tmp_path: pathlib.Path) -> None:
    """The 4 canonical tool_ids land in the catalogue with valid JSON chains."""
    db = _fresh_db_with_migration(tmp_path)
    res = subprocess.run(
        [sys.executable, str(ETL_SEED), "--db", str(db)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"stderr={res.stderr}"
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT tool_id, version, status, domain, atomic_tool_chain "
            "FROM am_composed_tool_catalog ORDER BY tool_id"
        ).fetchall()
    finally:
        conn.close()
    tids = {r[0] for r in rows}
    assert tids == EXPECTED_TOOL_IDS
    for tid, version, status, domain, chain_json in rows:
        assert version == 1
        assert status == "committed"
        assert domain  # non-empty
        chain = json.loads(chain_json)
        assert isinstance(chain, dict)
        assert chain["tool_id"] == tid
        # Monotonic step ordering 1..N.
        atomic = chain["atomic_chain"]
        assert isinstance(atomic, list)
        assert len(atomic) >= 4
        for idx, step_obj in enumerate(atomic, start=1):
            assert step_obj["step"] == idx
            assert step_obj["tool"]  # non-empty atomic tool name
            assert step_obj["phase"]  # non-empty phase tag
        # Savings factor = chain length (one composed call replaces N atomic).
        assert chain["savings_factor"] == len(atomic)


def test_seed_latest_view_resolves_committed(tmp_path: pathlib.Path) -> None:
    """v_composed_tools_latest exposes the 4 committed tools at version 1."""
    db = _fresh_db_with_migration(tmp_path)
    res = subprocess.run(
        [sys.executable, str(ETL_SEED), "--db", str(db)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    conn = sqlite3.connect(str(db))
    try:
        rows = dict(
            conn.execute("SELECT tool_id, latest_version FROM v_composed_tools_latest").fetchall()
        )
    finally:
        conn.close()
    assert set(rows.keys()) == EXPECTED_TOOL_IDS
    for v in rows.values():
        assert v == 1


def test_invocation_log_appends_row(tmp_path: pathlib.Path) -> None:
    """Audit log accepts a synthetic invocation row with valid CHECKs."""
    db = _fresh_db_with_migration(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO am_composed_tool_invocation_log "
            "(tool_id, tool_version, input_hash, output_hash, latency_ms, result) "
            "VALUES (?, 1, ?, ?, 12, 'ok')",
            (
                "ultimate_due_diligence_kit",
                "a" * 64,
                "b" * 64,
            ),
        )
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM am_composed_tool_invocation_log").fetchone()[0]
    finally:
        conn.close()
    assert n == 1


# ---------------------------------------------------------------------------
# Case 4 — Boot-manifest integrity + no-LLM + brand discipline
# ---------------------------------------------------------------------------


def test_manifest_jpcite_lists_276() -> None:
    """jpcite boot manifest registers migration 276_composable_tools.sql."""
    assert "276_composable_tools.sql" in MANIFEST_JPCITE.read_text(encoding="utf-8")


def test_manifest_autonomath_lists_276() -> None:
    """autonomath boot manifest (mirror) registers migration 276."""
    assert "276_composable_tools.sql" in MANIFEST_AM.read_text(encoding="utf-8")


_FORBIDDEN_LLM_IMPORTS = ("anthropic", "openai", "google.generativeai")


def test_no_llm_import_in_etl_or_migration() -> None:
    """Dim P storage MUST stay LLM-free (feedback_no_operator_llm_api)."""
    sources = [
        ETL_SEED.read_text(encoding="utf-8"),
        MIG_276.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in _FORBIDDEN_LLM_IMPORTS:
            assert f"import {bad}" not in src
            assert f"from {bad}" not in src


def test_no_legacy_brand_in_new_files() -> None:
    """No 税務会計AI / zeimu-kaikei.ai legacy brand in the new files."""
    legacy_phrases = ("税務会計AI", "zeimu-kaikei.ai")
    sources = [
        ETL_SEED.read_text(encoding="utf-8"),
        MIG_276.read_text(encoding="utf-8"),
        MIG_276_RB.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in legacy_phrases:
            assert bad not in src, f"legacy brand `{bad}` found in new file"
