from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import export_license_review_queue as export_queue  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            source_url TEXT NOT NULL,
            source_type TEXT,
            domain TEXT,
            first_seen TEXT,
            last_verified TEXT,
            license TEXT
        );
        CREATE TABLE am_entity_source (
            entity_id TEXT NOT NULL,
            source_id INTEGER NOT NULL
        );
        """
    )
    return conn


def test_collect_license_review_rows_filters_only_blocked_licenses() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_source(id, source_url, source_type, domain, license) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (1, "https://ok.example", "primary", "ok.example", "gov_standard_v2.0"),
            (2, "https://unknown.example", "primary", "unknown.example", "unknown"),
            (3, "https://prop.example", "primary", "prop.example", "proprietary"),
        ],
    )
    conn.executemany(
        "INSERT INTO am_entity_source(entity_id, source_id) VALUES (?, ?)",
        [("entity:1", 2), ("entity:2", 2), ("entity:3", 3)],
    )

    rows = export_queue.collect_license_review_rows(conn)

    assert [row["source_id"] for row in rows] == [3, 2]
    assert rows[0]["linked_entity_count"] == 1
    assert rows[1]["linked_entity_count"] == 2


def test_export_license_review_queue_writes_csv(tmp_path: Path) -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO am_source(id, source_url, source_type, domain, license) "
        "VALUES (?, ?, ?, ?, ?)",
        (2, "https://unknown.example", "primary", "unknown.example", "unknown"),
    )
    out = tmp_path / "queue.csv"

    result = export_queue.export_license_review_queue(conn, out, apply=True)

    assert result["blocked_source_rows"] == 1
    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["license"] == "unknown"
    assert rows[0]["source_url"] == "https://unknown.example"
