from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import reprobe_url_slash_flip as slash_flip  # noqa: E402


def test_slash_flip_url_preserves_query_and_fragment() -> None:
    assert slash_flip.slash_flip_url("https://example.jp/path?x=1#top") == (
        "https://example.jp/path/?x=1#top",
        "add_trailing_slash",
    )
    assert slash_flip.slash_flip_url("https://example.jp/path/?x=1#top") == (
        "https://example.jp/path?x=1#top",
        "remove_trailing_slash",
    )
    assert slash_flip.slash_flip_url("https://example.jp/") == (None, None)
    assert slash_flip.slash_flip_url("mailto:info@example.jp") == (None, None)


def test_collect_proposals_only_uses_hard_404_rows() -> None:
    rows = [
        slash_flip.LivenessRow(
            source_id="ok",
            old_url="https://example.jp/live",
            classification="ok",
        ),
        slash_flip.LivenessRow(
            source_id="dead",
            old_url="https://example.jp/dead",
            classification="hard_404",
            primary_name="Dead URL",
            tier="A",
        ),
    ]

    proposals = slash_flip.collect_slash_flip_proposals(rows)

    assert len(proposals) == 1
    assert proposals[0].source_id == "dead"
    assert proposals[0].new_url == "https://example.jp/dead/"
    assert proposals[0].transform == "add_trailing_slash"


def test_collect_proposals_skips_existing_flipped_url_duplicate_risk() -> None:
    rows = [
        slash_flip.LivenessRow(
            source_id="dead",
            old_url="https://example.jp/page",
            classification="hard_404",
        ),
        slash_flip.LivenessRow(
            source_id="known",
            old_url="https://example.jp/page/",
            classification="ok",
        ),
    ]

    assert slash_flip.collect_slash_flip_proposals(rows) == []


def test_collect_proposals_skips_converging_candidate_duplicate_risk() -> None:
    rows = [
        slash_flip.LivenessRow(
            source_id="one",
            old_url="https://example.jp/path//",
            classification="hard_404",
        ),
        slash_flip.LivenessRow(
            source_id="two",
            old_url="https://example.jp/path///",
            classification="hard_404",
        ),
    ]

    assert slash_flip.collect_slash_flip_proposals(rows) == []


def test_load_liveness_json_and_csv_shapes(tmp_path: Path) -> None:
    json_path = tmp_path / "liveness.json"
    json_path.write_text(
        json.dumps(
            {
                "summary": {},
                "results": [
                    {
                        "source_id": "json-row",
                        "url": "https://example.jp/json",
                        "latest_classification": "hard_404",
                        "status_code": 404,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    csv_path = tmp_path / "liveness.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["program_id", "source_url", "http_status", "primary_name"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "program_id": "csv-row",
                "source_url": "https://example.jp/csv",
                "http_status": "404",
                "primary_name": "CSV Row",
            }
        )

    json_rows = slash_flip.load_liveness_json(json_path)
    csv_rows = slash_flip.load_liveness_csv(csv_path)

    assert json_rows[0].source_id == "json-row"
    assert json_rows[0].classification == "hard_404"
    assert csv_rows[0].source_id == "csv-row"
    assert csv_rows[0].classification == "hard_404"


def test_load_db_rows_reads_404_rows_without_modifying_db() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT,
            tier TEXT,
            source_url TEXT,
            source_last_check_status INTEGER
        );
        INSERT INTO programs VALUES
            ('UNI-1', 'Dead', 'A', 'https://example.jp/dead', 404),
            ('UNI-2', 'Live', 'A', 'https://example.jp/live', 200);
        """
    )

    rows = slash_flip.load_db_rows(conn)

    assert len(rows) == 1
    assert rows[0].source_id == "UNI-1"
    assert rows[0].classification == "hard_404"
    assert conn.execute("SELECT COUNT(*) FROM programs").fetchone()[0] == 2
