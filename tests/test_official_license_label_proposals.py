from __future__ import annotations

import csv
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "etl" / "propose_official_license_labels.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("official_license_proposals", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            source_url TEXT NOT NULL UNIQUE,
            domain TEXT,
            license TEXT
        );
        CREATE TABLE jpi_bids (
            unified_id TEXT PRIMARY KEY,
            bid_title TEXT NOT NULL,
            source_url TEXT NOT NULL,
            fetched_at TEXT
        );
        CREATE TABLE jpi_programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            authority_name TEXT,
            official_url TEXT,
            source_url TEXT,
            source_fetched_at TEXT
        );
        """
    )
    return conn


def test_public_procurement_row_without_license_column_requires_review() -> None:
    mod = _load_module()
    conn = _build_db()
    conn.execute(
        "INSERT INTO jpi_bids VALUES (?, ?, ?, ?)",
        (
            "BID-abc1234567",
            "GEPS storage procurement",
            "https://www.p-portal.go.jp/pps-web-biz/UAA01/OAA0101",
            "2026-04-30",
        ),
    )

    rows = mod.collect_license_label_proposals(conn)

    assert len(rows) == 1
    row = rows[0]
    assert row["task"] == "B11"
    assert row["entity_id"] == "BID-abc1234567"
    assert row["domain"] == "www.p-portal.go.jp"
    assert row["current_license"] == ""
    assert row["proposed_license"] == "gov_standard_v2.0"
    assert row["review_required"] is True
    assert "no row-level license column" in row["reason"]


def test_unknown_public_source_is_never_promoted_without_review() -> None:
    mod = _load_module()
    conn = _build_db()
    conn.execute(
        "INSERT INTO am_source VALUES (?, ?, ?, ?)",
        (
            1,
            "https://www.jfc.go.jp/n/finance/search/01.html",
            "www.jfc.go.jp",
            "unknown",
        ),
    )

    rows = mod.collect_license_label_proposals(conn)

    assert len(rows) == 1
    row = rows[0]
    assert row["table_name"] == "am_source"
    assert row["current_license"] == "unknown"
    assert row["proposed_license"] == "gov_standard_v2.0"
    assert row["review_required"] is True


def test_proprietary_pdl_domain_stays_review_required() -> None:
    mod = _load_module()

    classified = mod.classify_source_url("https://www.nta.go.jp/taxes/shiraberu/invoice/index.htm")

    assert classified is not None
    proposed_license, confidence, reason = classified
    assert proposed_license == "pdl_v1.0"
    assert confidence > 0.9
    assert "PDL" in reason

    assert mod._needs_proposal(
        current_license="proprietary",
        proposed_license=proposed_license,
        table_has_license_column=True,
    )


def test_zenshinhoren_unknown_is_not_promoted_to_public() -> None:
    mod = _load_module()
    conn = _build_db()
    conn.execute(
        "INSERT INTO am_source VALUES (?, ?, ?, ?)",
        (
            2,
            "https://www.zenshinhoren.or.jp/model-case/sogyo/",
            "www.zenshinhoren.or.jp",
            "unknown",
        ),
    )
    conn.execute(
        "INSERT INTO jpi_programs VALUES (?, ?, ?, ?, ?, ?)",
        (
            "UNI-guarantee1",
            "創業等関連保証",
            "信用保証協会",
            "https://www.zenshinhoren.or.jp/model-case/sogyo/",
            "https://www.zenshinhoren.or.jp/model-case/sogyo/",
            "2026-04-30",
        ),
    )

    rows = mod.collect_license_label_proposals(conn)

    assert {row["proposed_license"] for row in rows} == {"proprietary"}
    assert all(row["review_required"] is True for row in rows)
    assert all(row["proposed_license"] not in mod.PUBLIC_LICENSES for row in rows)


def test_cli_writes_csv_and_json_without_db_mutation(tmp_path: Path) -> None:
    mod = _load_module()
    db = tmp_path / "license-proposals.db"
    csv_output = tmp_path / "queue.csv"
    json_output = tmp_path / "queue.json"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            source_url TEXT NOT NULL UNIQUE,
            domain TEXT,
            license TEXT
        );
        CREATE TABLE jpi_loan_programs (
            id INTEGER PRIMARY KEY,
            program_name TEXT NOT NULL,
            provider TEXT,
            official_url TEXT,
            fetched_at TEXT
        );
        INSERT INTO jpi_loan_programs VALUES (
            1,
            '新規開業資金',
            '日本政策金融公庫',
            'https://www.jfc.go.jp/n/finance/search/01_sinkikaigyou_m.html',
            '2026-04-30'
        );
        """
    )
    before = conn.execute("SELECT COUNT(*) FROM jpi_loan_programs").fetchone()[0]
    conn.close()

    rc = mod.main(
        [
            "--db",
            str(db),
            "--csv-output",
            str(csv_output),
            "--json-output",
            str(json_output),
            "--json",
        ]
    )

    assert rc == 0
    with sqlite3.connect(db) as verify:
        after = verify.execute("SELECT COUNT(*) FROM jpi_loan_programs").fetchone()[0]
    assert after == before

    with csv_output.open(encoding="utf-8", newline="") as f:
        csv_rows = list(csv.DictReader(f))
    assert csv_rows[0]["proposed_license"] == "gov_standard_v2.0"
    assert csv_rows[0]["review_required"] == "true"

    payload = json.loads(json_output.read_text(encoding="utf-8"))
    assert payload["read_mode"] == {
        "sqlite_only": True,
        "network_fetch_performed": False,
        "db_mutation_performed": False,
    }
    assert payload["completion_status"] == {
        "B11": "review_queue_only",
        "B12": "review_queue_only",
        "complete": False,
    }
    assert payload["summary"]["proposal_rows"] == 1
