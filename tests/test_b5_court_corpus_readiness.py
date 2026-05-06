from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "etl" / "report_court_corpus_readiness.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("court_readiness", SCRIPT_PATH)
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


def test_schema_flexible_counts_official_gaps_duplicates_and_categories(tmp_path: Path) -> None:
    mod = _load_module()
    db = tmp_path / "courts.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE court_decisions (
            unified_id TEXT PRIMARY KEY,
            case_name TEXT,
            case_number TEXT,
            court TEXT,
            decision_date TEXT,
            subject_area TEXT,
            key_ruling TEXT,
            full_text_url TEXT,
            pdf_url TEXT,
            source_url TEXT,
            source_excerpt TEXT,
            license TEXT,
            body_text TEXT
        );
        CREATE TABLE hanrei_cache (
            id INTEGER PRIMARY KEY,
            title TEXT,
            court_name TEXT,
            judgment_date TEXT,
            url TEXT,
            excerpt TEXT,
            body_text TEXT
        );
        CREATE TABLE enforcement_decision_refs (
            enforcement_case_id TEXT,
            decision_unified_id TEXT,
            source_url TEXT
        );
        INSERT INTO court_decisions VALUES
            (
                'HAN-0000000001',
                '所得税事件',
                '令和1(行ヒ)1',
                '最高裁判所',
                '2024-01-01',
                '租税',
                '所得税に関する判断',
                'https://www.courts.go.jp/hanrei/1/detail2/index.html',
                'https://www.courts.go.jp/assets/hanrei/hanrei-pdf-1.pdf',
                'https://www.courts.go.jp/hanrei/1/detail2/index.html',
                '判示事項',
                'gov-standard',
                '所得税本文'
            ),
            (
                'HAN-0000000002',
                '行政許可事件',
                '令和2(行ヒ)2',
                '東京地方裁判所',
                '2024-02-01',
                '行政',
                '許可取消に関する判断',
                'https://www.courts.go.jp/hanrei/2/detail2/index.html',
                '',
                '',
                '',
                '',
                ''
            ),
            (
                'HAN-0000000003',
                '法人税行政事件',
                '令和3(行ヒ)3',
                '大阪高等裁判所',
                '2024-03-01',
                '租税 行政',
                '法人税と行政処分',
                '',
                '',
                'https://www.courts.go.jp/hanrei/1/detail2/index.html',
                '裁判要旨',
                'gov-standard',
                ''
            ),
            (
                'HAN-0000000004',
                '民事事件',
                '令和4(受)4',
                '名古屋地方裁判所',
                '2024-04-01',
                '民事',
                '契約に関する判断',
                '',
                '',
                'https://example.test/hanrei/4',
                '抜粋',
                'private',
                '本文'
            );
        INSERT INTO hanrei_cache VALUES
            (
                1,
                '法人税 判決',
                '福岡地方裁判所',
                '2024-05-01',
                'https://www.courts.go.jp/hanrei/5/detail2/index.html',
                '',
                '法人税本文'
            ),
            (
                2,
                '民事 判決',
                '札幌地方裁判所',
                '2024-06-01',
                'https://example.test/hanrei/6',
                '抜粋',
                '本文'
            );
        INSERT INTO enforcement_decision_refs VALUES
            ('ENF-1', 'HAN-0000000001', 'https://www.courts.go.jp/hanrei/1/detail2/index.html');
        """
    )
    conn.commit()
    conn.close()

    report = mod.build_report([db], sample_limit=10)
    coverage = report["coverage"]["b5_courts"]

    assert report["read_mode"] == {
        "sqlite_only": True,
        "network_fetch_performed": False,
        "db_mutation_performed": False,
    }
    assert report["completion_status"] == {"B5": "readiness_only", "complete": False}
    assert coverage["candidate_table_count"] == 2
    assert coverage["physical_row_count"] == 6
    assert coverage["official_courts_go_jp_rows"] == 4
    assert coverage["duplicate_url_group_count"] == 1
    assert coverage["metadata_gaps_available"] == {
        "source_url_missing": 1,
        "source_excerpt_missing": 2,
        "license_missing": 1,
        "body_text_missing": 2,
    }
    assert coverage["likely_tax_rows"] == 3
    assert coverage["likely_administrative_rows"] == 2
    assert coverage["likely_tax_or_administrative_rows"] == 4
    assert coverage["metadata_missing_column_tables"]["source_url"] == [
        {"database": str(db), "table": "hanrei_cache"}
    ]
    assert coverage["metadata_missing_column_tables"]["license"] == [
        {"database": str(db), "table": "hanrei_cache"}
    ]
    assert {row["domain"]: row["rows"] for row in coverage["source_domains"]} == {
        "www.courts.go.jp": 4,
        "example.test": 2,
    }

    court_table = next(
        table
        for database in report["databases"]
        for table in database["tables"]
        if table["table"] == "court_decisions"
    )
    assert court_table["metadata"]["source_url"]["missing"] == 1
    assert court_table["metadata"]["source_excerpt"]["missing"] == 1
    assert court_table["metadata"]["license"]["missing"] == 1
    assert court_table["metadata"]["body_text"]["missing"] == 2
    assert court_table["duplicates"]["duplicate_url_groups"] == [
        {
            "table": "court_decisions",
            "column": "source_url",
            "url": "https://www.courts.go.jp/hanrei/1/detail2/index.html",
            "rows": 2,
        }
    ]

    plan_steps = {step["step"] for step in report["official_source_ingestion_backfill_plan"]}
    assert "normalize_official_source_urls" in plan_steps
    assert "backfill_body_text_from_official_text_or_pdf" in plan_steps


def test_cli_writes_json_without_mutating_database(tmp_path: Path, capsys) -> None:
    mod = _load_module()
    db = tmp_path / "cli_courts.db"
    output = tmp_path / "court_readiness.json"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE court_decisions (
            unified_id TEXT PRIMARY KEY,
            case_name TEXT,
            case_number TEXT,
            court TEXT,
            decision_date TEXT,
            subject_area TEXT,
            source_url TEXT,
            source_excerpt TEXT
        );
        INSERT INTO court_decisions VALUES (
            'HAN-0000000001',
            '行政処分取消事件',
            '令和1(行ヒ)1',
            '最高裁判所',
            '2024-01-01',
            '行政',
            'https://www.courts.go.jp/hanrei/1/detail2/index.html',
            ''
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
    assert payload["coverage"]["b5_courts"]["official_courts_go_jp_rows"] == 1
    assert (
        payload["coverage"]["b5_courts"]["metadata_gaps_available"]["source_excerpt_missing"] == 1
    )
    assert payload["completion_status"] == {"B5": "readiness_only", "complete": False}
    printed = json.loads(capsys.readouterr().out)
    assert printed["coverage"]["b5_courts"]["candidate_table_count"] == 1
