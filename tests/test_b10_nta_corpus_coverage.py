from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import report_nta_corpus_coverage as coverage  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE nta_shitsugi (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL,
            category TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            related_law TEXT,
            source_url TEXT,
            license TEXT,
            ingested_at TEXT NOT NULL
        );
        CREATE TABLE nta_bunsho_kaitou (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL,
            category TEXT NOT NULL,
            response_date TEXT,
            request_summary TEXT,
            answer TEXT,
            source_url TEXT,
            license TEXT,
            ingested_at TEXT NOT NULL
        );
        CREATE TABLE nta_saiketsu (
            id INTEGER PRIMARY KEY,
            volume_no INTEGER NOT NULL,
            case_no TEXT NOT NULL,
            tax_type TEXT,
            title TEXT,
            source_url TEXT,
            license TEXT,
            ingested_at TEXT NOT NULL
        );
        CREATE TABLE nta_tsutatsu_index (
            id INTEGER PRIMARY KEY,
            code TEXT NOT NULL,
            law_canonical_id TEXT NOT NULL,
            article_number TEXT NOT NULL,
            title TEXT,
            source_url TEXT,
            refreshed_at TEXT NOT NULL
        );
        """
    )
    return conn


def test_collect_coverage_reports_counts_completeness_and_duplicates() -> None:
    conn = _build_db()
    conn.executemany(
        """
        INSERT INTO nta_shitsugi(
            id, slug, category, question, answer, source_url, license, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "shotoku-1", "shotoku", "q", "a", "https://nta.example/shared", "gov", "now"),
            (2, "shotoku-2", "shotoku", "q", "a", "", "gov", "now"),
            (3, "hojin-1", "hojin", "q", "a", "https://nta.example/hojin", "", "now"),
        ],
    )
    conn.execute(
        """
        INSERT INTO nta_bunsho_kaitou(
            id, slug, category, request_summary, answer, source_url, license, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (1, "bunsho-1", "shohi", "req", "ans", "https://nta.example/shared", "gov", "now"),
    )
    conn.executemany(
        """
        INSERT INTO nta_saiketsu(
            id, volume_no, case_no, tax_type, title, source_url, license, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, 1, "01", "所得税", "t", "https://kfs.example/1", "gov", "now"),
            (2, 1, "02", "法人税", "t", "https://kfs.example/dup", "gov", "now"),
            (3, 1, "03", "法人税", "t", "https://kfs.example/dup", "gov", "now"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO nta_tsutatsu_index(
            id, code, law_canonical_id, article_number, title, source_url, refreshed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "法基通-1", "law:hojin-zei-tsutatsu", "1", "t", "https://law.example/1", "now"),
            (2, "所基通-1", "law:shotoku-zei-tsutatsu", "1", "t", "https://law.example/2", "now"),
        ],
    )

    report = coverage.collect_nta_corpus_coverage(conn)

    assert report["totals"] == {
        "rows": 9,
        "source_url_missing": 1,
        "license_missing": 1,
    }
    shitsugi = report["tables"]["nta_shitsugi"]
    assert shitsugi["metadata_completeness"]["source_url_present"] == 2
    assert shitsugi["metadata_completeness"]["license_present"] == 2
    assert shitsugi["counts_by_dimension"] == [
        {"category": "shotoku", "rows": 2},
        {"category": "hojin", "rows": 1},
    ]
    tsutatsu = report["tables"]["nta_tsutatsu_index"]["metadata_completeness"]
    assert tsutatsu["license_column_present"] is False
    assert tsutatsu["license_present"] is None
    assert report["duplicates"]["within_table_count"] == 1
    assert report["duplicates"]["across_table_count"] == 1
    assert report["suggested_next_target"] == {
        "target": "nta_bunsho_kaitou:shohi",
        "reason": "lowest populated category/tax bucket has 1 rows",
        "action": "expand_lowest_coverage_bucket",
    }


def test_suggested_target_falls_back_to_lowest_bucket_when_metadata_clean() -> None:
    conn = _build_db()
    conn.executemany(
        """
        INSERT INTO nta_shitsugi(
            id, slug, category, question, answer, source_url, license, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "a", "shotoku", "q", "a", "https://nta.example/a", "gov", "now"),
            (2, "b", "shotoku", "q", "a", "https://nta.example/b", "gov", "now"),
        ],
    )
    conn.execute(
        """
        INSERT INTO nta_bunsho_kaitou(
            id, slug, category, request_summary, answer, source_url, license, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (1, "c", "shohi", "req", "ans", "https://nta.example/c", "gov", "now"),
    )

    report = coverage.collect_nta_corpus_coverage(conn)

    assert report["suggested_next_target"] == {
        "target": "nta_bunsho_kaitou:shohi",
        "reason": "lowest populated category/tax bucket has 1 rows",
        "action": "expand_lowest_coverage_bucket",
    }


def test_write_report_materializes_json(tmp_path: Path) -> None:
    output = tmp_path / "nta_report.json"
    report = {"tables": {}, "totals": {"rows": 0}}

    coverage.write_report(report, output)

    assert json.loads(output.read_text(encoding="utf-8")) == report
