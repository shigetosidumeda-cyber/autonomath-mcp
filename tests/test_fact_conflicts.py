from __future__ import annotations

import sqlite3

from jpintel_mcp.services.fact_conflicts import compute_entity_conflict_metadata


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_value_text TEXT,
            field_value_numeric REAL,
            field_value_json TEXT,
            source_id INTEGER,
            source_url TEXT
        );
        """
    )
    return conn


def _field(metadata: dict, name: str) -> dict:
    return next(field for field in metadata["fields"] if field["field_name"] == name)


def test_text_numeric_and_json_values_are_normalized() -> None:
    conn = _build_db()
    conn.executemany(
        """
        INSERT INTO am_entity_facts(
            id, entity_id, field_name, field_value_text, field_value_numeric,
            field_value_json, source_id, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "e1", "primary_name", "  Alpha\n Program  ", None, None, 1, None),
            (2, "e1", "primary_name", "Alpha Program", None, None, 2, None),
            (3, "e1", "amount_max_yen", None, 100.0, None, 1, None),
            (4, "e1", "amount_max_yen", None, 100, None, 2, None),
            (5, "e1", "eligibility_json", None, None, '{"b":2,"a":1}', 1, None),
            (6, "e1", "eligibility_json", None, None, '{"a":1,"b":2}', 2, None),
        ],
    )

    metadata = compute_entity_conflict_metadata(conn, "e1")

    assert metadata is not None
    assert _field(metadata, "primary_name")["distinct_value_count"] == 1
    assert _field(metadata, "amount_max_yen")["values"][0]["normalized_value"] == "100"
    assert _field(metadata, "eligibility_json")["values"][0]["normalized_value"] == (
        '{"a":1,"b":2}'
    )
    assert metadata["summary"]["conflict_count"] == 0


def test_null_values_are_ignored() -> None:
    conn = _build_db()
    conn.executemany(
        """
        INSERT INTO am_entity_facts(
            id, entity_id, field_name, field_value_text, field_value_numeric,
            field_value_json, source_id, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "e1", "primary_name", None, None, None, 1, None),
            (2, "e1", "primary_name", "Program", None, None, 2, None),
            (3, "e1", "notes", "   ", None, None, 3, None),
        ],
    )

    metadata = compute_entity_conflict_metadata(conn, "e1")

    assert metadata is not None
    assert metadata["summary"]["fields_checked"] == 1
    assert _field(metadata, "primary_name")["fact_count"] == 1
    assert _field(metadata, "primary_name")["status"] == "consistent"


def test_source_url_is_used_when_source_id_is_missing() -> None:
    conn = _build_db()
    conn.executemany(
        """
        INSERT INTO am_entity_facts(
            id, entity_id, field_name, field_value_text, field_value_numeric,
            field_value_json, source_id, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "e1", "primary_name", "Program", None, None, None, "HTTPS://Example.GO.JP/a/#x"),
            (2, "e1", "primary_name", "Program", None, None, None, "https://example.go.jp/a"),
        ],
    )

    metadata = compute_entity_conflict_metadata(conn, "e1")

    assert metadata is not None
    primary_name = _field(metadata, "primary_name")
    assert primary_name["source_count"] == 1
    assert primary_name["values"][0]["sources"] == [
        {"source_id": None, "source_url": "https://example.go.jp/a"}
    ]


def test_singleton_field_multiple_values_are_conflicts() -> None:
    conn = _build_db()
    conn.executemany(
        """
        INSERT INTO am_entity_facts(
            id, entity_id, field_name, field_value_text, field_value_numeric,
            field_value_json, source_id, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "e1", "amount_max_yen", None, 100, None, 1, None),
            (2, "e1", "amount_max_yen", None, 200, None, 2, None),
        ],
    )

    metadata = compute_entity_conflict_metadata(conn, "e1")

    assert metadata is not None
    assert metadata["summary"]["has_conflicts"] is True
    assert _field(metadata, "amount_max_yen")["status"] == "conflict"


def test_unallowlisted_field_multiple_values_are_multiple_values() -> None:
    conn = _build_db()
    conn.executemany(
        """
        INSERT INTO am_entity_facts(
            id, entity_id, field_name, field_value_text, field_value_numeric,
            field_value_json, source_id, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "e1", "target_industry", "manufacturing", None, None, 1, None),
            (2, "e1", "target_industry", "retail", None, None, 2, None),
        ],
    )

    metadata = compute_entity_conflict_metadata(conn, "e1")

    assert metadata is not None
    target_industry = _field(metadata, "target_industry")
    assert target_industry["status"] == "multiple_values"
    assert metadata["summary"]["conflict_count"] == 0
    assert metadata["summary"]["multiple_values_count"] == 1
