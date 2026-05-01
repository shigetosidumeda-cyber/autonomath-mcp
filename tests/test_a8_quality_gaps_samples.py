from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import report_quality_known_gaps_samples as report  # noqa: E402


def _build_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            source_url TEXT,
            source_type TEXT DEFAULT 'primary',
            domain TEXT,
            last_verified TEXT,
            canonical_status TEXT DEFAULT 'active',
            license TEXT
        );
        CREATE TABLE jpi_programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            source_url TEXT,
            amount_max_man_yen REAL,
            application_window_json TEXT,
            enriched_json TEXT
        );
        CREATE TABLE am_acceptance_stat (
            program_entity_id TEXT NOT NULL,
            round_label TEXT NOT NULL,
            applied_count INTEGER,
            accepted_count INTEGER,
            acceptance_rate_pct REAL,
            source_url TEXT NOT NULL,
            source_fetched_at TEXT NOT NULL,
            PRIMARY KEY (program_entity_id, round_label)
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO am_source(
            id, source_url, source_type, domain, last_verified, canonical_status, license
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                "https://clean.example/source",
                "primary",
                "clean.example",
                "2026-04-30",
                "active",
                "gov_standard_v2.0",
            ),
            (
                2,
                "https://unknown.example/source",
                "primary",
                "unknown.example",
                "2026-04-30",
                "active",
                "unknown",
            ),
            (
                3,
                "https://unverified.example/source",
                "primary",
                "unverified.example",
                None,
                "active",
                "gov_standard_v2.0",
            ),
        ],
    )
    conn.executemany(
        """
        INSERT INTO jpi_programs(
            unified_id, primary_name, source_url, amount_max_man_yen,
            application_window_json, enriched_json
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "P-clean",
                "Clean Program",
                "https://clean.example/source",
                100,
                json.dumps({"end_date": "2026-06-30"}),
                json.dumps({"contacts": [{"email": "desk@clean.example"}]}),
            ),
            (
                "P-missing-source",
                "Missing Source Program",
                "https://missing.example/program",
                None,
                json.dumps({}),
                json.dumps({}),
            ),
            (
                "P-no-url",
                "No URL Program",
                None,
                None,
                json.dumps({}),
                json.dumps({}),
            ),
        ],
    )
    conn.executemany(
        """
        INSERT INTO am_acceptance_stat(
            program_entity_id, round_label, applied_count, accepted_count,
            acceptance_rate_pct, source_url, source_fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "program:clean",
                "1次",
                100,
                40,
                40.0,
                "https://clean.example/source",
                "2026-04-30",
            ),
            (
                "program:missing",
                "2次",
                50,
                10,
                20.0,
                "https://missing.example/stat",
                "2026-04-30",
            ),
        ],
    )
    conn.commit()
    conn.close()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_collect_samples_reports_counts_categories_and_report_only_status(tmp_path: Path) -> None:
    db_path = tmp_path / "fixtures.db"
    _build_db(db_path)

    with _connect(db_path) as conn:
        result = report.collect_quality_known_gaps_samples(
            conn,
            conn,
            program_limit=3,
            statistic_limit=2,
            source_limit=3,
            as_of="2026-05-01",
        )

    assert result["read_mode"] == {
        "sqlite_only": True,
        "network_fetch_performed": False,
        "llm_call_performed": False,
        "db_mutation_performed": False,
    }
    assert result["complete"] is False
    assert result["completion_status"]["A8"] == "report_only"
    assert result["sample_counts"] == {
        "program": 3,
        "statistic": 2,
        "source": 3,
        "total": 8,
    }
    assert result["gap_coverage"]["records_with_known_gaps"] == 5
    assert result["gap_coverage"]["gap_coverage_ratio"] == 0.625
    assert set(result["known_gap_categories"]) >= {
        "license_unknown",
        "missing_amount",
        "missing_contact",
        "missing_deadline",
        "missing_source_id",
        "source_unverified",
    }
    assert all(
        item["status"] == "pending_protected_integration" or item["status"] == "not_wired_here"
        for item in result["evidence_packet_integration_still_needs"]
    )


def test_source_samples_do_not_emit_program_required_fact_gaps(tmp_path: Path) -> None:
    db_path = tmp_path / "fixtures.db"
    _build_db(db_path)

    with _connect(db_path) as conn:
        result = report.collect_quality_known_gaps_samples(
            conn,
            conn,
            program_limit=0,
            statistic_limit=0,
            source_limit=3,
            as_of="2026-05-01",
        )

    source_samples = result["samples"]
    assert result["sample_counts"] == {
        "program": 0,
        "statistic": 0,
        "source": 3,
        "total": 3,
    }
    for sample in source_samples:
        assert sample["record_type"] == "source"
        assert "missing_deadline" not in sample["gap_codes"]
        assert "missing_amount" not in sample["gap_codes"]
        assert "missing_contact" not in sample["gap_codes"]


def test_main_writes_json_report_from_readonly_db(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "fixtures.db"
    output = tmp_path / "quality_known_gaps_samples.json"
    _build_db(db_path)

    exit_code = report.main(
        [
            "--autonomath-db",
            str(db_path),
            "--jpintel-db",
            str(db_path),
            "--output",
            str(output),
            "--program-limit",
            "1",
            "--statistic-limit",
            "1",
            "--source-limit",
            "1",
        ]
    )

    assert exit_code == 0
    assert output.exists()
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["inputs"]["autonomath_db"] == str(db_path)
    assert written["sample_counts"]["total"] == 3
    assert written["completion_status"]["complete"] is False
    stdout = capsys.readouterr().out
    assert "complete=False" in stdout
    assert f"output={output}" in stdout
