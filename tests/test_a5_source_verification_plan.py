from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import report_source_verification_plan as plan  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            source_url TEXT NOT NULL,
            domain TEXT,
            last_verified TEXT
        );
        """
    )
    return conn


def test_collect_plan_counts_http_non_http_domain_coverage_and_duration() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_source(id, source_url, domain, last_verified) VALUES (?, ?, ?, ?)",
        [
            (1, "https://big.example/a", "big.example", None),
            (2, "https://big.example/b", "big.example", None),
            (3, "http://big.example/c", "big.example", "2026-05-01 00:00:00"),
            (4, "https://fast.example/a", "fast.example", None),
            (5, "internal://fixture", "internal", None),
            (6, "file:///tmp/source", None, "2026-05-01 00:00:00"),
        ],
    )

    report = plan.collect_source_verification_plan(
        conn,
        db_path=Path("autonomath.db"),
        dominant_limit=2,
        quick_threshold=1,
        quick_limit=5,
        batch_limit=100,
    )

    assert report["read_mode"]["network_fetch_performed"] is False
    assert report["totals"] == {
        "rows": 6,
        "verified_rows": 2,
        "unverified_rows": 4,
        "verification_coverage_pct": 33.33,
        "http_rows": 4,
        "http_verified_rows": 1,
        "http_unverified_rows": 3,
        "http_verification_coverage_pct": 25.0,
        "non_http_rows": 2,
        "non_http_verified_rows": 1,
        "non_http_unverified_rows": 1,
        "non_http_verification_coverage_pct": 50.0,
        "domain_count": 4,
        "http_domain_count": 2,
        "remaining_http_domain_count": 2,
        "http_rows_with_stored_domain": 4,
        "http_rows_without_stored_domain": 0,
        "http_unverified_rows_with_stored_domain": 3,
        "http_unverified_rows_without_stored_domain": 0,
    }
    assert report["duration_estimates"]["all_domains_parallel_lower_bound_seconds"] == 2
    assert report["duration_estimates"]["serial_single_domain_shards_lower_bound_seconds"] == 3
    assert report["dominant_a5_domains"][0]["domain"] == "big.example"
    assert report["dominant_a5_domains"][0]["http_unverified_rows"] == 2
    assert report["quick_parallel_scan"]["domain_count"] == 1
    assert report["quick_parallel_scan"]["domains"][0]["domain"] == "fast.example"


def test_plan_commands_use_existing_domain_sharded_backfill() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_source(id, source_url, domain, last_verified) VALUES (?, ?, ?, ?)",
        [
            (1, "https://fast.example/a", "fast.example", None),
            (2, "https://missing.example/a", "", None),
        ],
    )

    report = plan.collect_source_verification_plan(
        conn,
        db_path=Path("autonomath.db"),
        quick_threshold=5,
        batch_limit=10,
    )

    commandable = next(
        row for row in report["domain_coverage"] if row["domain"] == "fast.example"
    )
    missing_domain = next(
        row for row in report["domain_coverage"] if row["domain"] == "missing.example"
    )

    dry_run = commandable["next_commands"]["dry_run_sample"]
    apply = commandable["next_commands"]["apply_batch"]
    assert "scripts/etl/backfill_am_source_last_verified.py" in dry_run
    assert "--domain fast.example" in dry_run
    assert "--dry-run" in dry_run
    assert "--per-host-delay-sec 1.0" in dry_run
    assert "--apply" in apply
    assert missing_domain["commandable_with_existing_backfill_domain_filter"] is False
    assert "next_commands" not in missing_domain


def test_collect_plan_reports_url_scheme_buckets() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_source(id, source_url, domain, last_verified) VALUES (?, ?, ?, ?)",
        [
            (1, "https://a.example/1", "a.example", None),
            (2, "http://a.example/2", "a.example", "2026-05-01"),
            (3, "internal://fixture", "internal", None),
        ],
    )

    report = plan.collect_source_verification_plan(conn, db_path=Path("autonomath.db"))
    by_scheme = {row["scheme"]: row for row in report["coverage_by_url_scheme"]}

    assert by_scheme["https"]["url_kind"] == "http"
    assert by_scheme["https"]["unverified_rows"] == 1
    assert by_scheme["http"]["verified_rows"] == 1
    assert by_scheme["internal"]["url_kind"] == "non_http"


def test_write_report_materializes_json(tmp_path: Path) -> None:
    output = tmp_path / "source_verification_plan.json"
    report = {"ok": True, "totals": {"rows": 0}}

    plan.write_report(report, output)

    assert json.loads(output.read_text(encoding="utf-8")) == report
