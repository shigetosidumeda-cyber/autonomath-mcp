from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import fix_subsidy_rate_text_values as fix  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            authority_level TEXT,
            authority_name TEXT,
            prefecture TEXT,
            municipality TEXT,
            source_url TEXT,
            official_url TEXT,
            subsidy_rate REAL
        );
        """
    )
    return conn


def _target() -> fix.DbTarget:
    return fix.DbTarget("temp", Path("temp.db"), "programs")


def test_parse_subsidy_rate_text_numeric_and_fixed_cases() -> None:
    cases = {
        "30%": (0.3, "set_numeric_max"),
        "2/3": (0.666667, "set_numeric_max"),
        "10/10": (1.0, "set_numeric_max"),
        "2/3 (中堅・中小) / 3/4 (小規模)": (0.75, "set_numeric_max"),
        "1/2 or 定額": (0.5, "set_numeric_max"),
        "価格連動(発動基準価格超過分 x 70% or 100%)": (
            1.0,
            "set_numeric_max",
        ),
        "定額": (None, "set_null_fixed_only"),
    }

    for raw, expected in cases.items():
        parsed = fix.parse_subsidy_rate_text(raw)
        assert parsed is not None
        assert (parsed.value, parsed.action) == expected


def test_parse_subsidy_rate_text_rejects_unparseable_values() -> None:
    assert fix.parse_subsidy_rate_text(None) is None
    assert fix.parse_subsidy_rate_text("") is None
    assert fix.parse_subsidy_rate_text("要確認") is None


def test_apply_updates_text_rows_and_preserves_review_csv(tmp_path: Path) -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO programs(unified_id, primary_name, subsidy_rate, source_url) "
        "VALUES (?, ?, ?, ?)",
        [
            ("UNI-1", "Percent", "30%", "https://example.test/1"),
            ("UNI-2", "Range", "2/3 (中堅) / 3/4 (小規模)", "https://example.test/2"),
            ("UNI-3", "Fixed", "定額", "https://example.test/3"),
            ("UNI-4", "Already numeric", 0.5, "https://example.test/4"),
        ],
    )
    fixes = fix.collect_subsidy_rate_fixes(conn, _target())
    out = tmp_path / "subsidy_rate_text_fix_review.csv"

    updated = fix.apply_subsidy_rate_fixes(conn, fixes)
    fix._write_review_csv(out, fixes)

    assert updated == 3
    rows = conn.execute(
        "SELECT unified_id, subsidy_rate, typeof(subsidy_rate) AS value_type "
        "FROM programs ORDER BY unified_id"
    ).fetchall()
    assert [(row["unified_id"], row["subsidy_rate"], row["value_type"]) for row in rows] == [
        ("UNI-1", 0.3, "real"),
        ("UNI-2", 0.75, "real"),
        ("UNI-3", None, "null"),
        ("UNI-4", 0.5, "real"),
    ]

    with out.open(encoding="utf-8", newline="") as f:
        csv_rows = list(csv.DictReader(f))
    assert [row["original_subsidy_rate_text"] for row in csv_rows] == [
        "30%",
        "2/3 (中堅) / 3/4 (小規模)",
        "定額",
    ]
    assert [row["parsed_subsidy_rate"] for row in csv_rows] == ["0.3", "0.75", ""]


def test_apply_is_idempotent_after_text_values_are_fixed() -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO programs(unified_id, primary_name, subsidy_rate) "
        "VALUES ('UNI-1', 'Formula', '70% or 100%')"
    )

    first_fixes = fix.collect_subsidy_rate_fixes(conn, _target())
    first_updated = fix.apply_subsidy_rate_fixes(conn, first_fixes)
    second_fixes = fix.collect_subsidy_rate_fixes(conn, _target())
    second_updated = fix.apply_subsidy_rate_fixes(conn, second_fixes)

    assert first_updated == 1
    assert second_fixes == []
    assert second_updated == 0
