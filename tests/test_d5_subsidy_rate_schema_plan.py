from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import plan_subsidy_rate_schema_migration as plan  # noqa: E402


def _create_program_table(
    path: Path,
    table_name: str,
    *,
    with_text_column: bool,
    rows: list[tuple[str, str, object, str | None]],
) -> None:
    text_column = ", subsidy_rate_text TEXT" if with_text_column else ""
    conn = sqlite3.connect(path)
    conn.executescript(
        f"""
        CREATE TABLE {table_name} (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            subsidy_rate REAL{text_column},
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_{table_name}_updated ON {table_name}(updated_at);
        """
    )
    if with_text_column:
        conn.executemany(
            f"""
            INSERT INTO {table_name}(
                unified_id, primary_name, subsidy_rate, subsidy_rate_text, updated_at
            )
            VALUES (?, ?, ?, ?, '2026-05-01T00:00:00Z')
            """,
            rows,
        )
    else:
        conn.executemany(
            f"""
            INSERT INTO {table_name}(unified_id, primary_name, subsidy_rate, updated_at)
            VALUES (?, ?, ?, '2026-05-01T00:00:00Z')
            """,
            [(uid, name, rate) for uid, name, rate, _rate_text in rows],
        )
    conn.commit()
    conn.close()


def _target_counts(report: dict, label: str) -> dict:
    target = next(item for item in report["targets"] if item["target"]["label"] == label)
    return target["counts"]


def _target_sql(report: dict, label: str, key: str) -> str:
    target = next(item for item in report["targets"] if item["target"]["label"] == label)
    return "\n".join(target[key])


def test_plan_reports_missing_text_column_and_text_contamination(tmp_path: Path) -> None:
    jpintel_db = tmp_path / "jpintel.db"
    autonomath_db = tmp_path / "autonomath.db"
    _create_program_table(
        jpintel_db,
        "programs",
        with_text_column=False,
        rows=[
            ("UNI-1", "Numeric", 0.5, None),
            ("UNI-2", "Text", "30%", None),
            ("UNI-3", "Null", None, None),
        ],
    )
    _create_program_table(
        autonomath_db,
        "jpi_programs",
        with_text_column=True,
        rows=[("UNI-1", "Numeric", 0.5, "1/2")],
    )

    report = plan.build_plan(
        [
            plan.DbTarget("jpintel", jpintel_db, "programs"),
            plan.DbTarget("autonomath", autonomath_db, "jpi_programs"),
        ],
        sample_limit=5,
    )

    jp_counts = _target_counts(report, "jpintel")
    assert report["ok"] is False
    assert report["summary_counts"]["contaminated_subsidy_rate_rows"] == 1
    assert report["summary_counts"]["targets_missing_subsidy_rate_text"] == 1
    assert jp_counts["contaminated_subsidy_rate_rows"] == 1
    assert jp_counts["contaminated_value_samples"] == [
        {"subsidy_rate_raw": "30%", "rows": 1}
    ]

    additive_sql = _target_sql(report, "jpintel", "data_preservation_sql")
    assert 'ALTER TABLE "programs" ADD COLUMN subsidy_rate_text TEXT;' in additive_sql
    assert "SET subsidy_rate_text = CAST(subsidy_rate AS TEXT)" in additive_sql

    rebuild_sql = _target_sql(report, "jpintel", "check_rebuild_sql")
    assert 'CREATE TABLE "programs__subsidy_rate_check_rebuild"' in rebuild_sql
    assert "CHECK (subsidy_rate IS NULL OR typeof(subsidy_rate)" in rebuild_sql
    assert "SELECT COUNT(*) AS blocking_subsidy_rate_text_rows" in rebuild_sql


def test_plan_detects_existing_text_column_and_zero_contamination(tmp_path: Path) -> None:
    jpintel_db = tmp_path / "jpintel.db"
    autonomath_db = tmp_path / "autonomath.db"
    _create_program_table(
        jpintel_db,
        "programs",
        with_text_column=True,
        rows=[
            ("UNI-1", "Numeric", 0.5, "1/2"),
            ("UNI-2", "Null", None, None),
        ],
    )
    _create_program_table(
        autonomath_db,
        "jpi_programs",
        with_text_column=True,
        rows=[("UNI-1", "Numeric", 0.5, "1/2")],
    )

    report = plan.build_plan(
        [
            plan.DbTarget("jpintel", jpintel_db, "programs"),
            plan.DbTarget("autonomath", autonomath_db, "jpi_programs"),
        ]
    )

    assert report["ok"] is True
    assert report["summary_counts"]["contaminated_subsidy_rate_rows"] == 0
    assert report["summary_counts"]["targets_missing_subsidy_rate_text"] == 0
    assert _target_counts(report, "jpintel")["subsidy_rate_text_nonblank_rows"] == 1

    additive_sql = _target_sql(report, "jpintel", "data_preservation_sql")
    assert "ADD COLUMN subsidy_rate_text" not in additive_sql
    assert "already exists; no ADD COLUMN needed" in additive_sql

    rebuild_sql = _target_sql(report, "jpintel", "check_rebuild_sql")
    assert "WHEN subsidy_rate_text IS NOT NULL THEN subsidy_rate_text" in rebuild_sql
    assert "CREATE INDEX idx_programs_updated ON programs(updated_at);" in rebuild_sql


def test_cli_writes_json_without_mutating_temp_databases(tmp_path: Path) -> None:
    jpintel_db = tmp_path / "jpintel.db"
    autonomath_db = tmp_path / "autonomath.db"
    output = tmp_path / "schema_plan.json"
    _create_program_table(
        jpintel_db,
        "programs",
        with_text_column=True,
        rows=[("UNI-1", "Numeric", 0.5, "1/2")],
    )
    _create_program_table(
        autonomath_db,
        "jpi_programs",
        with_text_column=True,
        rows=[("UNI-1", "Numeric", 0.5, "1/2")],
    )

    before = _columns(jpintel_db, "programs")
    rc = plan.main(
        [
            "--jpintel-db",
            str(jpintel_db),
            "--autonomath-db",
            str(autonomath_db),
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    assert _columns(jpintel_db, "programs") == before
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary_counts"]["target_count"] == 2
    assert payload["summary_counts"]["contaminated_subsidy_rate_rows"] == 0


def _columns(path: Path, table_name: str) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")]
    finally:
        conn.close()
