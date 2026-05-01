from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import propose_court_source_excerpt_backfill as proposals  # noqa: E402


def _schema_snapshot(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    snapshot = {
        name: int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
        for (name,) in rows
    }
    conn.close()
    return snapshot


def test_extracts_proposal_from_local_labelled_court_text(tmp_path: Path) -> None:
    db = tmp_path / "courts.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE court_decisions (
            unified_id TEXT PRIMARY KEY,
            case_name TEXT,
            court TEXT,
            decision_date TEXT,
            source_url TEXT,
            source_excerpt TEXT,
            body_text TEXT
        );
        INSERT INTO court_decisions VALUES (
            'HAN-0000000001',
            '法人税更正処分取消請求事件',
            '最高裁判所',
            '2024-01-01',
            'https://www.courts.go.jp/hanrei/1/detail2/index.html',
            '',
            '判示事項 法人税法132条の2にいう法人税の負担を不当に減少させる結果となると認められるものの意義。 裁判要旨 同条は不自然な組織再編成による税負担減少に適用される。'
        );
        """
    )
    conn.commit()
    conn.close()

    rows, metadata = proposals.build_excerpt_proposals([db])

    assert metadata["scanned_tables"][0]["table"] == "court_decisions"
    assert rows == [
        {
            "table": "court_decisions",
            "row_id": "HAN-0000000001",
            "source_url": "https://www.courts.go.jp/hanrei/1/detail2/index.html",
            "current_excerpt": "",
            "proposed_excerpt": (
                "【判示事項】法人税法132条の2にいう法人税の負担を不当に減少させる結果となる"
                "と認められるものの意義。\n"
                "【裁判要旨】同条は不自然な組織再編成による税負担減少に適用される。"
            ),
            "confidence": 0.92,
            "reason": "proposed from local body_text labelled court text",
            "review_required": False,
        }
    ]


def test_unavailable_when_missing_excerpt_has_no_local_text(tmp_path: Path) -> None:
    db = tmp_path / "courts.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE court_decisions (
            unified_id TEXT PRIMARY KEY,
            case_name TEXT,
            court TEXT,
            decision_date TEXT,
            source_url TEXT,
            source_excerpt TEXT
        );
        INSERT INTO court_decisions VALUES (
            'HAN-0000000002',
            '行政処分取消請求事件',
            '東京地方裁判所',
            '2024-02-01',
            'https://www.courts.go.jp/hanrei/2/detail2/index.html',
            NULL
        );
        """
    )
    conn.commit()
    conn.close()

    rows, _metadata = proposals.build_excerpt_proposals([db])

    assert rows == [
        {
            "table": "court_decisions",
            "row_id": "HAN-0000000002",
            "source_url": "https://www.courts.go.jp/hanrei/2/detail2/index.html",
            "current_excerpt": "",
            "proposed_excerpt": "",
            "confidence": 0.0,
            "reason": "unavailable: no usable local source text or summary text columns on this row",
            "review_required": True,
        }
    ]


def test_cli_writes_report_artifacts_without_mutating_database(tmp_path: Path) -> None:
    db = tmp_path / "courts.db"
    json_path = tmp_path / "court_source_excerpt_proposals.json"
    csv_path = tmp_path / "court_source_excerpt_proposals.csv"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE court_decisions (
            unified_id TEXT PRIMARY KEY,
            case_name TEXT,
            court TEXT,
            source_url TEXT,
            source_excerpt TEXT,
            body_text TEXT
        );
        INSERT INTO court_decisions VALUES (
            'HAN-0000000003',
            '消費税事件',
            '大阪高等裁判所',
            'https://www.courts.go.jp/hanrei/3/detail2/index.html',
            '',
            '主文 原判決を破棄する。事案の概要 仕入税額控除の可否が争われた事案である。'
        );
        """
    )
    conn.commit()
    conn.close()
    before = _schema_snapshot(db)

    rc = proposals.main(
        [
            "--db",
            str(db),
            "--json-output",
            str(json_path),
            "--csv-output",
            str(csv_path),
        ]
    )

    assert rc == 0
    assert _schema_snapshot(db) == before
    decoded = json.loads(json_path.read_text(encoding="utf-8"))
    assert decoded["read_mode"] == {
        "sqlite_only": True,
        "network_fetch_performed": False,
        "db_mutation_performed": False,
    }
    assert decoded["completion_status"] == {"B5": "proposal_only", "complete": False}
    assert decoded["totals"] == {
        "rows_missing_source_excerpt": 1,
        "proposed": 1,
        "unavailable": 0,
        "review_required": 0,
        "tables": 1,
    }

    with csv_path.open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert csv_rows == [
        {
            "table": "court_decisions",
            "row_id": "HAN-0000000003",
            "source_url": "https://www.courts.go.jp/hanrei/3/detail2/index.html",
            "current_excerpt": "",
            "proposed_excerpt": "【主文】原判決を破棄する。\n【事案の概要】仕入税額控除の可否が争われた事案である。",
            "confidence": "0.92",
            "reason": "proposed from local body_text labelled court text",
            "review_required": "False",
        }
    ]
