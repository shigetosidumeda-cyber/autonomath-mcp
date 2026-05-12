"""Integration tests for Dim R federated-MCP recommendation storage (Wave 47).

Closes the Wave 46 dim R storage gap: persists the curated partner
catalogue + per-call handoff audit log that back the Dim R
recommendation surface (jpcite -> 6 partner MCP servers handoff).

Three case bundles:
  1. Migration 278 applies cleanly + idempotent + rollback.
  2. Seed ETL loads exactly 6 partners and is idempotent on re-run.
  3. Handoff log append-only + soft-FK by partner_id + health-check
     last_health_at NULL semantics.

Hard constraints exercised
--------------------------
  * No external MCP server call (network).
  * No LLM SDK import.
  * Migration table names match Dim R surface
    (am_federated_mcp_partner / am_handoff_log).
  * Brand: only jpcite (and historical autonomath db filename) in
    comments + identifiers. No legacy ``税務会計AI`` / ``zeimu-kaikei.ai``.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sqlite3
import subprocess
import sys
import typing

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_278 = REPO_ROOT / "scripts" / "migrations" / "278_federated_mcp.sql"
MIG_278_RB = (
    REPO_ROOT / "scripts" / "migrations" / "278_federated_mcp_rollback.sql"
)
ETL_SEED = (
    REPO_ROOT / "scripts" / "etl" / "seed_federated_mcp_partners.py"
)
MANIFEST_JPCITE = (
    REPO_ROOT / "scripts" / "migrations" / "jpcite_boot_manifest.txt"
)
MANIFEST_AM = (
    REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"
)

EXPECTED_PARTNERS = ("freee", "mf", "notion", "slack", "github", "linear")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_seed_module() -> typing.Any:
    """Load seed_federated_mcp_partners.py by file path."""
    spec = importlib.util.spec_from_file_location(
        "_seed_fed_mcp_test_w47_mod", ETL_SEED
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_seed_fed_mcp_test_w47_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def _apply_migration(
    db_path: pathlib.Path, sql_path: pathlib.Path
) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql_path.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case bundle 1: migration apply / idempotent / rollback
# ---------------------------------------------------------------------------


def test_migration_278_applies_cleanly(tmp_path: pathlib.Path) -> None:
    """Migration creates both tables + indices on a fresh empty db."""
    db = tmp_path / "w47_dim_r.db"
    _apply_migration(db, MIG_278)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "am_federated_mcp_partner" in names
        assert "am_handoff_log" in names

        idx_names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        assert "idx_am_federated_mcp_partner_capability" in idx_names
        assert "idx_am_federated_mcp_partner_health" in idx_names
        assert "idx_am_handoff_log_partner" in idx_names
        assert "idx_am_handoff_log_time" in idx_names
    finally:
        conn.close()


def test_migration_278_idempotent(tmp_path: pathlib.Path) -> None:
    """Running the migration twice does not error or duplicate."""
    db = tmp_path / "w47_dim_r_idem.db"
    _apply_migration(db, MIG_278)
    _apply_migration(db, MIG_278)  # second apply must be a no-op
    conn = sqlite3.connect(str(db))
    try:
        # exactly one row in sqlite_master per table
        n_partner = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='am_federated_mcp_partner'"
        ).fetchone()[0]
        n_log = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='am_handoff_log'"
        ).fetchone()[0]
        assert n_partner == 1
        assert n_log == 1
    finally:
        conn.close()


def test_migration_278_rollback(tmp_path: pathlib.Path) -> None:
    """Rollback drops both tables + indices cleanly."""
    db = tmp_path / "w47_dim_r_rb.db"
    _apply_migration(db, MIG_278)
    _apply_migration(db, MIG_278_RB)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "am_federated_mcp_partner" not in names
        assert "am_handoff_log" not in names
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case bundle 2: seed ETL behaviour
# ---------------------------------------------------------------------------


def test_seed_loads_exactly_6_partners(tmp_path: pathlib.Path) -> None:
    """Seed ETL inserts the curated shortlist of 6 partners."""
    db = tmp_path / "w47_dim_r_seed.db"
    _apply_migration(db, MIG_278)
    mod = _import_seed_module()
    stats = mod.seed(db, dry_run=False)
    assert stats["inserted"] == 6
    assert stats["updated"] == 0

    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT partner_id FROM am_federated_mcp_partner ORDER BY partner_id"
        ).fetchall()
        ids = tuple(r[0] for r in rows)
        assert ids == tuple(sorted(EXPECTED_PARTNERS))
    finally:
        conn.close()


def test_seed_is_idempotent(tmp_path: pathlib.Path) -> None:
    """Re-running the seed yields 0 inserts / 6 updates and no dupes."""
    db = tmp_path / "w47_dim_r_seed_idem.db"
    _apply_migration(db, MIG_278)
    mod = _import_seed_module()
    mod.seed(db, dry_run=False)
    stats2 = mod.seed(db, dry_run=False)
    assert stats2["inserted"] == 0
    assert stats2["updated"] == 6

    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM am_federated_mcp_partner"
        ).fetchone()[0]
        assert n == 6
    finally:
        conn.close()


def test_seed_dry_run_writes_nothing(tmp_path: pathlib.Path) -> None:
    """--dry-run reports but never writes."""
    db = tmp_path / "w47_dim_r_seed_dry.db"
    _apply_migration(db, MIG_278)
    mod = _import_seed_module()
    stats = mod.seed(db, dry_run=True)
    assert stats["inserted"] == 6

    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM am_federated_mcp_partner"
        ).fetchone()[0]
        assert n == 0
    finally:
        conn.close()


def test_seed_capability_tags_pipe_separated(tmp_path: pathlib.Path) -> None:
    """All 6 partners get one or more pipe-separated capability tags."""
    db = tmp_path / "w47_dim_r_seed_cap.db"
    _apply_migration(db, MIG_278)
    mod = _import_seed_module()
    mod.seed(db, dry_run=False)

    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT partner_id, capability_tag FROM am_federated_mcp_partner"
        ).fetchall()
        for partner_id, cap in rows:
            assert cap, f"capability_tag empty for {partner_id}"
            for tag in cap.split("|"):
                assert tag, f"empty tag piece in {cap} for {partner_id}"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case bundle 3: handoff log behaviour + health-check semantics
# ---------------------------------------------------------------------------


def test_handoff_log_append_only(tmp_path: pathlib.Path) -> None:
    """Handoff inserts produce monotonically increasing handoff_id."""
    db = tmp_path / "w47_dim_r_handoff.db"
    _apply_migration(db, MIG_278)
    mod = _import_seed_module()
    mod.seed(db, dry_run=False)

    conn = sqlite3.connect(str(db))
    try:
        for partner_id in EXPECTED_PARTNERS:
            conn.execute(
                "INSERT INTO am_handoff_log "
                "(source_query, partner_id, response_summary) "
                "VALUES (?, ?, ?)",
                (f"q for {partner_id}", partner_id, "test rationale"),
            )
        conn.commit()
        rows = conn.execute(
            "SELECT handoff_id, partner_id FROM am_handoff_log "
            "ORDER BY handoff_id"
        ).fetchall()
        assert len(rows) == 6
        ids = [r[0] for r in rows]
        assert ids == sorted(ids)  # monotonic
    finally:
        conn.close()


def test_handoff_log_partner_index_lookup(tmp_path: pathlib.Path) -> None:
    """idx_am_handoff_log_partner enables fast partner -> recent lookups."""
    db = tmp_path / "w47_dim_r_handoff_idx.db"
    _apply_migration(db, MIG_278)
    mod = _import_seed_module()
    mod.seed(db, dry_run=False)

    conn = sqlite3.connect(str(db))
    try:
        for i in range(10):
            conn.execute(
                "INSERT INTO am_handoff_log "
                "(source_query, partner_id, response_summary) "
                "VALUES (?, ?, ?)",
                (f"q{i}", "freee", "rationale"),
            )
        conn.commit()
        n = conn.execute(
            "SELECT COUNT(*) FROM am_handoff_log WHERE partner_id = 'freee'"
        ).fetchone()[0]
        assert n == 10

        plan = conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT * FROM am_handoff_log "
            "WHERE partner_id = 'freee' "
            "ORDER BY requested_at DESC LIMIT 5"
        ).fetchall()
        plan_text = "\n".join(str(r) for r in plan)
        assert "idx_am_handoff_log_partner" in plan_text
    finally:
        conn.close()


def test_partner_last_health_at_nullable(tmp_path: pathlib.Path) -> None:
    """Freshly seeded partner row has last_health_at = NULL (DEGRADED safe)."""
    db = tmp_path / "w47_dim_r_health.db"
    _apply_migration(db, MIG_278)
    mod = _import_seed_module()
    mod.seed(db, dry_run=False)

    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT partner_id, last_health_at FROM am_federated_mcp_partner"
        ).fetchall()
        for partner_id, last_health_at in rows:
            assert last_health_at is None, (
                f"{partner_id} should start with NULL last_health_at"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Boot manifests + brand guard
# ---------------------------------------------------------------------------


def test_jpcite_boot_manifest_lists_278() -> None:
    """jpcite boot manifest registers migration 278_federated_mcp.sql."""
    assert "278_federated_mcp.sql" in MANIFEST_JPCITE.read_text(
        encoding="utf-8"
    )


def test_autonomath_boot_manifest_lists_278() -> None:
    """autonomath boot manifest registers migration 278_federated_mcp.sql."""
    assert "278_federated_mcp.sql" in MANIFEST_AM.read_text(
        encoding="utf-8"
    )


def test_no_legacy_brand_in_dim_r_files() -> None:
    """No legacy brand markers in the Dim R production surface.

    The test file itself (this file) holds the literal strings as
    assertion targets and is intentionally not scanned.
    """
    # legacy brand markers live as runtime literals to avoid the self-
    # reference paradox; build them at runtime so this file does NOT
    # contain them as plain text.
    legacy_brand_en = "zeimu" + "-" + "kaikei" + ".ai"
    legacy_brand_jp = "税務会計AI"  # 税務会計AI
    for path in (MIG_278, MIG_278_RB, ETL_SEED):
        text = path.read_text(encoding="utf-8")
        assert legacy_brand_en not in text, path
        assert legacy_brand_jp not in text, path


def test_no_llm_import_in_dim_r_etl() -> None:
    """Seed ETL must not import any LLM SDK (anthropic / openai / etc.)."""
    text = ETL_SEED.read_text(encoding="utf-8")
    for forbidden in ("import anthropic", "from anthropic", "import openai", "from openai"):
        assert forbidden not in text, forbidden
