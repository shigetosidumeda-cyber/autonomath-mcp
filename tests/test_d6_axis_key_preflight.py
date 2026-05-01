from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import preflight_axis_key_migration as preflight  # noqa: E402


def _build_db(path: Path, *, axis_key: bool = False) -> None:
    axis_column = ", axis_key TEXT NOT NULL DEFAULT ''" if axis_key else ""
    conn = sqlite3.connect(path)
    conn.executescript(
        f"""
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_value_text TEXT,
            field_kind TEXT NOT NULL{axis_column}
        );
        CREATE UNIQUE INDEX uq_am_facts_entity_field_text
            ON am_entity_facts(entity_id, field_name, COALESCE(field_value_text, ''));
        """
    )
    conn.commit()
    conn.close()


def test_axis_suffix_helpers_are_strict() -> None:
    assert preflight.axis_base("amount_max_yen__dup12") == "amount_max_yen"
    assert preflight.axis_key_from_field("amount_max_yen__dup12") == "dup12"
    assert preflight.axis_base("amount_max_yen__dup0") == "amount_max_yen__dup0"
    assert preflight.axis_key_from_field("amount_max_yen__dupx") == ""


def test_report_counts_dup_rows_amount_groups_and_no_violations(tmp_path: Path) -> None:
    db = tmp_path / "ok.db"
    _build_db(db)
    conn = sqlite3.connect(db)
    conn.executemany(
        "INSERT INTO am_entity_facts(id, entity_id, field_name, field_value_text, field_kind) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (1, "program:1", "amount_max_yen", "100000", "amount"),
            (2, "program:1", "amount_max_yen__dup1", "200000", "amount"),
            (3, "program:1", "name", "Program One", "text"),
            (4, "program:2", "amount_max_yen", "300000", "amount"),
        ],
    )
    conn.commit()
    conn.close()

    report = preflight.build_report(db)

    assert report["ok"] is True
    assert report["schema"]["has_axis_key"] is False
    assert report["counts"]["am_entity_facts_rows"] == 4
    assert report["counts"]["dup_suffix_rows"] == 1
    assert report["amount_multi_axis_groups"]["group_count"] == 1
    assert report["amount_multi_axis_groups"]["row_count"] == 2
    assert report["duplicate_violations"]["group_count"] == 0
    assert any("ADD COLUMN axis_key" in sql for sql in report["proposed_sql"])


def test_report_flags_duplicate_violation_when_axis_key_already_collides(
    tmp_path: Path,
) -> None:
    db = tmp_path / "violation.db"
    _build_db(db, axis_key=True)
    conn = sqlite3.connect(db)
    conn.executemany(
        "INSERT INTO am_entity_facts("
        "id, entity_id, field_name, field_value_text, field_kind, axis_key"
        ") VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "program:1", "amount_max_yen", "100000", "amount", "cap"),
            (2, "program:1", "amount_max_yen__dup1", "100000", "amount", "cap"),
            (3, "program:1", "amount_max_yen__dup2", "200000", "amount", "floor"),
        ],
    )
    conn.commit()
    conn.close()

    report = preflight.build_report(db)

    assert report["ok"] is False
    assert report["schema"]["has_axis_key"] is True
    assert report["counts"]["dup_suffix_rows"] == 2
    assert report["duplicate_violations"]["group_count"] == 1
    assert report["duplicate_violations"]["row_count"] == 2
    assert "duplicate_violations:proposed_unique_key" in report["issues"]
    assert not any("ADD COLUMN axis_key" in sql for sql in report["proposed_sql"])


def test_cli_writes_report_json_without_mutating_db(tmp_path: Path) -> None:
    db = tmp_path / "cli.db"
    output = tmp_path / "axis_key_preflight.json"
    _build_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO am_entity_facts(id, entity_id, field_name, field_value_text, field_kind) "
        "VALUES (1, 'program:1', 'amount_max_yen__dup1', '100000', 'amount')"
    )
    conn.commit()
    before_columns = [
        row[1] for row in conn.execute("PRAGMA table_info(am_entity_facts)").fetchall()
    ]
    conn.close()

    rc = preflight.main(["--db", str(db), "--output", str(output), "--json"])

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["counts"]["dup_suffix_rows"] == 1
    conn = sqlite3.connect(db)
    after_columns = [
        row[1] for row in conn.execute("PRAGMA table_info(am_entity_facts)").fetchall()
    ]
    conn.close()
    assert after_columns == before_columns
