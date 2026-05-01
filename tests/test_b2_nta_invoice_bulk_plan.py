from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "etl" / "report_nta_invoice_bulk_plan.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("report_nta_invoice_bulk_plan", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_jpintel_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE invoice_registrants (
            invoice_registration_number TEXT PRIMARY KEY,
            houjin_bangou TEXT,
            normalized_name TEXT NOT NULL,
            address_normalized TEXT,
            prefecture TEXT,
            registered_date TEXT NOT NULL,
            revoked_date TEXT,
            expired_date TEXT,
            registrant_kind TEXT NOT NULL,
            trade_name TEXT,
            last_updated_nta TEXT,
            source_url TEXT NOT NULL,
            source_checksum TEXT,
            confidence REAL NOT NULL DEFAULT 0.98,
            fetched_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO invoice_registrants VALUES
            (
                'T1234567890123', '1234567890123', 'Alpha KK', '東京都千代田区',
                '東京都', '2023-10-01', NULL, NULL, 'corporation', NULL,
                '2026-04-23', 'https://www.invoice-kohyo.nta.go.jp/download/zenken',
                'abc', 0.98, '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z'
            ),
            (
                'T9999999999999', NULL, 'Private Shop', '大阪府大阪市',
                '大阪府', '2024-01-01', NULL, NULL, 'sole_proprietor', 'Shop',
                '2026-04-23', 'https://www.invoice-kohyo.nta.go.jp/download/zenken',
                'def', 0.98, '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z'
            );
        """
    )
    conn.commit()
    conn.close()


def _make_autonomath_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE jpi_invoice_registrants (
            invoice_registration_number TEXT PRIMARY KEY,
            houjin_bangou TEXT,
            normalized_name TEXT NOT NULL,
            address_normalized TEXT,
            prefecture TEXT,
            registered_date TEXT NOT NULL,
            revoked_date TEXT,
            expired_date TEXT,
            registrant_kind TEXT NOT NULL,
            trade_name TEXT,
            last_updated_nta TEXT,
            source_url TEXT NOT NULL,
            source_checksum TEXT,
            confidence REAL NOT NULL DEFAULT 0.98,
            fetched_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE am_entities (
            canonical_id TEXT PRIMARY KEY,
            record_kind TEXT NOT NULL
        );
        INSERT INTO jpi_invoice_registrants VALUES
            (
                'T1234567890123', '1234567890123', 'Alpha KK', '東京都千代田区',
                '東京都', '2023-10-01', NULL, NULL, 'corporation', NULL,
                '2026-04-23', 'https://www.invoice-kohyo.nta.go.jp/download/zenken',
                'abc', 0.98, '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z'
            ),
            (
                'T9999999999999', NULL, 'Private Shop', '大阪府大阪市',
                '大阪府', '2024-01-01', NULL, NULL, 'sole_proprietor', 'Shop',
                '2026-04-23', 'https://www.invoice-kohyo.nta.go.jp/download/zenken',
                'def', 0.98, '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z'
            );
        INSERT INTO am_entities VALUES
            ('invoice:T1234567890123', 'invoice_registrant'),
            ('invoice:T9999999999999', 'invoice_registrant');
        """
    )
    conn.commit()
    conn.close()


def _write_workflow(path: Path) -> None:
    path.write_text(
        """
name: nta-bulk-monthly
on:
  schedule:
    - cron: "0 18 1 * *"
  workflow_dispatch:
jobs:
  ingest:
    timeout-minutes: 120
    steps:
      - run: |
          flyctl ssh console -a autonomath-api -C \
            "/app/.venv/bin/python /app/scripts/cron/ingest_nta_invoice_bulk.py \
              --db /data/jpintel.db \
              --mode ${MODE} \
              --cache-dir /data/_cache/nta_invoice \
              --log-file /data/invoice_load_log.jsonl \
              --batch-size 10000"
concurrency:
  group: nta-bulk-monthly
""",
        encoding="utf-8",
    )


def test_build_report_counts_workflow_artifacts_and_string_commands(tmp_path: Path) -> None:
    mod = _load_module()
    jpintel_db = tmp_path / "jpintel.db"
    autonomath_db = tmp_path / "autonomath.db"
    workflow = tmp_path / "nta-bulk-monthly.yml"
    local_cache = tmp_path / "cache"
    prod_cache = tmp_path / "prod_cache"
    local_log = tmp_path / "invoice_load_log.jsonl"
    prod_log = tmp_path / "prod_invoice_load_log.jsonl"
    artifact_root = tmp_path / "artifacts"

    _make_jpintel_db(jpintel_db)
    _make_autonomath_db(autonomath_db)
    _write_workflow(workflow)
    local_cache.mkdir()
    (local_cache / "nta_1_csv.zip").write_bytes(b"cached")
    local_log.write_text(
        json.dumps({"rows_after": 2, "mode": "full"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    report = mod.build_report(
        jpintel_db=jpintel_db,
        autonomath_db=autonomath_db,
        workflow_path=workflow,
        local_cache_dir=local_cache,
        prod_cache_dir=prod_cache,
        local_load_log=local_log,
        prod_load_log=prod_log,
        artifact_root=artifact_root,
    )

    assert report["read_mode"] == {
        "sqlite_mode_ro": True,
        "workflow_text_only": True,
        "cache_metadata_only": True,
        "network_fetch_performed": False,
        "download_performed": False,
        "db_mutation_performed": False,
        "commands_are_strings_only": True,
    }
    assert report["completion_status"] == {
        "B2": "plan_only",
        "complete": False,
        "reason": "acquisition and reconcile commands are deferred strings only",
    }
    assert report["current_invoice_registrant_count"] == 2
    assert report["remaining_rows_estimate"] == 3_999_998
    assert report["local_counts"]["jpintel"]["counts"]["by_registrant_kind"] == {
        "corporation": 1,
        "sole_proprietor": 1,
    }
    assert report["local_counts"]["jpintel"]["counts"]["with_houjin_bangou"] == 1
    assert report["reconcile"]["count_match"] is True
    assert report["workflow_cron_status"]["monthly_full_cron_wired"] is True
    assert report["workflow_cron_status"]["daily_delta_cron_wired"] is False
    assert report["artifact_status"]["local_cache"]["file_count"] == 1
    assert report["artifact_status"]["local_load_log"]["latest_entry"]["rows_after"] == 2
    assert report["expected_artifacts"]["source_urls"]["full_index"] == (
        "https://www.invoice-kohyo.nta.go.jp/download/zenken"
    )

    all_commands = [cmd for group in report["commands"].values() for cmd in group]
    assert all(isinstance(cmd, str) for cmd in all_commands)
    assert any("ingest_nta_invoice_bulk.py" in cmd for cmd in all_commands)
    assert any("mode=ro" in cmd for cmd in all_commands)

    codes = {blocker["code"] for blocker in report["blockers"]}
    assert "full_snapshot:not_acquired" in codes
    assert "workflow:daily_delta_not_scheduled" in codes
    assert "privacy:takedown_path_required" in codes


def test_missing_inputs_fail_closed_without_touching_db(tmp_path: Path) -> None:
    mod = _load_module()
    report = mod.build_report(
        jpintel_db=tmp_path / "missing_jpintel.db",
        autonomath_db=tmp_path / "missing_autonomath.db",
        workflow_path=tmp_path / "missing_workflow.yml",
        local_cache_dir=tmp_path / "missing_cache",
        prod_cache_dir=tmp_path / "missing_prod_cache",
        local_load_log=tmp_path / "missing_log.jsonl",
        prod_load_log=tmp_path / "missing_prod_log.jsonl",
        artifact_root=tmp_path / "artifacts",
    )

    codes = {blocker["code"] for blocker in report["blockers"]}
    assert "jpintel_db:missing" in codes
    assert "workflow:missing" in codes
    assert report["local_counts"]["jpintel"]["exists"] is False
    assert report["report_counts"]["fail_closed_blocker_count"] >= 3


def test_cli_writes_owned_json_report(tmp_path: Path) -> None:
    mod = _load_module()
    jpintel_db = tmp_path / "jpintel.db"
    autonomath_db = tmp_path / "autonomath.db"
    workflow = tmp_path / "nta-bulk-monthly.yml"
    output = tmp_path / "nta_invoice_bulk_plan.json"
    _make_jpintel_db(jpintel_db)
    _make_autonomath_db(autonomath_db)
    _write_workflow(workflow)

    rc = mod.main(
        [
            "--jpintel-db",
            str(jpintel_db),
            "--autonomath-db",
            str(autonomath_db),
            "--workflow",
            str(workflow),
            "--local-cache-dir",
            str(tmp_path / "cache"),
            "--prod-cache-dir",
            str(tmp_path / "prod_cache"),
            "--local-load-log",
            str(tmp_path / "invoice_load_log.jsonl"),
            "--prod-load-log",
            str(tmp_path / "prod_invoice_load_log.jsonl"),
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["current_invoice_registrant_count"] == 2
    assert payload["completion_status"]["complete"] is False
