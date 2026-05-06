from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "etl" / "report_official_finance_procurement_gaps.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("official_preflight", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _schema_snapshot(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    snapshot = {
        name: int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]) for (name,) in rows
    }
    conn.close()
    return snapshot


def test_schema_flexible_preflight_counts_gaps_and_domains(tmp_path: Path) -> None:
    mod = _load_module()
    db = tmp_path / "preflight.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE procurement_notices (
            id INTEGER PRIMARY KEY,
            title TEXT,
            buyer TEXT,
            notice_url TEXT,
            fetched_on TEXT,
            source_license TEXT
        );
        CREATE TABLE finance_loans (
            id INTEGER PRIMARY KEY,
            name TEXT,
            lender TEXT,
            url TEXT,
            retrieved_at TEXT,
            license TEXT,
            conditions TEXT
        );
        INSERT INTO procurement_notices VALUES
            (
                1,
                'GEPS server notice',
                'Digital Agency',
                'https://www.p-portal.go.jp/pps-web-biz/UAA01/OAA0101',
                '2026-04-30',
                'CC-BY-4.0'
            ),
            (
                2,
                'MAFF equipment bid',
                'MAFF',
                'https://www.maff.go.jp/j/supply/nyusatu/index.html',
                '',
                ''
            ),
            (3, 'offline notice', 'City', '', '2026-04-30', '');
        INSERT INTO finance_loans VALUES
            (
                1,
                '新創業融資制度',
                '日本政策金融公庫',
                'https://www.jfc.go.jp/n/finance/search/index_a_n01.html',
                '2026-04-30',
                'gov-standard',
                ''
            ),
            (
                2,
                'セーフティネット保証5号',
                '信用保証協会',
                'https://www.chusho.meti.go.jp/kinyu/sefu/',
                '',
                '',
                '信用保証協会の保証付き'
            ),
            (3, 'local bridge loan', 'City bank', '', '2026-04-30', '', '');
        """
    )
    conn.commit()
    conn.close()

    report = mod.build_report([db], sample_limit=10)

    procurement = report["coverage"]["b11_procurement"]
    assert procurement["counts"]["procurement_like_rows"] == 3
    assert procurement["counts"]["geps_like_rows"] == 1
    assert procurement["metadata_gaps_physical"] == {
        "provenance_missing": 1,
        "license_missing": 2,
        "freshness_missing": 1,
    }
    procurement_domains = {row["domain"]: row["rows"] for row in procurement["source_domains"]}
    assert procurement_domains["www.p-portal.go.jp"] == 1
    assert procurement_domains["www.maff.go.jp"] == 1

    finance = report["coverage"]["b12_finance_loans"]
    assert finance["counts"]["loan_like_rows"] == 3
    assert finance["counts"]["jfc_like_rows"] == 1
    assert finance["counts"]["credit_guarantee_like_rows"] == 1
    assert finance["metadata_gaps_physical"] == {
        "provenance_missing": 1,
        "license_missing": 2,
        "freshness_missing": 1,
    }
    finance_domains = {row["domain"]: row["rows"] for row in finance["source_domains"]}
    assert finance_domains["www.jfc.go.jp"] == 1
    assert finance_domains["www.chusho.meti.go.jp"] == 1

    geps_target = next(
        target
        for target in report["next_official_source_targets"]
        if target["source_domain"] == "www.p-portal.go.jp"
    )
    assert geps_target["source_path"] == "/pps-web-biz/"
    assert geps_target["current_rows"] == 1
    assert geps_target["network_fetch_performed"] is False


def test_cli_writes_json_without_mutating_database(tmp_path: Path, capsys) -> None:
    mod = _load_module()
    db = tmp_path / "cli.db"
    output = tmp_path / "official_preflight.json"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE bids (
            unified_id TEXT PRIMARY KEY,
            bid_title TEXT NOT NULL,
            bid_kind TEXT NOT NULL,
            procuring_entity TEXT NOT NULL,
            source_url TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );
        CREATE TABLE loan_programs (
            id INTEGER PRIMARY KEY,
            program_name TEXT NOT NULL,
            provider TEXT,
            official_url TEXT,
            fetched_at TEXT
        );
        INSERT INTO bids VALUES (
            'BID-1',
            'GEPS storage procurement',
            'open',
            'Ministry',
            'https://www.p-portal.go.jp/pps-web-biz/geps-chotatujoho/resources/app',
            '2026-04-30'
        );
        INSERT INTO loan_programs VALUES (
            1,
            'JFC startup loan',
            '日本政策金融公庫',
            'https://www.jfc.go.jp/n/finance/search/01.html',
            '2026-04-30'
        );
        """
    )
    conn.commit()
    conn.close()
    before = _schema_snapshot(db)

    rc = mod.main(["--db", str(db), "--output", str(output), "--json"])

    assert rc == 0
    assert _schema_snapshot(db) == before
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["read_mode"] == {
        "sqlite_only": True,
        "network_fetch_performed": False,
        "db_mutation_performed": False,
    }
    assert payload["coverage"]["b11_procurement"]["counts"]["geps_like_rows"] == 1
    assert payload["coverage"]["b12_finance_loans"]["counts"]["jfc_like_rows"] == 1
    assert payload["completion_status"] == {
        "B11": "preflight_only",
        "B12": "preflight_only",
        "complete": False,
    }
    printed = json.loads(capsys.readouterr().out)
    assert printed["coverage"]["b11_procurement"]["counts"]["procurement_like_rows"] == 1
