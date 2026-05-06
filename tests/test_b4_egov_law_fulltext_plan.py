from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "etl" / "report_egov_law_fulltext_plan.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("egov_law_fulltext_plan", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_loader_files(tmp_path: Path) -> tuple[Path, Path]:
    driver = tmp_path / "incremental_law_fulltext.py"
    workflow = tmp_path / "incremental-law-load.yml"
    driver.write_text(
        "\n".join(
            [
                "_DEFAULT_LIMIT = 600",
                "_RATE_SLEEP_SEC = 1.0",
            ]
        ),
        encoding="utf-8",
    )
    workflow.write_text(
        "\n".join(
            [
                "on:",
                "  workflow_dispatch:",
                "    inputs:",
                "      limit:",
                '        default: "600"',
                "jobs:",
                "  load:",
                "    timeout-minutes: 90",
                "    steps:",
                "      - run: |",
                '          LIMIT="${INPUT_LIMIT:-600}"',
            ]
        ),
        encoding="utf-8",
    )
    return driver, workflow


def _schema_snapshot(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    snapshot = {
        name: int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
        for (name,) in tables
    }
    conn.close()
    return snapshot


def _make_laws_db_with_body_text(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE laws (
            unified_id TEXT PRIMARY KEY,
            law_title TEXT NOT NULL,
            law_type TEXT,
            revision_status TEXT,
            ministry TEXT,
            body_text TEXT,
            source_url TEXT,
            full_text_url TEXT,
            source_checksum TEXT,
            fetched_at TEXT,
            updated_at TEXT
        );
        INSERT INTO laws VALUES
            (
                'LAW-0000000001',
                'Act One',
                'act',
                'current',
                'METI',
                'body',
                'https://laws.e-gov.go.jp/law/001',
                'https://laws.e-gov.go.jp/law/001',
                'sha1',
                '2026-05-01T00:00:00+00:00',
                '2026-05-01T00:00:00+00:00'
            ),
            (
                'LAW-0000000002',
                'Act Two',
                'act',
                'current',
                'METI',
                '   ',
                'https://example.test/law/002',
                '',
                '',
                '2026-05-01T00:00:00+00:00',
                '2026-05-01T00:00:00+00:00'
            ),
            (
                'LAW-0000000003',
                'Order Three',
                'cabinet_order',
                'repealed',
                'MHLW',
                NULL,
                '',
                '',
                NULL,
                '',
                ''
            ),
            (
                'LAW-0000000004',
                'Rule Four',
                'rule',
                'current',
                'MHLW',
                'body four',
                'https://elaws.e-gov.go.jp/document?lawid=004',
                'https://elaws.e-gov.go.jp/document?lawid=004',
                'sha4',
                '2026-05-01T00:00:00+00:00',
                '2026-05-01T00:00:00+00:00'
            );
        """
    )
    conn.commit()
    conn.close()


def test_build_report_counts_body_text_domains_and_batches(tmp_path: Path) -> None:
    mod = _load_module()
    db = tmp_path / "jpintel.db"
    output = tmp_path / "plan.json"
    driver, workflow = _write_loader_files(tmp_path)
    _make_laws_db_with_body_text(db)

    report = mod.build_report(
        db_path=db,
        driver_path=driver,
        workflow_path=workflow,
        output_path=output,
        acceptance_target=3,
    )

    assert report["read_mode"] == {
        "sqlite_only": True,
        "local_incremental_script_read": True,
        "local_incremental_workflow_read": True,
        "network_fetch_performed": False,
        "download_performed": False,
        "db_mutation_performed": False,
        "commands_are_strings_only": True,
    }
    assert report["completion_status"] == {"B4": "plan_only", "complete": False}
    assert report["incremental_loader"]["effective_batch_limit"] == 600
    assert report["incremental_loader"]["default_limit_consistent"] is True

    coverage = report["law_coverage"]
    assert coverage["total_laws"] == 4
    assert coverage["body_text"] == {
        "column_present": True,
        "present": 2,
        "missing": 2,
        "present_pct": 50.0,
        "missing_pct": 50.0,
    }
    assert coverage["metadata_completeness"]["source_url"]["present"] == 3
    assert coverage["metadata_completeness"]["source_url"]["official_egov_rows"] == 2
    assert {row["domain"]: row["rows"] for row in coverage["source_domains"]} == {
        "laws.e-gov.go.jp": 1,
        "elaws.e-gov.go.jp": 1,
        "example.test": 1,
    }

    estimate = report["batch_estimate"]
    assert estimate["batch_limit"] == 600
    assert estimate["body_text_needed_for_acceptance"] == 1
    assert estimate["batches_to_acceptance"] == 1
    assert estimate["batches_to_saturate_current_laws"] == 1

    assert "COUNT(*) >= 3" in report["acceptance"]["threshold_query"]
    all_commands = [cmd for group in report["commands"].values() for cmd in group]
    assert all(isinstance(cmd, str) for cmd in all_commands)
    assert any("incremental_law_fulltext.py" in cmd for cmd in all_commands)
    assert any("laws_with_body_text" in cmd for cmd in all_commands)


def test_missing_body_text_column_is_reported_without_mutating_db(tmp_path: Path) -> None:
    mod = _load_module()
    db = tmp_path / "jpintel.db"
    output = tmp_path / "plan.json"
    driver, workflow = _write_loader_files(tmp_path)
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE laws (
            unified_id TEXT PRIMARY KEY,
            law_title TEXT NOT NULL,
            source_url TEXT NOT NULL,
            full_text_url TEXT
        );
        INSERT INTO laws VALUES
            ('LAW-0000000001', 'Act One', 'https://laws.e-gov.go.jp/law/001', NULL),
            ('LAW-0000000002', 'Act Two', 'https://laws.e-gov.go.jp/law/002', NULL);
        """
    )
    conn.commit()
    conn.close()
    before = _schema_snapshot(db)

    report = mod.build_report(
        db_path=db,
        driver_path=driver,
        workflow_path=workflow,
        output_path=output,
        acceptance_target=3,
    )

    assert _schema_snapshot(db) == before
    assert report["law_coverage"]["body_text"] == {
        "column_present": False,
        "present": 0,
        "missing": 2,
        "present_pct": 0.0,
        "missing_pct": 100.0,
    }
    assert "laws.body_text:missing_column" in {gap["code"] for gap in report["readiness_gaps"]}
    assert report["acceptance"]["current_schema_column_present"] is False


def test_cli_writes_json_report(tmp_path: Path, capsys) -> None:
    mod = _load_module()
    db = tmp_path / "jpintel.db"
    output = tmp_path / "plan.json"
    driver, workflow = _write_loader_files(tmp_path)
    _make_laws_db_with_body_text(db)

    rc = mod.main(
        [
            "--db",
            str(db),
            "--driver",
            str(driver),
            "--workflow",
            str(workflow),
            "--output",
            str(output),
            "--acceptance-target",
            "3",
            "--write-report",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["law_coverage"]["total_laws"] == 4
    assert payload["batch_estimate"]["batches_to_acceptance"] == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["commands"]["acceptance"] == payload["commands"]["acceptance"]
