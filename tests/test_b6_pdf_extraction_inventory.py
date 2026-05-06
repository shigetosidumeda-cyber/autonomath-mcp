from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import report_pdf_extraction_inventory as inventory  # noqa: E402


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _build_fixture_db(path: Path) -> sqlite3.Connection:
    conn = _connect(path)
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT,
            authority_name TEXT,
            program_kind TEXT,
            source_url TEXT,
            official_url TEXT,
            source_mentions_json TEXT
        );
        CREATE TABLE program_documents (
            id INTEGER PRIMARY KEY,
            program_name TEXT,
            form_name TEXT,
            form_type TEXT,
            form_format TEXT,
            form_url_direct TEXT,
            completion_example_url TEXT,
            source_url TEXT,
            source_excerpt TEXT
        );
        CREATE TABLE new_program_candidates (
            id INTEGER PRIMARY KEY,
            candidate_name TEXT,
            mentioned_in TEXT,
            ministry TEXT,
            program_kind_hint TEXT,
            policy_background_excerpt TEXT,
            source_url TEXT,
            source_pdf_page TEXT
        );
        """
    )
    return conn


def test_collect_inventory_counts_sources_profiles_local_files_and_shards(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "repo"
    (local_root / "fixtures").mkdir(parents=True)
    local_source_pdf = local_root / "fixtures" / "local_outline.pdf"
    basename_match_pdf = local_root / "koubo.pdf"
    local_source_pdf.write_bytes(b"%PDF-1.4\n")
    basename_match_pdf.write_bytes(b"%PDF-1.4\n")

    db_path = tmp_path / "jpintel.db"
    conn = _build_fixture_db(db_path)
    conn.executemany(
        """
        INSERT INTO programs(
            unified_id, primary_name, authority_name, program_kind,
            source_url, official_url, source_mentions_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "UNI-1",
                "Energy subsidy",
                "City A",
                "subsidy",
                "https://alpha.example/koubo.pdf",
                "https://alpha.example/index.html",
                json.dumps(["https://beta.example/guide.pdf"]),
            ),
            (
                "UNI-2",
                "Duplicate subsidy",
                "City A",
                "subsidy",
                "https://alpha.example/koubo.pdf",
                None,
                None,
            ),
            (
                "UNI-3",
                "Local subsidy",
                "City B",
                "subsidy",
                "fixtures/local_outline.pdf",
                None,
                None,
            ),
            (
                "UNI-4",
                "HTML only",
                "City C",
                "subsidy",
                "https://html.example/detail.html",
                None,
                None,
            ),
        ],
    )
    conn.execute(
        """
        INSERT INTO program_documents(
            id, program_name, form_name, form_type, form_format,
            form_url_direct, completion_example_url, source_url, source_excerpt
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            "Documented program",
            "application form",
            "required",
            "pdf",
            "https://forms.example/apply.pdf",
            None,
            "https://forms.example/index.html",
            "form fixture",
        ),
    )
    conn.execute(
        """
        INSERT INTO new_program_candidates(
            id, candidate_name, mentioned_in, ministry, program_kind_hint,
            policy_background_excerpt, source_url, source_pdf_page
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            "Future subsidy",
            "budget",
            "METI",
            "subsidy",
            "budget summary",
            "https://gamma.example/budget.pdf",
            "p.3",
        ),
    )
    conn.commit()

    report = inventory.collect_pdf_extraction_inventory(
        conn,
        db_path=db_path,
        local_root=local_root,
        analysis_dir=tmp_path,
        csv_output=tmp_path / "inventory.csv",
        shard_count=2,
        sample_limit=10,
        python_runner="python",
        batch_script="scripts/etl/run_program_pdf_extraction_batch.py",
        temp_db_dir=tmp_path,
        cache_dir=tmp_path / "cache",
    )

    assert report["report_only"] is True
    assert report["mutates_db"] is False
    assert report["network_fetch_performed"] is False
    assert report["external_api_calls"] is False

    assert report["totals"]["candidate_pdf_rows"] == 6
    assert report["totals"]["unique_pdf_sources"] == 5
    assert report["totals"]["remote_pdf_candidate_rows"] == 5
    assert report["totals"]["unique_remote_pdf_sources"] == 4
    assert report["totals"]["local_pdf_candidate_rows"] == 1
    assert report["totals"]["local_pdf_candidate_rows_existing"] == 1
    assert report["totals"]["local_pdf_files_seen_under_root"] == 2
    assert report["totals"]["local_pdf_files_relevant_by_reference_or_basename"] == 2
    assert report["totals"]["batch_processable_candidate_rows"] == 2
    assert report["totals"]["batch_processable_unique_sources"] == 1

    assert report["profile_counts"] == {
        "application_form_candidate": 1,
        "grant_env_content": 5,
    }
    assert report["likely_extractable_field_counts"]["deadline"] == 5
    assert report["likely_extractable_field_counts"]["required_docs"] == 6
    assert report["likely_extractable_field_counts"]["contact"] == 6

    domains = {row["domain"]: row for row in report["domains"]}
    assert domains["alpha.example"]["candidate_rows"] == 2
    assert domains["alpha.example"]["unique_source_count"] == 1
    assert domains["alpha.example"]["batch_processable_rows"] == 2
    assert domains["beta.example"]["candidate_rows"] == 1
    assert domains["forms.example"]["candidate_rows"] == 1
    assert domains["gamma.example"]["candidate_rows"] == 1

    shards = report["shard_plan"]["shards"]
    assert report["shard_plan"]["domain_exclusive"] is True
    assert report["shard_plan"]["shard_count"] == 2
    seen_domains = [domain for shard in shards for domain in shard["domains"]]
    assert sorted(seen_domains) == [
        "alpha.example",
        "beta.example",
        "forms.example",
        "gamma.example",
    ]
    assert len(seen_domains) == len(set(seen_domains))
    assert all("run_program_pdf_extraction_batch.py" in shard["run_command"] for shard in shards)
    assert all(str(tmp_path / "inventory.csv") in shard["run_command"] for shard in shards)

    local_rows = [row for row in report["candidate_rows"] if row["ref_type"] == "local_file"]
    assert len(local_rows) == 1
    assert local_rows[0]["local_file_exists"] == "true"
    assert str(local_source_pdf) in local_rows[0]["matched_local_paths"]

    assert (
        conn.execute("SELECT COUNT(*) FROM programs").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM program_documents").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM new_program_candidates").fetchone()[0],
    ) == (4, 1, 1)
    assert report["completion_status"]["complete"] is False
    assert report["completion_status"]["B6"] == "inventory_and_plan_only"


def test_write_json_and_csv_reports_round_trip(tmp_path: Path) -> None:
    local_root = tmp_path / "repo"
    local_root.mkdir()
    db_path = tmp_path / "jpintel.db"
    conn = _build_fixture_db(db_path)
    conn.execute(
        """
        INSERT INTO programs(
            unified_id, primary_name, authority_name, program_kind,
            source_url, official_url, source_mentions_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "UNI-1",
            "Energy subsidy",
            "City A",
            "subsidy",
            "https://alpha.example/koubo.pdf",
            None,
            None,
        ),
    )
    conn.commit()
    report = inventory.collect_pdf_extraction_inventory(
        conn,
        db_path=db_path,
        local_root=local_root,
        analysis_dir=tmp_path,
        csv_output=tmp_path / "inventory.csv",
        shard_count=1,
        python_runner="python",
        temp_db_dir=tmp_path,
    )

    json_path = tmp_path / "inventory.json"
    csv_path = tmp_path / "inventory.csv"
    inventory.write_json_report(report, json_path)
    inventory.write_csv_report(report, csv_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["totals"]["candidate_pdf_rows"] == 1
    assert payload["shard_plan"]["shards"][0]["batch_processable_rows"] == 1

    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "shard_id": "1",
            "source_table": "programs",
            "source_column": "source_url",
            "source_kind": "program",
            "program_id": "UNI-1",
            "program_name": "Energy subsidy",
            "source_ref": "https://alpha.example/koubo.pdf",
            "normalized_ref": "https://alpha.example/koubo.pdf",
            "ref_type": "remote_url",
            "domain": "alpha.example",
            "profile_hint": "grant_env_content",
            "parser_supported": "true",
            "likely_fields": "deadline,subsidy_rate,required_docs,contact,max_amount",
            "local_file_exists": "false",
            "local_file_path": "",
            "matched_local_paths": "[]",
            "batch_processable": "true",
        }
    ]


def test_connect_readonly_sets_sqlite_query_only(tmp_path: Path) -> None:
    db_path = tmp_path / "jpintel.db"
    conn = _build_fixture_db(db_path)
    conn.commit()
    conn.close()

    with inventory._connect_readonly(db_path) as readonly:  # noqa: SLF001
        assert inventory.discover_source_schemas(readonly)
        with pytest.raises(sqlite3.OperationalError):
            readonly.execute(
                """
                INSERT INTO programs(
                    unified_id, primary_name, source_url
                ) VALUES ('UNI-X', 'blocked', 'https://x.example/a.pdf')
                """
            )
