from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import report_adoption_program_join_gaps as gaps  # noqa: E402


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _build_adoption_db(path: Path) -> sqlite3.Connection:
    conn = _connect(path)
    conn.executescript(
        """
        CREATE TABLE jpi_adoption_records (
            id INTEGER PRIMARY KEY,
            program_name_raw TEXT,
            company_name_raw TEXT,
            prefecture TEXT,
            amount_granted_yen INTEGER,
            source_url TEXT,
            program_id TEXT,
            program_id_match_method TEXT,
            program_id_match_score REAL
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO jpi_adoption_records(
            id, program_name_raw, company_name_raw, prefecture, amount_granted_yen,
            source_url, program_id, program_id_match_method, program_id_match_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                "IT導入補助金 2023 後期",
                "A社",
                None,
                1_000_000,
                "https://example.invalid/1",
                None,
                "unknown",
                0.0,
            ),
            (
                2,
                "中小企業設備導入補助事業",
                "B社",
                "東京都",
                2_000_000,
                "https://example.invalid/2",
                None,
                "unknown",
                0.0,
            ),
            (
                3,
                "",
                "blank",
                None,
                None,
                "https://example.invalid/3",
                None,
                "unknown",
                0.0,
            ),
            (
                4,
                "ものづくり補助金",
                "matched",
                None,
                3_000_000,
                "https://example.invalid/4",
                "prog-mono",
                "exact_alias",
                1.0,
            ),
        ],
    )
    conn.commit()
    return conn


def _build_program_db(path: Path) -> sqlite3.Connection:
    conn = _connect(path)
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            aliases_json TEXT,
            prefecture TEXT,
            tier TEXT,
            excluded INTEGER DEFAULT 0
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO programs(
            unified_id, primary_name, aliases_json, prefecture, tier, excluded
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "prog-it",
                "IT導入補助金",
                json.dumps(["IT補助金"], ensure_ascii=False),
                None,
                "B",
                0,
            ),
            ("prog-equipment", "中小企業設備導入補助金", None, "東京都", "A", 0),
            ("prog-mono", "ものづくり補助金", None, None, "S", 0),
            ("prog-excluded", "IT導入補助金2023後期", None, None, "A", 1),
        ],
    )
    conn.commit()
    return conn


def test_strategy_variants_cover_b7_normalization_cases() -> None:
    variants = gaps.generate_strategy_variants("IT導入補助金 2025 (デジタル化・AI導入補助金)")
    by_strategy = {
        strategy: {variant.variant for variant in variants if variant.strategy == strategy}
        for strategy in {variant.strategy for variant in variants}
    }

    assert "IT導入補助金" in by_strategy["combined_aggressive"]
    assert "デジタル化・AI導入補助金" in by_strategy["strip_parentheses"]
    assert gaps._without_punctuation("デジタル化・AI導入補助金") == gaps._without_punctuation(
        "デジタル化AI導入補助金"
    )

    suffix_variants = gaps.generate_strategy_variants("中小企業設備導入補助事業")
    assert any(
        variant.strategy == "grant_suffix_variants" and variant.variant == "中小企業設備導入補助金"
        for variant in suffix_variants
    )


def test_collect_report_is_read_only_and_recommends_aliases(tmp_path: Path) -> None:
    adoption_path = tmp_path / "adoption.db"
    program_path = tmp_path / "programs.db"
    adoption_conn = _build_adoption_db(adoption_path)
    program_conn = _build_program_db(program_path)

    report = gaps.collect_adoption_program_join_gaps(
        adoption_conn,
        program_conn,
        sample_limit=10,
    )

    assert report["report_only"] is True
    assert report["mutates_db"] is False
    assert report["schema"]["adoption"]["table"] == "jpi_adoption_records"
    assert report["schema"]["program"]["table"] == "programs"
    assert report["totals"]["adoption_rows"] == 4
    assert report["totals"]["current_unmatched_rows"] == 3
    assert report["totals"]["current_unmatched_named_rows"] == 2
    assert report["totals"]["current_unmatched_blank_name_rows"] == 1
    assert (
        report["candidate_counts_by_strategy"]["strip_fiscal_year_round"]["rows_with_candidates"]
        == 1
    )
    assert (
        report["candidate_counts_by_strategy"]["grant_suffix_variants"]["rows_with_candidates"] == 1
    )

    recommendations = report["recommended_alias_additions"]
    assert {
        (row["alias"], row["recommended_program_id"], row["review_required"])
        for row in recommendations
    } == {
        ("IT導入補助金 2023 後期", "prog-it", False),
        ("中小企業設備導入補助事業", "prog-equipment", False),
    }

    still_unmatched = adoption_conn.execute(
        "SELECT COUNT(*) FROM jpi_adoption_records WHERE program_id IS NULL"
    ).fetchone()[0]
    assert still_unmatched == 3


def test_program_schema_prefers_nonempty_jpi_programs_table(tmp_path: Path) -> None:
    db_path = tmp_path / "mixed_programs.db"
    conn = _connect(db_path)
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL
        );
        CREATE TABLE jpi_programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            aliases_json TEXT,
            tier TEXT,
            excluded INTEGER DEFAULT 0
        );
        INSERT INTO jpi_programs(unified_id, primary_name, tier, excluded)
        VALUES ('prog-1', 'IT導入補助金', 'B', 0);
        """
    )

    schema = gaps.inspect_program_schema(conn)

    assert schema.table == "jpi_programs"


def test_write_json_and_csv_reports(tmp_path: Path) -> None:
    report = {
        "totals": {"current_unmatched_rows": 2},
        "recommended_alias_additions": [
            {
                "alias": "IT導入補助金 2023 後期",
                "unmatched_rows": 10,
                "prefecture": None,
                "recommended_program_id": "prog-it",
                "recommended_primary_name": "IT導入補助金",
                "matched_surface": "IT導入補助金",
                "strategy": "strip_fiscal_year_round",
                "variant": "IT導入補助金",
                "candidate_count": 1,
                "review_required": False,
                "reason": "test",
            }
        ],
    }
    json_path = tmp_path / "report.json"
    csv_path = tmp_path / "report.csv"

    gaps.write_report(report, json_path)
    gaps.write_recommendations_csv(report, csv_path)

    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "alias": "IT導入補助金 2023 後期",
            "unmatched_rows": "10",
            "prefecture": "",
            "recommended_program_id": "prog-it",
            "recommended_primary_name": "IT導入補助金",
            "matched_surface": "IT導入補助金",
            "strategy": "strip_fiscal_year_round",
            "variant": "IT導入補助金",
            "candidate_count": "1",
            "review_required": "False",
            "reason": "test",
        }
    ]
