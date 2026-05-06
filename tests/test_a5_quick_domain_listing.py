from __future__ import annotations

import csv
import json
import shlex
import sqlite3
import sys
from pathlib import Path

import pytest

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import list_source_verification_quick_domains as quick  # noqa: E402


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


def _insert_domain(
    conn: sqlite3.Connection,
    *,
    start_id: int,
    domain: str,
    count: int,
) -> int:
    conn.executemany(
        "INSERT INTO am_source(id, source_url, domain, last_verified) VALUES (?, ?, ?, ?)",
        [
            (
                start_id + offset,
                f"https://{domain}/source/{offset}",
                domain,
                None,
            )
            for offset in range(count)
        ],
    )
    return start_id + count


def test_select_quick_domains_counts_unverified_http_rows_and_id_range() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_source(id, source_url, domain, last_verified) VALUES (?, ?, ?, ?)",
        [
            (1, "https://a.example/one", "a.example", None),
            (2, "https://a.example/verified", "a.example", "2026-05-01 00:00:00"),
            (3, "http://a.example/two", "a.example", None),
            (4, "https://big.example/one", "big.example", None),
            (5, "https://big.example/two", "big.example", None),
            (6, "https://big.example/three", "big.example", None),
            (7, "internal://fixture", "internal", None),
            (8, "https://missing-domain.example/one", "", None),
        ],
    )

    rows = quick.select_quick_domains(conn, threshold=2)

    assert rows == [
        quick.DomainCandidate(
            domain="a.example",
            unverified_http_rows=2,
            min_id=1,
            max_id=3,
        )
    ]
    assert quick.count_unverified_http_rows_without_domain(conn) == 1


def test_backfill_command_generation_is_exact_and_shell_safe() -> None:
    command = quick.build_backfill_command(
        "a.example",
        db_path=Path("autonomath.db"),
        limit=3,
        mode="apply",
    )

    assert shlex.split(command) == [
        ".venv/bin/python",
        "scripts/etl/backfill_am_source_last_verified.py",
        "--db",
        "autonomath.db",
        "--domain",
        "a.example",
        "--limit",
        "3",
        "--per-host-delay-sec",
        "1.0",
        "--json",
        "--apply",
    ]

    with pytest.raises(ValueError, match="per_host_delay_sec"):
        quick.build_backfill_command(
            "a.example",
            db_path=Path("autonomath.db"),
            limit=3,
            mode="apply",
            per_host_delay_sec=0.5,
        )


def test_collect_plan_generates_disjoint_balanced_shards_and_commands() -> None:
    conn = _build_db()
    next_id = 1
    next_id = _insert_domain(conn, start_id=next_id, domain="a.example", count=50)
    next_id = _insert_domain(conn, start_id=next_id, domain="b.example", count=20)
    next_id = _insert_domain(conn, start_id=next_id, domain="c.example", count=10)
    next_id = _insert_domain(conn, start_id=next_id, domain="d.example", count=5)
    _insert_domain(conn, start_id=next_id, domain="too-big.example", count=51)

    report = quick.collect_quick_domain_plan(
        conn,
        db_path=Path("autonomath.db"),
        threshold=50,
        shard_count=2,
        dry_run_limit=7,
    )

    assert report["read_mode"]["network_fetch_performed"] is False
    assert report["read_mode"]["db_mutation_performed"] is False
    assert report["selection"]["quick_domain_count"] == 4
    assert report["selection"]["quick_unverified_http_rows"] == 85
    assert report["selection"]["over_threshold_domain_count"] == 1
    assert report["duration_estimates"]["all_shards_parallel_lower_bound_seconds"] == 50

    rows = {row["domain"]: row for row in report["domains"]}
    assert rows["a.example"]["min_id"] == 1
    assert rows["a.example"]["max_id"] == 50
    assert rows["a.example"]["unverified_http_rows"] == 50
    assert "--domain a.example" in rows["a.example"]["apply_command"]
    assert "--limit 50" in rows["a.example"]["apply_command"]
    assert rows["d.example"]["dry_run_command"].endswith("--dry-run")
    assert "--limit 5" in rows["d.example"]["dry_run_command"]
    assert "--limit 7" in rows["c.example"]["dry_run_command"]

    shards = report["shards"]
    assert shards[0]["domains"] == ["a.example"]
    assert shards[0]["unverified_http_rows"] == 50
    assert shards[1]["domains"] == ["d.example", "c.example", "b.example"]
    assert shards[1]["unverified_http_rows"] == 35
    assert set(shards[0]["domains"]).isdisjoint(shards[1]["domains"])


def test_write_json_and_csv_reports(tmp_path: Path) -> None:
    conn = _build_db()
    _insert_domain(conn, start_id=1, domain="a.example", count=2)
    report = quick.collect_quick_domain_plan(
        conn,
        db_path=Path("autonomath.db"),
        threshold=50,
        shard_count=1,
    )

    json_path = tmp_path / "quick_domains.json"
    csv_path = tmp_path / "quick_domains.csv"

    quick.write_json_report(report, json_path)
    quick.write_csv_report(report, csv_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))["selection"]["quick_domain_count"] == 1
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["domain"] == "a.example"
    assert rows[0]["unverified_http_rows"] == "2"
    assert rows[0]["apply_command"].endswith("--apply")
