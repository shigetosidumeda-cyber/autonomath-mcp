from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import backfill_amendment_diff_from_snapshots as backfill  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_amendment_snapshot (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            version_seq INTEGER NOT NULL,
            observed_at TEXT NOT NULL,
            amount_max_yen INTEGER,
            subsidy_rate_max REAL,
            target_set_json TEXT,
            eligibility_hash TEXT,
            summary_hash TEXT,
            source_url TEXT,
            source_fetched_at TEXT,
            raw_snapshot_json TEXT,
            UNIQUE(entity_id, version_seq)
        );
        CREATE TABLE am_amendment_diff (
            diff_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            prev_value TEXT,
            new_value TEXT,
            prev_hash TEXT,
            new_hash TEXT,
            detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            source_url TEXT
        );
        """
    )
    return conn


def test_target_empty_equivalence_is_not_recorded() -> None:
    assert backfill.should_record_field_change("target_set_json", None, "[]") is False
    assert backfill.should_record_field_change("target_set_json", "", "[]") is False


def test_collect_snapshot_diffs_materializes_typed_field_changes() -> None:
    conn = _build_db()
    conn.executemany(
        """INSERT INTO am_amendment_snapshot
           (entity_id, version_seq, observed_at, amount_max_yen,
            subsidy_rate_max, target_set_json, eligibility_hash, summary_hash,
            source_url, source_fetched_at, raw_snapshot_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                "program:one",
                1,
                "2026-04-01",
                100,
                0.5,
                "[]",
                "eh",
                "sh",
                "https://a.example",
                "t1",
                "{}",
            ),
            (
                "program:one",
                2,
                "2026-04-02",
                200,
                0.5,
                None,
                "eh",
                "sh",
                "https://b.example",
                "t2",
                "{}",
            ),
        ],
    )

    diffs = backfill.collect_snapshot_diffs(conn)

    assert [(d.entity_id, d.field_name, d.prev_value, d.new_value) for d in diffs[:3]] == [
        ("program:one", "amount_max_yen", "100", "200"),
        ("program:one", "source_url", "https://a.example", "https://b.example"),
        ("program:one", "source_fetched_at", "t1", "t2"),
    ]
    assert diffs[3].field_name == "projection_regression_candidate"
    assert '"amount_max_yen"' in (diffs[3].new_value or "")


def test_insert_snapshot_diffs_is_idempotent() -> None:
    conn = _build_db()
    conn.executemany(
        """INSERT INTO am_amendment_snapshot
           (entity_id, version_seq, observed_at, amount_max_yen, source_url)
           VALUES (?, ?, ?, ?, ?)""",
        [
            ("program:one", 1, "2026-04-01", 100, "https://a.example"),
            ("program:one", 2, "2026-04-02", 200, "https://a.example"),
        ],
    )
    conn.commit()
    diffs = backfill.collect_snapshot_diffs(conn)

    first = backfill.insert_snapshot_diffs(conn, diffs, apply=True)
    second = backfill.insert_snapshot_diffs(conn, diffs, apply=True)

    assert first["inserted_diffs"] == 2
    assert first["am_amendment_diff_after"] == 2
    assert second["inserted_diffs"] == 0
    assert second["am_amendment_diff_after"] == 2
