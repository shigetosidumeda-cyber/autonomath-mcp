from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import promote_houjin_relations as promote  # noqa: E402


def test_normalize_houjin_bangou_accepts_t_prefix_and_width_noise() -> None:
    assert promote.normalize_houjin_bangou("T１２３-４５６７-８９０１２３") == "1234567890123"
    assert promote.normalize_houjin_bangou("not-a-number") is None


def test_extract_houjin_bangou_checks_supported_json_keys() -> None:
    raw = json.dumps({"invoice_registration_number": "T1234567890123"})
    assert promote.extract_houjin_bangou(raw) == "1234567890123"
    assert promote.extract_houjin_bangou("{bad json") is None


def test_collect_houjin_edges_only_targets_existing_corporate_nodes() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_entities (
            canonical_id TEXT PRIMARY KEY,
            record_kind TEXT NOT NULL,
            raw_json TEXT
        );
        CREATE TABLE am_relation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_entity_id TEXT NOT NULL,
            target_entity_id TEXT,
            target_raw TEXT,
            relation_type TEXT NOT NULL,
            confidence REAL NOT NULL,
            origin TEXT NOT NULL,
            source_field TEXT,
            harvested_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO am_entities VALUES (?, ?, ?)",
        ("houjin:1234567890123", "corporate_entity", "{}"),
    )
    conn.execute(
        "INSERT INTO am_entities VALUES (?, ?, ?)",
        (
            "adoption:test:1",
            "adoption",
            json.dumps({"houjin_bangou": "1234567890123"}),
        ),
    )
    conn.execute(
        "INSERT INTO am_entities VALUES (?, ?, ?)",
        (
            "adoption:test:2",
            "adoption",
            json.dumps({"houjin_bangou": "9999999999999"}),
        ),
    )

    edges = promote.collect_houjin_edges(conn)

    assert [(e.source_entity_id, e.target_entity_id) for e in edges] == [
        ("adoption:test:1", "houjin:1234567890123")
    ]
    assert edges[0].relation_type == "related"
    assert edges[0].source_field == "harvest:raw_json.houjin_bangou"
