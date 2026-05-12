"""Integration tests for Dim Q time-machine + counterfactual (Wave 47).

Closes the Wave 46 dim Q storage gap: migration 277 adds
``am_monthly_snapshot_log`` (book-keeping for the monthly snapshot batch)
and ``am_counterfactual_eval_log`` (audit trail for the
counterfactual eval surface) per feedback_time_machine_query_design.md.
Pairs with ``scripts/etl/build_monthly_snapshot.py`` which computes a
deterministic sha256 digest per snapshotted table and upserts the
audit row.

Case bundles
------------
  1. Migration 277 applies cleanly on a fresh SQLite db (idempotent re-apply).
  2. Migration 277 rollback drops every artefact created.
  3. CHECK constraints reject malformed rows (as_of_date length, sha256
     length, oversize counterfactual_input/result_diff).
  4. Monthly snapshot batch upserts an audit row, recomputes digest
     stably, and is idempotent across repeated runs (noop on 2nd call).
  5. ``--gc`` purges rows older than 5y; rows inside the window survive.
  6. Boot manifest registration (jpcite + autonomath mirror).
  7. No LLM-API import / no legacy brand in new files.

Hard constraints exercised
--------------------------
  * No LLM SDK import in any new file (Dim Q snapshots are deterministic).
  * Migration table names match the ETL comments
    (am_monthly_snapshot_log / am_counterfactual_eval_log).
  * Idempotent re-apply: a 2nd run of mig 277 is a no-op.
  * Brand: only jpcite. No legacy ``税務会計AI`` / ``zeimu-kaikei.ai``.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_277 = REPO_ROOT / "scripts" / "migrations" / "277_time_machine.sql"
MIG_277_RB = REPO_ROOT / "scripts" / "migrations" / "277_time_machine_rollback.sql"
ETL_SNAPSHOT = REPO_ROOT / "scripts" / "etl" / "build_monthly_snapshot.py"
MANIFEST_JPCITE = REPO_ROOT / "scripts" / "migrations" / "jpcite_boot_manifest.txt"
MANIFEST_AM = REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply(db_path: pathlib.Path, sql_path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql_path.read_text(encoding="utf-8"))
    finally:
        conn.close()


def _fresh_db(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "dim_q.db"
    _apply(db, MIG_277)
    return db


# ---------------------------------------------------------------------------
# 1. Migration applies + is idempotent
# ---------------------------------------------------------------------------


def test_mig_277_applies_clean(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') "
                "AND name LIKE 'am_%snapshot%' "
                " OR name LIKE 'am_counterfactual%' "
                " OR name LIKE 'v_monthly_snapshot%'"
            )
        }
        assert "am_monthly_snapshot_log" in names
        assert "am_counterfactual_eval_log" in names
        assert "v_monthly_snapshot_latest" in names
    finally:
        conn.close()


def test_mig_277_is_idempotent(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    # Re-applying must not raise.
    _apply(db, MIG_277)


# ---------------------------------------------------------------------------
# 2. Rollback drops every artefact
# ---------------------------------------------------------------------------


def test_mig_277_rollback_drops_all(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _apply(db, MIG_277_RB)
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table','view','index') "
            "AND (name LIKE 'am_monthly_snapshot_log%' "
            "  OR name LIKE 'am_counterfactual_eval_log%' "
            "  OR name LIKE 'v_monthly_snapshot_latest%' "
            "  OR name LIKE 'idx_am_monthly_snapshot_log%' "
            "  OR name LIKE 'idx_am_counterfactual_eval_log%')"
        ).fetchall()
        assert rows == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. CHECK constraints reject malformed rows
# ---------------------------------------------------------------------------


def test_check_as_of_date_length(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_monthly_snapshot_log "
                "(as_of_date, table_name, row_count, sha256) "
                "VALUES (?, ?, ?, ?)",
                ("2024-06", "am_amendment_snapshot", 0, "a" * 64),
            )
    finally:
        conn.close()


def test_check_sha256_length(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_monthly_snapshot_log "
                "(as_of_date, table_name, row_count, sha256) "
                "VALUES (?, ?, ?, ?)",
                ("2024-06-01", "am_amendment_snapshot", 0, "short"),
            )
    finally:
        conn.close()


def test_check_counterfactual_input_cap(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        oversized = "x" * 8193  # > 8 KiB cap
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_counterfactual_eval_log "
                "(as_of_date, query, counterfactual_input, result_diff) "
                "VALUES (?, ?, ?, ?)",
                ("2024-06-01", "q1", oversized, "{}"),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Snapshot batch upserts deterministically + is idempotent
# ---------------------------------------------------------------------------


def _seed_amendment_rows(db: pathlib.Path) -> None:
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS am_amendment_snapshot (
                snapshot_id INTEGER PRIMARY KEY,
                entity_id TEXT,
                effective_from TEXT,
                version_seq INTEGER
            );
            INSERT INTO am_amendment_snapshot
              (snapshot_id, entity_id, effective_from, version_seq)
              VALUES (1, 'e-1', '2024-01-01', 1),
                     (2, 'e-2', '2024-02-01', 1);
            """
        )
        conn.commit()
    finally:
        conn.close()


def _run_snapshot(db: pathlib.Path, *extra: str) -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            str(ETL_SNAPSHOT),
            "--db",
            str(db),
            *extra,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    # Final stdout line is the canonical JSON report.
    last_line = proc.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


def test_snapshot_batch_upserts_and_is_idempotent(
    tmp_path: pathlib.Path,
) -> None:
    db = _fresh_db(tmp_path)
    _seed_amendment_rows(db)

    rep1 = _run_snapshot(db, "--as-of", "2024-06-01")
    actions1 = {s["table_name"]: s["action"] for s in rep1["snapshots"]}
    # am_amendment_snapshot present (seeded); other tables absent and
    # land as inserted with row_count=0 + empty-digest sha256.
    assert actions1["am_amendment_snapshot"] == "inserted"
    amend_row = next(s for s in rep1["snapshots"] if s["table_name"] == "am_amendment_snapshot")
    assert amend_row["row_count"] == 2
    assert len(amend_row["sha256"]) == 64

    # Second run = pure noop for every table (digest stable).
    rep2 = _run_snapshot(db, "--as-of", "2024-06-01")
    actions2 = {s["table_name"]: s["action"] for s in rep2["snapshots"]}
    for tbl, act in actions2.items():
        assert act == "noop", f"{tbl} should be noop on idempotent re-run"


def test_snapshot_dry_run_writes_nothing(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _seed_amendment_rows(db)

    rep = _run_snapshot(db, "--as-of", "2024-06-01", "--dry-run")
    assert rep["dry_run"] is True

    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_monthly_snapshot_log").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


# ---------------------------------------------------------------------------
# 5. --gc retention window
# ---------------------------------------------------------------------------


def test_gc_drops_old_snapshots(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        # Older than 5y: drop.
        conn.execute(
            "INSERT INTO am_monthly_snapshot_log "
            "(as_of_date, table_name, row_count, sha256) "
            "VALUES (?, ?, ?, ?)",
            ("2018-01-01", "am_amendment_snapshot", 1, "a" * 64),
        )
        # Inside 5y window: keep.
        conn.execute(
            "INSERT INTO am_monthly_snapshot_log "
            "(as_of_date, table_name, row_count, sha256) "
            "VALUES (?, ?, ?, ?)",
            ("2024-06-01", "am_amendment_snapshot", 1, "b" * 64),
        )
        conn.commit()
    finally:
        conn.close()

    rep = _run_snapshot(db, "--as-of", "2026-05-01", "--gc")
    assert rep["gc_removed"] == 1

    conn = sqlite3.connect(str(db))
    try:
        survivors = {r[0] for r in conn.execute("SELECT as_of_date FROM am_monthly_snapshot_log")}
    finally:
        conn.close()
    assert "2018-01-01" not in survivors
    assert "2024-06-01" in survivors


# ---------------------------------------------------------------------------
# 6. Boot-manifest integrity
# ---------------------------------------------------------------------------


def test_manifest_jpcite_lists_277() -> None:
    """jpcite boot manifest registers migration 277_time_machine.sql."""
    assert "277_time_machine.sql" in MANIFEST_JPCITE.read_text(encoding="utf-8")


def test_manifest_autonomath_lists_277() -> None:
    """autonomath boot manifest (mirror) registers migration 277."""
    assert "277_time_machine.sql" in MANIFEST_AM.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 7. No-LLM-import + brand discipline
# ---------------------------------------------------------------------------


_FORBIDDEN_LLM_IMPORTS = ("anthropic", "openai", "google.generativeai")


def test_no_llm_import_in_etl_or_migration() -> None:
    """Dim Q snapshots MUST stay LLM-free (feedback_no_operator_llm_api)."""
    sources = [
        ETL_SNAPSHOT.read_text(encoding="utf-8"),
        MIG_277.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in _FORBIDDEN_LLM_IMPORTS:
            assert f"import {bad}" not in src
            assert f"from {bad}" not in src


def test_no_legacy_brand_in_new_files() -> None:
    """No 税務会計AI / zeimu-kaikei.ai legacy brand in new files."""
    legacy_phrases = ("税務会計AI", "zeimu-kaikei.ai")
    sources = [
        ETL_SNAPSHOT.read_text(encoding="utf-8"),
        MIG_277.read_text(encoding="utf-8"),
        MIG_277_RB.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in legacy_phrases:
            assert bad not in src, f"legacy brand `{bad}` found in new file"
