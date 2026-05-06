from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "etl" / "corporate_bulk_preflight.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("corporate_bulk_preflight", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_jpintel_db(path: Path, *, include_bulk_indexes: bool = True) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE houjin_master (
            houjin_bangou TEXT PRIMARY KEY,
            normalized_name TEXT NOT NULL,
            last_updated_nta TEXT
        );
        CREATE INDEX idx_houjin_name ON houjin_master(normalized_name);
        CREATE INDEX idx_houjin_prefecture ON houjin_master(normalized_name);
        CREATE INDEX idx_houjin_ctype ON houjin_master(normalized_name);
        CREATE INDEX idx_houjin_active ON houjin_master(normalized_name);

        CREATE TABLE invoice_registrants (
            invoice_registration_number TEXT PRIMARY KEY,
            houjin_bangou TEXT,
            normalized_name TEXT NOT NULL,
            registered_date TEXT NOT NULL,
            revoked_date TEXT,
            expired_date TEXT,
            registrant_kind TEXT NOT NULL,
            prefecture TEXT,
            last_updated_nta TEXT
        );
        CREATE INDEX idx_invoice_registrants_houjin ON invoice_registrants(houjin_bangou);
        CREATE INDEX idx_invoice_registrants_name ON invoice_registrants(normalized_name);
        CREATE INDEX idx_invoice_registrants_prefecture ON invoice_registrants(prefecture);
        CREATE INDEX idx_invoice_registrants_registered ON invoice_registrants(registered_date);
        CREATE INDEX idx_invoice_registrants_active
            ON invoice_registrants(revoked_date, expired_date);
        CREATE INDEX idx_invoice_registrants_kind ON invoice_registrants(registrant_kind);
        INSERT INTO houjin_master VALUES
            ('1234567890123', 'Alpha KK', '2026-04-01'),
            ('2234567890123', 'Beta KK', NULL);
        INSERT INTO invoice_registrants VALUES
            (
                'T1234567890123',
                '1234567890123',
                'Alpha KK',
                '2023-10-01',
                NULL,
                NULL,
                'corporation',
                'Tokyo',
                '2026-04-02'
            );
        """
    )
    if include_bulk_indexes:
        conn.executescript(
            """
            CREATE INDEX idx_invoice_registrants_houjin_registered
                ON invoice_registrants(houjin_bangou, registered_date DESC);
            CREATE INDEX idx_invoice_registrants_prefecture_registered
                ON invoice_registrants(prefecture, registered_date DESC);
            CREATE INDEX idx_invoice_registrants_last_updated
                ON invoice_registrants(last_updated_nta);
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
            record_kind TEXT NOT NULL,
            primary_name TEXT,
            fetched_at TEXT
        );
        CREATE INDEX idx_am_entities_kind ON am_entities(record_kind);
        CREATE INDEX ix_am_entities_kind_fetched ON am_entities(record_kind, fetched_at);

        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            source_id INTEGER
        );
        CREATE INDEX idx_am_facts_entity ON am_entity_facts(entity_id);
        CREATE INDEX idx_am_facts_field ON am_entity_facts(field_name);
        CREATE INDEX idx_am_efacts_source ON am_entity_facts(source_id);

        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            source_key TEXT,
            license TEXT
        );
        CREATE INDEX idx_am_source_license ON am_source(license);

        INSERT INTO am_entities VALUES
            ('houjin:1234567890123', 'corporate_entity', 'Alpha KK', '2026-04-01'),
            ('program:test', 'program', 'Program', '2026-04-01');
        INSERT INTO am_entity_facts(entity_id, field_name, source_id) VALUES
            ('houjin:1234567890123', 'corp.gbiz_update_date', 1),
            ('houjin:1234567890123', 'houjin_bangou', 1);
        INSERT INTO am_source VALUES (1, 'https://info.gbiz.go.jp/', 'cc_by_4.0');
        """
    )
    conn.commit()
    conn.close()


def test_build_report_passes_with_required_local_state(tmp_path: Path) -> None:
    mod = _load_module()
    jpintel_db = tmp_path / "jpintel.db"
    autonomath_db = tmp_path / "autonomath.db"
    gbiz_jsonl = tmp_path / "gbiz_enrichment.jsonl"
    invoice_cache = tmp_path / "invoice_cache"
    _make_jpintel_db(jpintel_db)
    _make_autonomath_db(autonomath_db)
    gbiz_jsonl.write_text('{"corporate_number":"1234567890123"}\n', encoding="utf-8")
    invoice_cache.mkdir()
    (invoice_cache / "invoice.csv").write_text("T1234567890123\n", encoding="utf-8")

    report = mod.build_report(
        jpintel_db=jpintel_db,
        autonomath_db=autonomath_db,
        gbiz_jsonl=gbiz_jsonl,
        invoice_cache_dir=invoice_cache,
        disk_path=tmp_path,
    )

    assert report["ok"] is True
    assert report["issues"] == []
    assert report["databases"]["jpintel"]["counts"]["houjin_master"] == 2
    assert report["databases"]["jpintel"]["counts"]["invoice_registrants"] == 1
    assert report["databases"]["jpintel"]["houjin_master_last_updated_nta"] == {
        "present": 1,
        "total": 2,
        "coverage": 0.5,
    }
    assert report["databases"]["autonomath"]["counts"]["corporate_entities"] == 1
    assert report["databases"]["autonomath"]["counts"]["gbiz_fact_rows"] == 1
    assert report["artifacts"]["gbiz_jsonl"]["exists"] is True
    assert report["artifacts"]["invoice_cache"]["file_count"] == 1


def test_build_report_flags_missing_bulk_index_and_artifacts(tmp_path: Path) -> None:
    mod = _load_module()
    jpintel_db = tmp_path / "jpintel.db"
    autonomath_db = tmp_path / "autonomath.db"
    _make_jpintel_db(jpintel_db, include_bulk_indexes=False)
    _make_autonomath_db(autonomath_db)

    report = mod.build_report(
        jpintel_db=jpintel_db,
        autonomath_db=autonomath_db,
        gbiz_jsonl=tmp_path / "missing.jsonl",
        invoice_cache_dir=tmp_path / "missing_cache",
        disk_path=tmp_path,
    )

    assert report["ok"] is False
    assert (
        "jpintel_db:index:invoice_registrants.idx_invoice_registrants_last_updated"
        in (report["issues"])
    )
    assert "gbiz_jsonl:missing" in report["issues"]
    assert "invoice_cache:missing_or_empty" in report["issues"]


def test_cli_writes_json_output(tmp_path: Path) -> None:
    mod = _load_module()
    jpintel_db = tmp_path / "jpintel.db"
    autonomath_db = tmp_path / "autonomath.db"
    gbiz_jsonl = tmp_path / "gbiz_enrichment.jsonl"
    invoice_cache = tmp_path / "invoice_cache"
    output = tmp_path / "audit.json"
    _make_jpintel_db(jpintel_db)
    _make_autonomath_db(autonomath_db)
    gbiz_jsonl.write_text("{}\n", encoding="utf-8")
    invoice_cache.mkdir()
    (invoice_cache / "cache.zip").write_bytes(b"zip")

    rc = mod.main(
        [
            "--jpintel-db",
            str(jpintel_db),
            "--autonomath-db",
            str(autonomath_db),
            "--gbiz-jsonl",
            str(gbiz_jsonl),
            "--invoice-cache-dir",
            str(invoice_cache),
            "--disk-path",
            str(tmp_path),
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["scope"].startswith("B1/B3 corporate bulk preflight")
