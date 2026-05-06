from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import report_jgrants_ingest_readiness as readiness  # noqa: E402


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_collect_report_from_api_style_schema_is_read_only(tmp_path: Path) -> None:
    db_path = tmp_path / "jpintel.db"
    conn = _connect(db_path)
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            authority_name TEXT,
            official_url TEXT,
            source_url TEXT,
            application_window_json TEXT,
            amount_max_man_yen REAL,
            amount_min_man_yen REAL,
            subsidy_rate REAL,
            subsidy_rate_text TEXT,
            enriched_json TEXT,
            source_mentions_json TEXT,
            source_fetched_at TEXT,
            source_checksum TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE programs_fts USING fts5(
            unified_id UNINDEXED,
            primary_name,
            aliases,
            enriched_text
        );
        CREATE TABLE program_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_name TEXT NOT NULL,
            form_name TEXT,
            form_url_direct TEXT,
            source_url TEXT,
            UNIQUE(program_name, form_url_direct)
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO programs(
            unified_id, primary_name, authority_name, official_url, source_url,
            application_window_json, amount_max_man_yen, amount_min_man_yen,
            subsidy_rate, subsidy_rate_text, enriched_json, source_mentions_json,
            source_fetched_at, source_checksum, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "UNI-jg-1",
                "JGrants Missing Detail",
                "Jグランツ",
                "https://www.jgrants-portal.go.jp/subsidy/subsidy",
                "https://www.jgrants-portal.go.jp/subsidy/subsidy",
                None,
                100.0,
                None,
                0.5,
                None,
                None,
                None,
                "2026-05-01T00:00:00+00:00",
                "abc",
                "2026-05-01T00:00:00+00:00",
            ),
            (
                "UNI-jg-2",
                "JGrants Enriched Detail",
                None,
                "https://example.go.jp/detail",
                "https://example.go.jp/detail",
                json.dumps({"end_date": "2026-06-01"}, ensure_ascii=False),
                None,
                None,
                None,
                "1/2",
                json.dumps(
                    {
                        "extraction": {
                            "contacts_v3": [{"office_name": "事務局"}],
                            "documents_v3": [{"name": "申請書", "required": True}],
                            "money": {"amount_detail": "上限100万円"},
                        }
                    },
                    ensure_ascii=False,
                ),
                json.dumps(["Jグランツ申請URL"], ensure_ascii=False),
                "2026-05-01T00:00:00+00:00",
                "def",
                "2026-05-01T00:00:00+00:00",
            ),
            (
                "UNI-other",
                "Other Program",
                None,
                "https://example.go.jp/other",
                "https://example.go.jp/other",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "2026-05-01T00:00:00+00:00",
            ),
        ],
    )
    conn.commit()

    report = readiness.collect_jgrants_ingest_readiness(conn, sample_limit=10)

    assert report["report_only"] is True
    assert report["mutates_db"] is False
    assert report["external_api_calls"] is False
    assert report["schema"]["program"]["table"] == "programs"
    assert report["schema"]["document"]["table"] == "program_documents"
    assert report["schema"]["source"] is None
    assert report["totals"]["program_rows"] == 3
    assert report["totals"]["jgrants_linked_program_rows"] == 2
    assert report["totals"]["jgrants_direct_url_rows"] == 1
    assert report["totals"]["jgrants_text_reference_rows"] == 2
    assert report["totals"]["jgrants_generic_subsidy_url_rows"] == 1

    missing = report["missing_structured_fields"]
    assert missing["deadline"] == {"present": 1, "missing": 1, "missing_pct": 50.0}
    assert missing["amount"] == {"present": 2, "missing": 0, "missing_pct": 0.0}
    assert missing["subsidy_rate"] == {"present": 2, "missing": 0, "missing_pct": 0.0}
    assert missing["contact"] == {"present": 1, "missing": 1, "missing_pct": 50.0}
    assert missing["required_docs"] == {"present": 1, "missing": 1, "missing_pct": 50.0}
    assert missing["license"] == {"present": 0, "missing": 2, "missing_pct": 100.0}
    assert "no source table with a license column" in " ".join(report["blockers"])
    assert any(plan["target"] == "programs" for plan in report["schema_safe_upsert_plan"])

    assert (
        conn.execute("SELECT COUNT(*) FROM programs WHERE unified_id LIKE 'UNI-jg-%'").fetchone()[0]
        == 2
    )


def test_collect_report_prefers_jpi_schema_and_uses_side_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "autonomath.db"
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
            authority_name TEXT,
            official_url TEXT,
            source_url TEXT,
            application_window_json TEXT,
            amount_max_man_yen REAL,
            subsidy_rate REAL,
            subsidy_rate_text TEXT,
            enriched_json TEXT,
            source_mentions_json TEXT,
            source_fetched_at TEXT,
            source_checksum TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE am_application_round (
            round_id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_entity_id TEXT NOT NULL,
            round_label TEXT NOT NULL,
            application_open_date TEXT,
            application_close_date TEXT,
            status TEXT,
            source_url TEXT,
            UNIQUE(program_entity_id, round_label)
        );
        CREATE TABLE jpi_program_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_name TEXT NOT NULL,
            form_name TEXT,
            form_url_direct TEXT,
            source_url TEXT,
            UNIQUE(program_name, form_url_direct)
        );
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url TEXT NOT NULL UNIQUE,
            domain TEXT,
            license TEXT
        );
        """
    )
    conn.execute(
        """
        INSERT INTO jpi_programs(
            unified_id, primary_name, authority_name, official_url, source_url,
            amount_max_man_yen, subsidy_rate, enriched_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "UNI-jg-side",
            "JGrants Side Table Detail",
            None,
            "https://www.jgrants-portal.go.jp/subsidy/subsidy",
            "https://www.jgrants-portal.go.jp/subsidy/subsidy",
            200.0,
            0.5,
            json.dumps({"contacts_v3": [{"office_name": "JGrants Helpdesk"}]}, ensure_ascii=False),
            "2026-05-01T00:00:00+00:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO am_application_round(
            program_entity_id, round_label, application_open_date,
            application_close_date, status, source_url
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "UNI-jg-side",
            "1次",
            "2026-05-01",
            "2026-06-01",
            "open",
            "https://www.jgrants-portal.go.jp/subsidy/subsidy",
        ),
    )
    conn.execute(
        """
        INSERT INTO jpi_program_documents(program_name, form_name, form_url_direct, source_url)
        VALUES (?, ?, ?, ?)
        """,
        (
            "JGrants Side Table Detail",
            "申請書",
            "https://www.jgrants-portal.go.jp/form.pdf",
            "https://www.jgrants-portal.go.jp/subsidy/subsidy",
        ),
    )
    conn.execute(
        "INSERT INTO am_source(source_url, domain, license) VALUES (?, ?, ?)",
        (
            "https://www.jgrants-portal.go.jp/subsidy/subsidy",
            "www.jgrants-portal.go.jp",
            "terms_unconfirmed_local_fixture",
        ),
    )
    conn.commit()

    report = readiness.collect_jgrants_ingest_readiness(conn, sample_limit=5)

    assert report["schema"]["program"]["table"] == "jpi_programs"
    assert report["schema"]["application_round"]["table"] == "am_application_round"
    assert report["schema"]["document"]["table"] == "jpi_program_documents"
    assert report["schema"]["source"]["table"] == "am_source"
    assert report["totals"]["jgrants_linked_program_rows"] == 1
    for field in readiness.REPORT_FIELDS:
        assert report["missing_structured_fields"][field]["missing"] == 0

    targets = {step["target"] for step in report["schema_safe_upsert_plan"]}
    assert {"jpi_programs", "am_application_round", "jpi_program_documents", "am_source"}.issubset(
        targets
    )


def test_write_report_round_trips_json(tmp_path: Path) -> None:
    report = {
        "report": "b8_jgrants_ingest_readiness",
        "totals": {"jgrants_linked_program_rows": 1},
        "blockers": ["local-only"],
    }
    output = tmp_path / "report.json"

    readiness.write_report(report, output)

    assert json.loads(output.read_text(encoding="utf-8")) == report
