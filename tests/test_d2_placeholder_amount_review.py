from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import export_placeholder_amount_review as review  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_entities (
            canonical_id TEXT PRIMARY KEY,
            record_kind TEXT NOT NULL,
            primary_name TEXT NOT NULL,
            source_topic TEXT,
            source_url TEXT,
            raw_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_value_text TEXT,
            field_value_numeric REAL,
            field_kind TEXT NOT NULL,
            unit TEXT,
            source_url TEXT,
            source_id INTEGER
        );
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            license TEXT,
            domain TEXT,
            source_type TEXT
        );
        CREATE TABLE am_amount_condition (
            id INTEGER PRIMARY KEY,
            entity_id TEXT NOT NULL,
            condition_label TEXT NOT NULL,
            fixed_yen INTEGER,
            numeric_value REAL,
            unit TEXT,
            currency TEXT,
            source_field TEXT NOT NULL,
            evidence_fact_id INTEGER
        );
        """
    )
    return conn


def test_collect_flags_tiny_program_max_without_blanket_nulling_100() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_entities(canonical_id, record_kind, primary_name) "
        "VALUES (?, ?, ?)",
        [
            ("program:suspicious", "program", "Suspicious max"),
            ("program:legit", "program", "Legit one million"),
            ("program:fee", "program", "Application fee"),
            ("stat:one", "statistic", "Statistic 100"),
        ],
    )
    conn.executemany(
        "INSERT INTO am_entity_facts(id, entity_id, field_name, "
        "field_value_text, field_value_numeric, field_kind, unit) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                1,
                "program:suspicious",
                "amount_max_yen",
                "100",
                100,
                "amount",
                "yen",
            ),
            (
                2,
                "program:legit",
                "amount_max_yen",
                "1000000",
                1_000_000,
                "amount",
                "yen",
            ),
            (3, "program:fee", "application_fee_yen", "100", 100, "amount", "yen"),
            (4, "stat:one", "stat.accepted_count", "100", 100, "number", None),
        ],
    )
    conn.executemany(
        "INSERT INTO am_amount_condition(id, entity_id, condition_label, "
        "fixed_yen, currency, source_field, evidence_fact_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (10, "program:suspicious", "max", 100, "JPY", "amount_max_yen", 1),
            (11, "program:legit", "max", 1_000_000, "JPY", "amount_max_yen", 2),
            (
                12,
                "program:fee",
                "application_fee",
                100,
                "JPY",
                "application_fee_yen",
                3,
            ),
            (13, "stat:one", "max", 100, "JPY", "amount_max_yen", 4),
        ],
    )

    rows = review.collect_placeholder_amount_review_rows(conn)

    assert [row["amount_condition_id"] for row in rows] == [10]
    assert rows[0]["fixed_yen"] == 100
    assert rows[0]["reason"] == review.REASON_TINY_JPY_PROGRAM_MAX


def test_export_dry_run_does_not_write_csv(tmp_path: Path) -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO am_entities(canonical_id, record_kind, primary_name) "
        "VALUES ('program:one', 'program', 'One')"
    )
    conn.execute(
        "INSERT INTO am_amount_condition(id, entity_id, condition_label, "
        "fixed_yen, currency, source_field) "
        "VALUES (1, 'program:one', 'max', 200, 'JPY', 'amount_max_yen')"
    )
    out = tmp_path / "placeholder_amount_review.csv"

    result = review.export_placeholder_amount_review(conn, out, apply=False)

    assert result["mode"] == "dry_run"
    assert result["review_rows"] == 1
    assert result["by_fixed_yen"] == {"200": 1}
    assert not out.exists()


def test_export_apply_writes_deterministic_csv(tmp_path: Path) -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_entities(canonical_id, record_kind, primary_name) "
        "VALUES (?, 'program', ?)",
        [("program:b", "B"), ("program:a", "A")],
    )
    conn.executemany(
        "INSERT INTO am_amount_condition(id, entity_id, condition_label, "
        "fixed_yen, currency, source_field) "
        "VALUES (?, ?, 'max', ?, 'JPY', 'amount_max_yen')",
        [(2, "program:b", 200), (1, "program:a", 100)],
    )
    out = tmp_path / "placeholder_amount_review.csv"

    first = review.export_placeholder_amount_review(conn, out, apply=True)
    second = review.export_placeholder_amount_review(conn, out, apply=True)

    assert first["review_rows"] == second["review_rows"] == 2
    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [row["amount_condition_id"] for row in rows] == ["1", "2"]
    assert rows[0]["fixed_yen"] == "100"
    assert rows[1]["fixed_yen"] == "200"
