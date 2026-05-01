from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import backfill_missing_authorities as d3  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_authority (
            canonical_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            canonical_en TEXT,
            level TEXT NOT NULL,
            parent_id TEXT,
            region_code TEXT,
            website TEXT,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE am_entities (
            canonical_id TEXT PRIMARY KEY,
            authority_canonical TEXT
        );
        INSERT INTO am_authority(canonical_id, canonical_name, level)
        VALUES ('authority:pref:hyogo', '兵庫県', 'prefecture');
        """
    )
    return conn


def test_backfill_missing_authorities_inserts_reviewed_seeds_only() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_entities(canonical_id, authority_canonical) VALUES (?, ?)",
        [
            ("entity-1", "authority:city-kobe"),
            ("entity-2", "authority:city-kobe"),
            ("entity-3", "authority:jsbri"),
            ("entity-4", "authority:unknown-local"),
        ],
    )

    result = d3.backfill_missing_authorities(conn, apply=True)

    assert result["known_orphan_authorities_before"] == 2
    assert result["known_orphan_refs_before"] == 3
    assert result["inserted_rows"] == 2
    assert result["unknown_orphan_authorities_before"] == ["authority:unknown-local"]
    assert result["orphan_authorities_after"] == 1
    assert result["orphan_refs_after"] == 1

    kobe = conn.execute(
        "SELECT canonical_name, level, parent_id, region_code "
        "FROM am_authority WHERE canonical_id='authority:city-kobe'"
    ).fetchone()
    assert dict(kobe) == {
        "canonical_name": "神戸市",
        "level": "designated_city",
        "parent_id": "authority:pref:hyogo",
        "region_code": "28100",
    }


def test_backfill_missing_authorities_is_idempotent() -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO am_entities(canonical_id, authority_canonical) VALUES (?, ?)",
        ("entity-1", "authority:city-takarazuka"),
    )

    first = d3.backfill_missing_authorities(conn, apply=True)
    second = d3.backfill_missing_authorities(conn, apply=True)

    assert first["inserted_rows"] == 1
    assert second["known_orphan_authorities_before"] == 0
    assert second["inserted_rows"] == 0
    assert second["orphan_refs_after"] == 0


def test_orphan_authority_counts_excludes_existing_authorities() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_entities(canonical_id, authority_canonical) VALUES (?, ?)",
        [
            ("entity-1", "authority:pref:hyogo"),
            ("entity-2", "authority:pref-aichi"),
            ("entity-3", None),
        ],
    )

    assert d3.orphan_authority_counts(conn) == {"authority:pref-aichi": 1}
