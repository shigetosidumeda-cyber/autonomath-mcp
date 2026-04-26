"""Tests for lineage tracking: migration + ingest + API surface."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# The migrate module lives under scripts/, which is not a package.
# Put it on sys.path so tests can import it directly.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import migrate  # noqa: E402


def _programs_columns(conn: sqlite3.Connection) -> set[str]:
    return {row["name"] for row in conn.execute("PRAGMA table_info(programs)")}


def _create_empty_programs_table(db_path: Path) -> None:
    """Build a minimal pre-lineage DB to simulate an old production instance.

    Includes every table that existed before the first migration so that
    later migrations (which may ALTER any of them) find their targets.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """CREATE TABLE programs (
                unified_id TEXT PRIMARY KEY,
                primary_name TEXT NOT NULL,
                aliases_json TEXT,
                authority_level TEXT,
                authority_name TEXT,
                prefecture TEXT,
                municipality TEXT,
                program_kind TEXT,
                official_url TEXT,
                amount_max_man_yen REAL,
                amount_min_man_yen REAL,
                subsidy_rate REAL,
                trust_level TEXT,
                tier TEXT,
                coverage_score REAL,
                gap_to_tier_s_json TEXT,
                a_to_j_coverage_json TEXT,
                excluded INTEGER DEFAULT 0,
                exclusion_reason TEXT,
                crop_categories_json TEXT,
                equipment_category TEXT,
                target_types_json TEXT,
                funding_purpose_json TEXT,
                amount_band TEXT,
                application_window_json TEXT,
                enriched_json TEXT,
                source_mentions_json TEXT,
                updated_at TEXT NOT NULL
            )"""
        )
        # Tables already present on pre-migration prod DBs (see schema.sql).
        # Migrations downstream may ALTER these (e.g. 005 adds a column to
        # usage_events), so the stub DB must include them.
        conn.execute(
            """CREATE TABLE api_keys (
                key_hash TEXT PRIMARY KEY,
                customer_id TEXT,
                tier TEXT NOT NULL,
                stripe_subscription_id TEXT,
                created_at TEXT NOT NULL,
                revoked_at TEXT,
                last_used_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                ts TEXT NOT NULL,
                status INTEGER,
                metered INTEGER DEFAULT 0,
                FOREIGN KEY(key_hash) REFERENCES api_keys(key_hash)
            )"""
        )
        conn.commit()
    finally:
        conn.close()


def test_migrate_on_empty_db_creates_columns(tmp_path: Path) -> None:
    db = tmp_path / "empty_for_migration.db"
    _create_empty_programs_table(db)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        cols_before = _programs_columns(conn)
    finally:
        conn.close()

    assert "source_url" not in cols_before
    assert "source_fetched_at" not in cols_before
    assert "source_checksum" not in cols_before

    applied = migrate.run_migrations(db)
    assert "001_lineage.sql" in applied

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        cols_after = _programs_columns(conn)
        # schema_migrations bookkeeping must also exist.
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        # Idx must be registered.
        indexes = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    finally:
        conn.close()

    assert "source_url" in cols_after
    assert "source_fetched_at" in cols_after
    assert "source_checksum" in cols_after
    assert "schema_migrations" in tables
    assert "idx_programs_source_fetched" in indexes


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "idempotent.db"
    _create_empty_programs_table(db)

    first = migrate.run_migrations(db)
    assert "001_lineage.sql" in first
    first_count = len(first)

    second = migrate.run_migrations(db)
    assert second == []

    third = migrate.run_migrations(db)
    assert third == []

    conn = sqlite3.connect(str(db))
    try:
        (n,) = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()
    finally:
        conn.close()
    assert n == first_count


def test_ingest_populates_lineage_fields(tmp_path: Path, monkeypatch) -> None:
    # Build a minimal Autonomath-shaped tree in tmp so the canonical ingest
    # has something to read without touching the real /Users/shigetoumeda/Autonomath.
    autonomath_root = tmp_path / "autonomath"
    registry_dir = autonomath_root / "data"
    enriched_dir = autonomath_root / "backend" / "knowledge_base" / "data" / "canonical" / "enriched"
    agri_dir = autonomath_root / "backend" / "knowledge_base" / "data" / "agri"
    enriched_dir.mkdir(parents=True)
    registry_dir.mkdir(parents=True, exist_ok=True)
    agri_dir.mkdir(parents=True, exist_ok=True)

    registry = {
        "_meta": {"generated_at": "2026-04-22T00:00:00Z"},
        "programs": {
            "UNI-lineage-test-1": {
                "primary_name": "lineage test program",
                "tier": "A",
                "authority_level": "国",
                "prefecture": "東京都",
                "program_kind": "補助金",
                "official_url": "https://example.gov.jp/program/1",
                "amount_max_man_yen": 100,
            }
        },
    }
    (registry_dir / "unified_registry.json").write_text(
        json.dumps(registry, ensure_ascii=False), encoding="utf-8"
    )
    (enriched_dir / "UNI-lineage-test-1.json").write_text(
        json.dumps(
            {"official_url": "https://example.gov.jp/program/1", "body": "detail text"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (agri_dir / "exclusion_rules.json").write_text(
        json.dumps({"rules": {}}, ensure_ascii=False), encoding="utf-8"
    )

    # Fresh isolated DB for this test.
    db_path = tmp_path / "ingest_target.db"
    monkeypatch.setenv("JPINTEL_DB_PATH", str(db_path))
    monkeypatch.setenv("JPINTEL_AUTONOMATH_PATH", str(autonomath_root))

    # Purge cached jpintel_mcp modules so Settings re-reads env.
    for mod in list(sys.modules):
        if mod.startswith("jpintel_mcp"):
            del sys.modules[mod]

    from jpintel_mcp.ingest.canonical import run as ingest_run

    rc = ingest_run()
    assert rc == 0

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT source_url, source_fetched_at, source_checksum "
            "FROM programs WHERE unified_id = ?",
            ("UNI-lineage-test-1",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["source_url"] == "https://example.gov.jp/program/1"
    assert row["source_fetched_at"] is not None
    assert len(row["source_fetched_at"]) >= 19  # ISO-8601-ish
    assert row["source_checksum"] is not None
    assert len(row["source_checksum"]) == 16  # truncated sha256

    # Re-purge so the rest of the test suite sees its original env again.
    for mod in list(sys.modules):
        if mod.startswith("jpintel_mcp"):
            del sys.modules[mod]
