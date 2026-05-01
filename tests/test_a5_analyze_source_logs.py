from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import analyze_source_verification_logs as analyzer  # noqa: E402


def _build_db(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:" if path is None else str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            source_url TEXT,
            domain TEXT,
            last_verified TEXT
        );
        """
    )
    return conn


def _json_block(
    *,
    candidate_rows: int,
    verified_probe_rows: int,
    updated_rows: int,
    outcomes: dict[str, int],
) -> str:
    return json.dumps(
        {
            "candidate_rows": candidate_rows,
            "generated_at": "2026-05-01T00:00:00+00:00",
            "last_verified_non_null_after": 12,
            "last_verified_non_null_before": 10,
            "last_verified_null_after": 4,
            "last_verified_null_before": 6,
            "methods": {"HEAD": candidate_rows},
            "mode": "apply",
            "outcomes": outcomes,
            "probed_rows": candidate_rows,
            "sample_results": [
                {
                    "error": None,
                    "final_url": "https://example.test/final",
                    "method": "HEAD",
                    "outcome": next(iter(outcomes)),
                    "source_id": 1,
                    "source_url": "https://example.test/source",
                    "status_code": 200,
                    "verified": verified_probe_rows > 0,
                }
            ],
            "updated_rows": updated_rows,
            "verified_at": "2026-05-01 00:00:00",
            "verified_probe_rows": verified_probe_rows,
        },
        indent=2,
        sort_keys=True,
    )


def test_parse_complete_shard_log_counts_result_json_without_nested_double_count(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "source_verification_shard_1_2026-05-01.log"
    log_path.write_text(
        "\n".join(
            [
                "source_verification_shard=1 run_date=2026-05-01 "
                "generated_at=2026-05-01T00:00:00+00:00 "
                "domain_count=2 unverified_http_rows=3",
                "domain=a.example unverified_http_rows=1",
                _json_block(
                    candidate_rows=1,
                    verified_probe_rows=1,
                    updated_rows=1,
                    outcomes={"ok": 1},
                ),
                "domain=b.example unverified_http_rows=2",
                _json_block(
                    candidate_rows=2,
                    verified_probe_rows=1,
                    updated_rows=1,
                    outcomes={"ok": 1, "transport_error": 1},
                ),
                "source_verification_shard=1 complete",
            ]
        ),
        encoding="utf-8",
    )

    summary = analyzer.parse_shard_log(log_path)

    assert summary["planned_domain_count"] == 2
    assert summary["planned_unverified_http_rows"] == 3
    assert summary["domain_lines_seen"] == 2
    assert summary["domains_processed"] == 2
    assert summary["domains_remaining_inferable"] == 0
    assert summary["candidate_rows"] == 3
    assert summary["probed_rows"] == 3
    assert summary["verified_probe_rows"] == 2
    assert summary["updated_rows"] == 2
    assert summary["outcomes"] == {"ok": 2, "transport_error": 1}
    assert summary["methods"] == {"HEAD": 3}
    assert summary["json_result_blocks"] == 2
    assert summary["complete"] is True


def test_parse_incomplete_shard_keeps_started_domain_unpaired(tmp_path: Path) -> None:
    log_path = tmp_path / "source_verification_shard_2_2026-05-01.log"
    log_path.write_text(
        "\n".join(
            [
                "source_verification_shard=2 run_date=2026-05-01 "
                "generated_at=2026-05-01T00:00:00+00:00 "
                "domain_count=3 unverified_http_rows=4",
                "domain=a.example unverified_http_rows=1",
                _json_block(
                    candidate_rows=1,
                    verified_probe_rows=1,
                    updated_rows=1,
                    outcomes={"redirect": 1},
                ),
                "domain=b.example unverified_http_rows=2",
            ]
        ),
        encoding="utf-8",
    )

    summary = analyzer.parse_shard_log(log_path)

    assert summary["domains_processed"] == 1
    assert summary["domain_lines_seen"] == 2
    assert summary["domains_remaining_inferable"] == 2
    assert summary["unlogged_remaining_domain_count"] == 1
    assert summary["candidate_rows_remaining_inferable"] == 3
    assert summary["domains_started_without_result_count"] == 1
    assert summary["domains_started_without_result"][0]["domain"] == "b.example"
    assert summary["complete"] is False


def test_collect_db_counts_reports_current_unverified_http_domain_buckets() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_source(id, source_url, domain, last_verified) VALUES (?, ?, ?, ?)",
        [
            (1, "https://a.example/1", "a.example", None),
            (2, "https://a.example/2", "a.example", None),
            (3, "https://a.example/verified", "a.example", "2026-05-01 00:00:00"),
            (4, "https://big.example/1", "big.example", None),
            (5, "https://big.example/2", "big.example", None),
            (6, "http://big.example/3", "big.example", None),
            (7, "https://missing.example/1", "", None),
            (8, "internal://fixture", "internal", None),
        ],
    )

    counts = analyzer.collect_db_counts(conn, quick_threshold=2)

    assert counts["rows"] == 8
    assert counts["verified_rows"] == 1
    assert counts["http_rows"] == 7
    assert counts["http_verified_rows"] == 1
    assert counts["http_unverified_rows"] == 6
    assert counts["remaining_http_domain_count"] == 2
    assert counts["remaining_http_domain_unverified_rows"] == 5
    assert counts["remaining_quick_domain_count"] == 1
    assert counts["remaining_quick_unverified_http_rows"] == 2
    assert counts["remaining_over_threshold_domain_count"] == 1
    assert counts["remaining_over_threshold_unverified_http_rows"] == 3
    assert counts["http_unverified_rows_without_stored_domain"] == 1


def test_analyze_source_verification_logs_writes_json_and_markdown(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "autonomath.db"
    with _build_db(db_path) as conn:
        conn.execute(
            "INSERT INTO am_source(id, source_url, domain, last_verified) "
            "VALUES (?, ?, ?, ?)",
            (1, "https://a.example/verified", "a.example", "2026-05-01 00:00:00"),
        )

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_path = log_dir / "source_verification_shard_1_2026-05-01.log"
    log_path.write_text(
        "\n".join(
            [
                "source_verification_shard=1 run_date=2026-05-01 "
                "generated_at=2026-05-01T00:00:00+00:00 "
                "domain_count=1 unverified_http_rows=1",
                "domain=a.example unverified_http_rows=1",
                _json_block(
                    candidate_rows=1,
                    verified_probe_rows=1,
                    updated_rows=1,
                    outcomes={"ok": 1},
                ),
                "source_verification_shard=1 complete",
            ]
        ),
        encoding="utf-8",
    )

    report = analyzer.analyze_source_verification_logs(
        db_path=db_path,
        log_dir=log_dir,
        run_date="2026-05-01",
        generated_at="2026-05-01T00:00:00+00:00",
    )
    json_output = tmp_path / "summary.json"
    md_output = tmp_path / "summary.md"

    analyzer.write_json_report(report, json_output)
    analyzer.write_markdown_report(report, md_output)

    assert report["completion_status"]["A5_complete"] is True
    assert json.loads(json_output.read_text(encoding="utf-8"))["log_totals"][
        "updated_rows"
    ] == 1
    assert "A5 complete: yes" in md_output.read_text(encoding="utf-8")
