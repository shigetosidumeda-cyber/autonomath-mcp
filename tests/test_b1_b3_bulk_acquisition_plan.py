from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "etl" / "report_corporate_bulk_acquisition_plan.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("corporate_bulk_acquisition_plan", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_jpintel_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE houjin_master (
            houjin_bangou TEXT PRIMARY KEY,
            normalized_name TEXT NOT NULL,
            last_updated_nta TEXT
        );
        CREATE TABLE invoice_registrants (
            invoice_registration_number TEXT PRIMARY KEY,
            houjin_bangou TEXT,
            normalized_name TEXT NOT NULL,
            registrant_kind TEXT NOT NULL,
            last_updated_nta TEXT
        );
        INSERT INTO houjin_master VALUES
            ('1234567890123', 'Alpha KK', '2026-04-01'),
            ('2234567890123', 'Beta KK', NULL);
        INSERT INTO invoice_registrants VALUES
            ('T1234567890123', '1234567890123', 'Alpha KK', 'corporation', '2026-04-02'),
            ('T9999999999999', NULL, '(private)', 'sole_proprietor', '2026-04-02');
        """
    )
    conn.commit()
    conn.close()


def _make_autonomath_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE am_entities (
            canonical_id TEXT PRIMARY KEY,
            record_kind TEXT NOT NULL
        );
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL
        );
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            source_url TEXT
        );
        INSERT INTO am_entities VALUES
            ('houjin:1234567890123', 'corporate_entity'),
            ('program:test', 'program');
        INSERT INTO am_entity_facts(entity_id, field_name) VALUES
            ('houjin:1234567890123', 'corp.gbiz_update_date'),
            ('houjin:1234567890123', 'houjin_bangou');
        INSERT INTO am_source VALUES (1, 'https://info.gbiz.go.jp/');
        """
    )
    conn.commit()
    conn.close()


def _write_preflight(
    path: Path,
    *,
    ok: bool,
    issues: list[str],
    gbiz_jsonl: Path,
    invoice_cache: Path,
) -> None:
    payload = {
        "ok": ok,
        "generated_at": "2026-05-01T00:00:00+00:00",
        "issues": issues,
        "artifacts": {
            "gbiz_jsonl": {
                "path": str(gbiz_jsonl),
                "exists": gbiz_jsonl.exists(),
                "is_file": gbiz_jsonl.is_file(),
                "size_bytes": gbiz_jsonl.stat().st_size if gbiz_jsonl.exists() else 0,
            },
            "invoice_cache": {
                "path": str(invoice_cache),
                "exists": invoice_cache.exists(),
                "is_dir": invoice_cache.is_dir(),
                "file_count": 1 if invoice_cache.is_dir() else 0,
                "total_bytes": 4 if invoice_cache.is_dir() else 0,
            },
        },
        "disk": {
            "path": str(path.parent),
            "free_bytes": 5 * 1024 * 1024 * 1024,
            "total_bytes": 10 * 1024 * 1024 * 1024,
            "required_free_bytes": 2 * 1024 * 1024 * 1024,
            "ok": True,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_build_report_generates_official_sources_counts_and_string_commands(
    tmp_path: Path,
) -> None:
    mod = _load_module()
    jpintel_db = tmp_path / "jpintel.db"
    autonomath_db = tmp_path / "autonomath.db"
    preflight = tmp_path / "preflight.json"
    gbiz_jsonl = tmp_path / "gbiz_enrichment.jsonl"
    invoice_cache = tmp_path / "invoice_cache"
    artifact_root = tmp_path / "bulk"
    _make_jpintel_db(jpintel_db)
    _make_autonomath_db(autonomath_db)
    gbiz_jsonl.write_text('{"corporate_number":"1234567890123"}\n', encoding="utf-8")
    invoice_cache.mkdir()
    (invoice_cache / "nta_1_csv.zip").write_bytes(b"zip!")
    _write_preflight(
        preflight,
        ok=True,
        issues=[],
        gbiz_jsonl=gbiz_jsonl,
        invoice_cache=invoice_cache,
    )

    report = mod.build_report(
        jpintel_db=jpintel_db,
        autonomath_db=autonomath_db,
        preflight_path=preflight,
        gbiz_jsonl=tmp_path / "ignored.jsonl",
        invoice_cache_dir=tmp_path / "ignored_cache",
        artifact_root=artifact_root,
    )

    assert report["read_mode"] == {
        "sqlite_only": True,
        "preflight_json_only": True,
        "network_fetch_performed": False,
        "download_performed": False,
        "ingest_performed": False,
        "commands_are_strings_only": True,
    }
    assert report["completion_status"] == {
        "B1": "acquisition_plan_only",
        "B3": "acquisition_plan_only",
        "complete": False,
    }
    assert report["local_counts"]["jpintel"]["counts"]["houjin_master"] == 2
    assert report["local_counts"]["jpintel"]["counts"]["invoice_registrants"] == 2
    assert report["local_counts"]["jpintel"]["counts"]["invoice_registrants_by_kind"] == {
        "corporation": 1,
        "sole_proprietor": 1,
    }
    assert report["local_counts"]["autonomath"]["counts"]["corporate_entities"] == 1
    assert report["local_counts"]["autonomath"]["counts"]["gbiz_fact_rows"] == 1

    source_by_id = {source["source_id"]: source for source in report["sources"]}
    assert set(source_by_id) == {"B1_NTA_HOUJIN", "B1_GBIZINFO", "B3_NTA_INVOICE"}
    assert source_by_id["B1_NTA_HOUJIN"]["source_urls"] == [
        "https://www.houjin-bangou.nta.go.jp/",
        "https://www.houjin-bangou.nta.go.jp/download/",
    ]
    assert source_by_id["B3_NTA_INVOICE"]["source_domains"] == [
        "www.invoice-kohyo.nta.go.jp"
    ]
    assert source_by_id["B1_GBIZINFO"]["expected_local_artifacts"]["jsonl_snapshot"] == str(
        gbiz_jsonl
    )
    assert source_by_id["B3_NTA_INVOICE"]["disk_estimate"]["remaining_rows_estimate"] == (
        4_000_000 - 2
    )

    all_commands = [cmd for group in report["commands"].values() for cmd in group]
    assert all(isinstance(cmd, str) for cmd in all_commands)
    assert any("https://www.invoice-kohyo.nta.go.jp" in cmd for cmd in all_commands)
    assert report["report_counts"]["source_count"] == 3
    assert report["report_counts"]["command_count"] == len(all_commands)
    assert report["ok"] is False
    assert {
        blocker["code"] for blocker in report["blockers"]
    } >= {
        "license_review:B1_NTA_HOUJIN",
        "license_review:B1_GBIZINFO",
        "privacy_review:B3_NTA_INVOICE",
    }


def test_build_report_fail_closes_on_preflight_issues_and_missing_db(tmp_path: Path) -> None:
    mod = _load_module()
    jpintel_db = tmp_path / "missing_jpintel.db"
    autonomath_db = tmp_path / "missing_autonomath.db"
    preflight = tmp_path / "preflight.json"
    gbiz_jsonl = tmp_path / "missing_gbiz.jsonl"
    invoice_cache = tmp_path / "missing_cache"
    _write_preflight(
        preflight,
        ok=False,
        issues=["gbiz_jsonl:missing", "invoice_cache:missing_or_empty"],
        gbiz_jsonl=gbiz_jsonl,
        invoice_cache=invoice_cache,
    )

    report = mod.build_report(
        jpintel_db=jpintel_db,
        autonomath_db=autonomath_db,
        preflight_path=preflight,
        gbiz_jsonl=gbiz_jsonl,
        invoice_cache_dir=invoice_cache,
        artifact_root=tmp_path / "bulk",
    )

    codes = {blocker["code"] for blocker in report["blockers"]}
    assert "preflight:gbiz_jsonl:missing" in codes
    assert "preflight:invoice_cache:missing_or_empty" in codes
    assert "jpintel_db:missing" in codes
    assert "autonomath_db:missing" in codes
    assert report["ok"] is False
    assert report["report_counts"]["blocker_count"] == len(report["blockers"])


def test_cli_writes_report_even_when_blockers_exist(tmp_path: Path) -> None:
    mod = _load_module()
    jpintel_db = tmp_path / "jpintel.db"
    autonomath_db = tmp_path / "autonomath.db"
    preflight = tmp_path / "missing_preflight.json"
    output = tmp_path / "plan.json"
    _make_jpintel_db(jpintel_db)
    _make_autonomath_db(autonomath_db)

    rc = mod.main(
        [
            "--jpintel-db",
            str(jpintel_db),
            "--autonomath-db",
            str(autonomath_db),
            "--preflight",
            str(preflight),
            "--output",
            str(output),
            "--artifact-root",
            str(tmp_path / "bulk"),
        ]
    )

    assert rc == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["preflight"] == {"path": str(preflight), "present": False}
    assert "preflight:missing" in {blocker["code"] for blocker in payload["blockers"]}
    assert payload["read_mode"]["download_performed"] is False
