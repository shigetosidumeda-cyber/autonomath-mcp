from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import report_tier_bc_liveness_plan as plan  # noqa: E402


def _build_programs_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT,
            tier TEXT,
            source_url TEXT,
            source_url_status TEXT
        );
        """
    )
    return conn


def test_domain_grouping_counts_only_tier_bc_unknown_http_rows(tmp_path: Path) -> None:
    conn = _build_programs_db()
    conn.executemany(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?)",
        [
            ("UNI-A", "Tier A", "A", "https://alpha.example/a", "unknown"),
            ("UNI-B1", "B One", "B", "https://alpha.example/b1", "unknown"),
            ("UNI-B2", "B Two", "B", "https://alpha.example/b2", " "),
            ("UNI-B3", "B Live", "B", "https://alpha.example/live", "ok"),
            ("UNI-C1", "C One", "C", "HTTP://beta.example/c1", None),
            ("UNI-C2", "C Missing", "C", "", "unknown"),
            ("UNI-C3", "C Mail", "C", "mailto:info@example.jp", "unknown"),
        ],
    )

    report = plan.build_liveness_plan(
        conn,
        analysis_dir=tmp_path,
        bounded_scan_csv=None,
        sample_limit=10,
        shard_target_rows=10,
    )

    assert report["db_counts"]["tier_bc_unknown_source_url_status_rows"] == 5
    assert report["db_counts"]["http_candidate_rows"] == 3
    assert report["db_counts"]["non_http_or_missing_unknown_rows"] == 2
    assert report["db_counts"]["http_candidate_rows_by_tier"] == {"B": 2, "C": 1}
    assert [(row["domain"], row["row_count"]) for row in report["domain_counts"]] == [
        ("alpha.example", 2),
        ("beta.example", 1),
    ]
    assert [row["unified_id"] for row in report["sample_candidate_rows"]] == [
        "UNI-B1",
        "UNI-B2",
        "UNI-C1",
    ]
    assert [row[0] for row in conn.execute("SELECT source_url_status FROM programs ORDER BY unified_id")] == [
        "unknown",
        "unknown",
        " ",
        "ok",
        None,
        "unknown",
        "unknown",
    ]


def test_estimate_generation_and_shards_are_domain_exclusive(tmp_path: Path) -> None:
    conn = _build_programs_db()
    rows = [
        ("A1", "A1", "B", "https://a.example/1", "unknown"),
        ("A2", "A2", "B", "https://a.example/2", "unknown"),
        ("A3", "A3", "C", "https://a.example/3", "unknown"),
        ("B1", "B1", "B", "https://b.example/1", "unknown"),
        ("B2", "B2", "C", "https://b.example/2", "unknown"),
        ("C1", "C1", "B", "https://c.example/1", "unknown"),
        ("C2", "C2", "C", "https://c.example/2", "unknown"),
        ("D1", "D1", "C", "https://d.example/1", "unknown"),
    ]
    conn.executemany("INSERT INTO programs VALUES (?, ?, ?, ?, ?)", rows)

    report = plan.build_liveness_plan(
        conn,
        analysis_dir=tmp_path,
        bounded_scan_csv=None,
        shard_target_rows=4,
    )

    estimate = report["scan_duration_estimate"]
    assert estimate["candidate_rows"] == 8
    assert estimate["unique_domains"] == 4
    assert estimate["sequential_candidate_only_seconds"] == 8
    assert estimate["sequential_with_robots_seconds"] == 12
    assert estimate["largest_domain"] == "a.example"
    assert estimate["largest_domain_min_seconds_with_robots"] == 4

    shards = report["safe_batching_plan"]["shards"]
    assert report["safe_batching_plan"]["shard_count"] == 2
    assert sorted(shard["row_count"] for shard in shards) == [4, 4]
    seen_domains = [domain for shard in shards for domain in shard["domains"]]
    assert sorted(seen_domains) == ["a.example", "b.example", "c.example", "d.example"]
    assert len(seen_domains) == len(set(seen_domains))


def test_bounded_scan_summary_extrapolates_with_uncertainty(tmp_path: Path) -> None:
    csv_path = tmp_path / "tier_bc_url_liveness.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "unified_id",
                "source_url",
                "domain",
                "status_code",
                "classification",
                "method",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "unified_id": "ok",
                "source_url": "https://a.example/ok",
                "domain": "a.example",
                "status_code": "200",
                "classification": "ok",
                "method": "HEAD",
            }
        )
        writer.writerow(
            {
                "unified_id": "redirect",
                "source_url": "https://a.example/redirect",
                "domain": "a.example",
                "status_code": "200",
                "classification": "ok_redirect",
                "method": "HEAD",
            }
        )
        writer.writerow(
            {
                "unified_id": "dead",
                "source_url": "https://b.example/dead",
                "domain": "b.example",
                "status_code": "404",
                "classification": "hard_404",
                "method": "HEAD",
            }
        )
        writer.writerow(
            {
                "unified_id": "timeout",
                "source_url": "https://c.example/timeout",
                "domain": "c.example",
                "status_code": "",
                "classification": "transport_error",
                "method": "HEAD",
            }
        )

    summary = plan.summarize_bounded_scan_csv(csv_path, universe_rows=100)

    assert summary["present"] is True
    assert summary["sample_rows"] == 4
    assert summary["classification_distribution"] == {
        "hard_404": 1,
        "ok": 1,
        "ok_redirect": 1,
        "transport_error": 1,
    }
    extrapolation = summary["hidden_broken_extrapolation"]
    assert extrapolation["estimated_confirmed_broken_rows_if_representative"] == 25
    assert extrapolation["estimated_at_risk_rows_if_all_uncertain_are_broken"] == 50
    assert "planning/readiness only" in extrapolation["uncertainty_note"]
