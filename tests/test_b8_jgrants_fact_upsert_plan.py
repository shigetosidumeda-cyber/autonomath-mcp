from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import plan_jgrants_fact_upsert as planner  # noqa: E402


def _sample_detail() -> dict[str, object]:
    return {
        "subsidyId": "JG-2026-001",
        "detailUrl": "https://www.jgrants-portal.go.jp/subsidy/detail/JG-2026-001",
        "applicationEndDate": "2026-06-30",
        "subsidyMaxAmount": "100万円",
        "subsidyRate": "2分の1",
        "contact": {
            "organizationName": "経済産業省",
            "departmentName": "補助金室",
            "phoneNumber": "03-1234-5678",
            "emailAddress": "grants@example.go.jp",
        },
        "requiredDocuments": [{"documentName": "申請書"}, {"documentName": "事業計画書"}],
    }


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _build_program_db(path: Path, *, include_fact_tables: bool) -> sqlite3.Connection:
    conn = _connect(path)
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            authority_name TEXT,
            official_url TEXT,
            source_url TEXT,
            source_mentions_json TEXT,
            enriched_json TEXT,
            application_window_json TEXT,
            amount_max_man_yen REAL,
            amount_min_man_yen REAL,
            subsidy_rate REAL,
            subsidy_rate_text TEXT,
            updated_at TEXT NOT NULL
        );
        """
    )
    if include_fact_tables:
        conn.executescript(
            """
            CREATE TABLE am_source (
                id INTEGER PRIMARY KEY,
                source_url TEXT NOT NULL UNIQUE,
                domain TEXT,
                license TEXT
            );
            CREATE TABLE am_entity_facts (
                id INTEGER PRIMARY KEY,
                entity_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                field_value_text TEXT,
                field_value_json TEXT,
                field_value_numeric REAL,
                field_kind TEXT NOT NULL,
                source_url TEXT,
                source_id INTEGER
            );
            """
        )
    conn.execute(
        """
        INSERT INTO programs(
            unified_id, primary_name, authority_name, official_url, source_url,
            source_mentions_json, enriched_json, application_window_json,
            amount_max_man_yen, amount_min_man_yen, subsidy_rate, subsidy_rate_text,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "UNI-jgrants-1",
            "JGrants Fixture",
            "Jグランツ",
            "https://www.jgrants-portal.go.jp/subsidy/subsidy",
            "https://www.jgrants-portal.go.jp/subsidy/detail/JG-2026-001",
            json.dumps(["Jグランツ"], ensure_ascii=False),
            None,
            None,
            None,
            None,
            None,
            None,
            "2026-05-01T00:00:00+00:00",
        ),
    )
    if include_fact_tables:
        conn.execute(
            "INSERT INTO am_source(id, source_url, domain, license) VALUES (?, ?, ?, ?)",
            (
                7,
                "https://www.jgrants-portal.go.jp/subsidy/detail/JG-2026-001",
                "www.jgrants-portal.go.jp",
                "gov_standard_v2.0",
            ),
        )
        conn.execute(
            """
            INSERT INTO am_entity_facts(
                id, entity_id, field_name, field_value_text, field_value_numeric,
                field_kind, source_url, source_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                100,
                "UNI-jgrants-1",
                "program.amount_max_yen",
                "1000000",
                1_000_000,
                "amount",
                "https://www.jgrants-portal.go.jp/subsidy/detail/JG-2026-001",
                7,
            ),
        )
    conn.commit()
    return conn


def test_mapped_detail_to_fact_rows_adds_source_license_conflict_metadata() -> None:
    mapped = planner.normalize_detail_for_program(_sample_detail())
    metadata = planner.SourceMetadata(
        source_url="https://www.jgrants-portal.go.jp/subsidy/detail/JG-2026-001",
        mapped_license="gov_standard_v2.0",
        source_table="am_source",
        source_id=7,
        source_license="gov_standard_v2.0",
        status="resolved",
        blockers=(),
        required_steps=(),
    )

    rows = planner.mapped_detail_to_fact_rows(
        "UNI-jgrants-1",
        mapped,
        source_metadata=metadata,
    )
    by_field = {row["field_name"]: row for row in rows}

    assert set(by_field) == {
        "program.application_deadline",
        "program.amount_max_yen",
        "program.subsidy_rate",
        "program.contact",
        "program.required_documents",
        "program.jgrants_source_url",
        "program.jgrants_source_id",
    }
    assert by_field["program.amount_max_yen"]["field_value_numeric"] == 1_000_000
    assert by_field["program.subsidy_rate"]["field_value_text"] == "1/2"
    assert by_field["program.contact"]["source_id"] == 7
    assert by_field["program.contact"]["license"] == "gov_standard_v2.0"
    assert by_field["program.contact"]["conflict_policy"]["mode"] == "dry_run_no_write"
    assert all(row["idempotency_key"].startswith("b8:jgrants_fact:") for row in rows)

    rows_again = planner.mapped_detail_to_fact_rows(
        "UNI-jgrants-1",
        mapped,
        source_metadata=metadata,
    )
    assert [row["idempotency_key"] for row in rows_again] == [
        row["idempotency_key"] for row in rows
    ]


def test_build_plan_resolves_source_and_reports_existing_same_value(tmp_path: Path) -> None:
    db_path = tmp_path / "jpintel.db"
    conn = _build_program_db(db_path, include_fact_tables=True)

    before_count = conn.execute("SELECT COUNT(*) FROM am_entity_facts").fetchone()[0]
    plan = planner.build_jgrants_fact_upsert_plan(
        conn,
        detail_payloads={"UNI-jgrants-1": _sample_detail()},
        readiness_path=tmp_path / "missing-readiness.json",
        database_label=str(db_path),
    )
    after_count = conn.execute("SELECT COUNT(*) FROM am_entity_facts").fetchone()[0]

    assert before_count == after_count == 1
    assert plan["counts"]["jgrants_linked_programs"] == 1
    assert plan["counts"]["programs_with_detail_json"] == 1
    assert plan["counts"]["proposed_fact_rows"] == 7
    assert plan["counts"]["action_counts"]["noop_existing_same_value"] == 1
    assert plan["counts"]["action_counts"]["would_insert"] == 6
    assert plan["programs"][0]["proposed_fact_rows"][0]["source_metadata_status"] == "resolved"


def test_cli_writes_dry_run_plan_without_mutating_temp_db(tmp_path: Path) -> None:
    db_path = tmp_path / "jpintel.db"
    output = tmp_path / "plan.json"
    conn = _build_program_db(db_path, include_fact_tables=False)
    before_columns = [
        row["name"] for row in conn.execute("PRAGMA table_info(programs)").fetchall()
    ]
    before_rows = conn.execute("SELECT COUNT(*) FROM programs").fetchone()[0]
    conn.close()

    rc = planner.main(
        [
            "--db",
            str(db_path),
            "--readiness",
            str(tmp_path / "missing-readiness.json"),
            "--output",
            str(output),
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["dry_run"] is True
    assert payload["mutates_db"] is False
    assert payload["external_api_calls"] is False
    assert payload["counts"]["jgrants_linked_programs"] == 1
    assert payload["counts"]["programs_missing_detail_json"] == 1
    assert payload["counts"]["candidate_fact_slots_if_all_details_present"] == 7
    assert payload["counts"]["proposed_fact_rows"] == 0
    assert "am_entity_facts table is missing" in " ".join(payload["blockers"])

    conn = _connect(db_path)
    after_columns = [
        row["name"] for row in conn.execute("PRAGMA table_info(programs)").fetchall()
    ]
    after_rows = conn.execute("SELECT COUNT(*) FROM programs").fetchone()[0]
    conn.close()
    assert after_columns == before_columns
    assert after_rows == before_rows
