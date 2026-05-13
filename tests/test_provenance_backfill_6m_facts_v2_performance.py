from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ETL_SCRIPT = REPO_ROOT / "scripts" / "etl" / "provenance_backfill_6M_facts_v2.py"


def _load_etl_module():
    spec = importlib.util.spec_from_file_location(
        "provenance_backfill_6M_facts_v2", ETL_SCRIPT
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _create_metadata_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            source_url TEXT
        );
        CREATE TABLE am_fact_metadata (
            fact_id TEXT PRIMARY KEY,
            source_doc TEXT,
            extracted_at TEXT,
            verified_by TEXT,
            confidence_lower REAL,
            confidence_upper REAL,
            ed25519_sig BLOB,
            updated_at TEXT
        );
        CREATE TABLE am_fact_attestation_log (
            log_id INTEGER PRIMARY KEY,
            fact_id TEXT,
            attester TEXT,
            signature_hex TEXT,
            notes TEXT
        );
        INSERT INTO am_source VALUES (1, 'https://example.test/source');
        """
    )


def test_provenance_backfill_paginates_integer_ids_without_text_cast() -> None:
    conn = sqlite3.connect(":memory:")
    _create_metadata_tables(conn)
    conn.executescript(
        """
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY,
            source_id INTEGER,
            source_url TEXT,
            confidence REAL,
            created_at TEXT
        );
        INSERT INTO am_entity_facts VALUES
          (10, 1, NULL, 0.9, '2026-05-10T00:00:00Z'),
          (1, 1, NULL, 0.5, '2026-05-01T00:00:00Z'),
          (2, 1, NULL, 0.6, '2026-05-02T00:00:00Z');
        """
    )
    etl = _load_etl_module()

    counts = etl._walk(conn, None, max_rows=0, chunk_size=1, dry_run=False)
    walked_fact_ids = [
        r[0]
        for r in conn.execute(
            "SELECT fact_id FROM am_fact_attestation_log ORDER BY log_id"
        ).fetchall()
    ]

    assert counts == {"upserted": 3, "unchanged": 0, "skipped": 0, "errors": 0}
    assert walked_fact_ids == ["1", "2", "10"]
    assert "CAST(id AS TEXT)" not in ETL_SCRIPT.read_text(encoding="utf-8")


def test_provenance_backfill_still_supports_text_ids() -> None:
    conn = sqlite3.connect(":memory:")
    _create_metadata_tables(conn)
    conn.executescript(
        """
        CREATE TABLE am_entity_facts (
            id TEXT PRIMARY KEY,
            source_id INTEGER,
            source_url TEXT,
            confidence REAL,
            created_at TEXT
        );
        INSERT INTO am_entity_facts VALUES
          ('fact-10', 1, NULL, 0.9, '2026-05-10T00:00:00Z'),
          ('fact-2', 1, NULL, 0.6, '2026-05-02T00:00:00Z');
        """
    )
    etl = _load_etl_module()

    counts = etl._walk(conn, None, max_rows=0, chunk_size=1, dry_run=False)
    metadata_ids = [
        r[0]
        for r in conn.execute(
            "SELECT fact_id FROM am_fact_metadata ORDER BY fact_id"
        ).fetchall()
    ]

    assert counts == {"upserted": 2, "unchanged": 0, "skipped": 0, "errors": 0}
    assert metadata_ids == ["fact-10", "fact-2"]
