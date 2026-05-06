from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import backfill_program_fact_source_ids as backfill  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            source_url TEXT NOT NULL UNIQUE
        );
        CREATE TABLE am_entities (
            canonical_id TEXT PRIMARY KEY,
            record_kind TEXT NOT NULL,
            source_url TEXT
        );
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            source_url TEXT,
            source_id INTEGER
        );
        CREATE TABLE am_entity_source (
            entity_id TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT '',
            source_field TEXT,
            PRIMARY KEY (entity_id, source_id, role)
        );
        """
    )
    return conn


def test_normalize_source_url_strips_fragment_and_trailing_slash() -> None:
    assert (
        backfill.normalize_source_url("HTTPS://Example.GO.JP/path/%E8%A3%9C%E5%8A%A9/#section")
        == "https://example.go.jp/path/補助"
    )


def test_resolve_fact_source_prefers_fact_source_url_exact_match() -> None:
    fact = backfill.FactCandidate(
        fact_id=10,
        entity_id="program:one",
        fact_source_url="https://a.example/fact",
        entity_source_url="https://a.example/entity",
    )

    assignment = backfill.resolve_fact_source(
        fact,
        exact_sources={
            "https://a.example/fact": 1,
            "https://a.example/entity": 2,
        },
        normalized_sources={},
        entity_sources={},
        allow_ranked_fallback=False,
    )

    assert assignment == backfill.SourceAssignment(
        fact_id=10,
        entity_id="program:one",
        source_id=1,
        method="fact_source_url_exact",
    )


def test_backfill_program_fact_source_ids_uses_unambiguous_entity_source() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_source(id, source_url) VALUES (?, ?)",
        [(1, "https://a.example/source")],
    )
    conn.execute(
        "INSERT INTO am_entities(canonical_id, record_kind, source_url) VALUES (?, ?, ?)",
        ("program:one", "program", None),
    )
    conn.execute(
        "INSERT INTO am_entity_facts(id, entity_id, field_name, source_url, source_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (10, "program:one", "amount", None, None),
    )
    conn.execute(
        "INSERT INTO am_entity_source(entity_id, source_id, role, source_field) "
        "VALUES (?, ?, ?, ?)",
        ("program:one", 1, "primary_source", "am_entities.source_url"),
    )

    result = backfill.backfill_program_fact_source_ids(
        conn,
        apply=True,
        allow_ranked_fallback=False,
    )

    assert result["updated_rows"] == 1
    assert result["method_counts"] == {"entity_source_unambiguous": 1}
    assert conn.execute("SELECT source_id FROM am_entity_facts WHERE id = 10").fetchone()[0] == 1


def test_ranked_fallback_is_explicitly_gated() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_source(id, source_url) VALUES (?, ?)",
        [(1, "https://a.example/secondary"), (2, "https://a.example/primary")],
    )
    conn.execute(
        "INSERT INTO am_entities(canonical_id, record_kind, source_url) VALUES (?, ?, ?)",
        ("program:one", "program", None),
    )
    conn.execute(
        "INSERT INTO am_entity_facts(id, entity_id, field_name, source_url, source_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (10, "program:one", "amount", None, None),
    )
    conn.executemany(
        "INSERT INTO am_entity_source(entity_id, source_id, role, source_field) "
        "VALUES (?, ?, ?, ?)",
        [
            ("program:one", 1, "reference", "raw.reference_url"),
            ("program:one", 2, "official", "raw.official_url"),
        ],
    )

    conservative = backfill.backfill_program_fact_source_ids(
        conn,
        apply=False,
        allow_ranked_fallback=False,
    )
    ranked = backfill.backfill_program_fact_source_ids(
        conn,
        apply=True,
        allow_ranked_fallback=True,
    )

    assert conservative["candidate_assignments"] == 1
    assert conservative["method_counts"] == {"entity_source_unique_primary": 1}
    assert ranked["updated_rows"] == 1
    assert conn.execute("SELECT source_id FROM am_entity_facts WHERE id = 10").fetchone()[0] == 2
