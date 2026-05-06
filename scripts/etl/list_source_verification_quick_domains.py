#!/usr/bin/env python3
"""List A5 quick source-verification domains without probing the network.

This is a runner plan, not a verifier. It reads ``autonomath.db`` in SQLite
read-only mode, selects remaining HTTP(S) ``am_source`` domains with at most
50 unverified rows, and writes CSV/JSON command plans for the existing
``backfill_am_source_last_verified.py --domain`` runner.
"""

from __future__ import annotations

import argparse
import csv
import json
import shlex
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_JSON_OUTPUT = (
    REPO_ROOT / "analysis_wave18" / "source_verification_quick_domains_2026-05-01.json"
)
DEFAULT_CSV_OUTPUT = (
    REPO_ROOT / "analysis_wave18" / "source_verification_quick_domains_2026-05-01.csv"
)

PYTHON_RUNNER = ".venv/bin/python"
BACKFILL_SCRIPT = "scripts/etl/backfill_am_source_last_verified.py"
DEFAULT_THRESHOLD = 50
DEFAULT_SHARDS = 4
DEFAULT_DRY_RUN_LIMIT = 25
DEFAULT_PER_HOST_DELAY_SEC = 1.0

REQUIRED_COLUMNS = {"id", "source_url", "domain", "last_verified"}
HTTP_URL_SQL = "(lower(source_url) LIKE 'http://%' OR lower(source_url) LIKE 'https://%')"

CSV_FIELDS = [
    "shard_id",
    "shard_domain_count",
    "shard_unverified_http_rows",
    "domain",
    "unverified_http_rows",
    "min_id",
    "max_id",
    "lower_bound_seconds_at_1_req_per_sec",
    "dry_run_command",
    "apply_command",
]


@dataclass(frozen=True)
class DomainCandidate:
    domain: str
    unverified_http_rows: int
    min_id: int
    max_id: int


@dataclass
class Shard:
    shard_id: int
    domains: list[DomainCandidate]
    unverified_http_rows: int = 0

    @property
    def domain_count(self) -> int:
        return len(self.domains)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _validate_am_source(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "am_source"):
        raise ValueError("am_source table is missing")
    missing = sorted(REQUIRED_COLUMNS - _columns(conn, "am_source"))
    if missing:
        raise ValueError(f"am_source is missing required columns: {missing}")


def _duration_hms(seconds: int) -> str:
    minutes, sec = divmod(max(0, seconds), 60)
    hours, minute = divmod(minutes, 60)
    days, hour = divmod(hours, 24)
    if days:
        return f"{days}d {hour:02d}h {minute:02d}m {sec:02d}s"
    if hours:
        return f"{hours}h {minute:02d}m {sec:02d}s"
    if minutes:
        return f"{minutes}m {sec:02d}s"
    return f"{sec}s"


def build_backfill_command(
    domain: str,
    *,
    db_path: Path,
    limit: int,
    mode: Literal["dry-run", "apply"],
    python_runner: str = PYTHON_RUNNER,
    backfill_script: str = BACKFILL_SCRIPT,
    per_host_delay_sec: float = DEFAULT_PER_HOST_DELAY_SEC,
) -> str:
    """Return a shell-safe command for the existing per-domain backfill runner."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    if per_host_delay_sec < 1.0:
        raise ValueError("per_host_delay_sec must be at least 1.0")
    mode_flag = "--dry-run" if mode == "dry-run" else "--apply"
    args = [
        python_runner,
        backfill_script,
        "--db",
        str(db_path),
        "--domain",
        domain,
        "--limit",
        str(limit),
        "--per-host-delay-sec",
        str(per_host_delay_sec),
        "--json",
        mode_flag,
    ]
    return " ".join(shlex.quote(arg) for arg in args)


def _domain_row(
    candidate: DomainCandidate,
    *,
    shard: Shard,
    db_path: Path,
    dry_run_limit: int,
    python_runner: str,
    backfill_script: str,
    per_host_delay_sec: float,
) -> dict[str, Any]:
    dry_limit = min(dry_run_limit, candidate.unverified_http_rows)
    return {
        "shard_id": shard.shard_id,
        "shard_domain_count": shard.domain_count,
        "shard_unverified_http_rows": shard.unverified_http_rows,
        "domain": candidate.domain,
        "unverified_http_rows": candidate.unverified_http_rows,
        "min_id": candidate.min_id,
        "max_id": candidate.max_id,
        "lower_bound_seconds_at_1_req_per_sec": candidate.unverified_http_rows,
        "dry_run_command": build_backfill_command(
            candidate.domain,
            db_path=db_path,
            limit=dry_limit,
            mode="dry-run",
            python_runner=python_runner,
            backfill_script=backfill_script,
            per_host_delay_sec=per_host_delay_sec,
        ),
        "apply_command": build_backfill_command(
            candidate.domain,
            db_path=db_path,
            limit=candidate.unverified_http_rows,
            mode="apply",
            python_runner=python_runner,
            backfill_script=backfill_script,
            per_host_delay_sec=per_host_delay_sec,
        ),
    }


def select_remaining_http_domains(conn: sqlite3.Connection) -> list[DomainCandidate]:
    """Return unverified HTTP(S) counts grouped by stored ``am_source.domain``."""
    _validate_am_source(conn)
    rows = conn.execute(
        f"""
        SELECT lower(trim(domain)) AS domain,
               COUNT(*) AS unverified_http_rows,
               MIN(id) AS min_id,
               MAX(id) AS max_id
          FROM am_source
         WHERE last_verified IS NULL
           AND source_url IS NOT NULL
           AND {HTTP_URL_SQL}
           AND domain IS NOT NULL
           AND trim(domain) <> ''
         GROUP BY lower(trim(domain))
         ORDER BY unverified_http_rows ASC, domain ASC
        """
    ).fetchall()
    return [
        DomainCandidate(
            domain=str(row["domain"]),
            unverified_http_rows=int(row["unverified_http_rows"]),
            min_id=int(row["min_id"]),
            max_id=int(row["max_id"]),
        )
        for row in rows
    ]


def select_quick_domains(
    conn: sqlite3.Connection,
    *,
    threshold: int = DEFAULT_THRESHOLD,
) -> list[DomainCandidate]:
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    return [
        candidate
        for candidate in select_remaining_http_domains(conn)
        if candidate.unverified_http_rows <= threshold
    ]


def count_unverified_http_rows_without_domain(conn: sqlite3.Connection) -> int:
    _validate_am_source(conn)
    row = conn.execute(
        f"""
        SELECT COUNT(*)
          FROM am_source
         WHERE last_verified IS NULL
           AND source_url IS NOT NULL
           AND {HTTP_URL_SQL}
           AND (domain IS NULL OR trim(domain) = '')
        """
    ).fetchone()
    return int(row[0])


def assign_shards(
    candidates: list[DomainCandidate],
    *,
    shard_count: int = DEFAULT_SHARDS,
) -> list[Shard]:
    """Assign domains to deterministic, disjoint shards balanced by row count."""
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")

    shards = [Shard(shard_id=i + 1, domains=[]) for i in range(shard_count)]
    for candidate in sorted(
        candidates,
        key=lambda item: (-item.unverified_http_rows, item.domain),
    ):
        shard = min(
            shards,
            key=lambda item: (
                item.unverified_http_rows,
                item.domain_count,
                item.shard_id,
            ),
        )
        shard.domains.append(candidate)
        shard.unverified_http_rows += candidate.unverified_http_rows

    for shard in shards:
        shard.domains.sort(key=lambda item: (item.unverified_http_rows, item.domain))
    return shards


def collect_quick_domain_plan(
    conn: sqlite3.Connection,
    *,
    db_path: Path = DEFAULT_DB,
    threshold: int = DEFAULT_THRESHOLD,
    shard_count: int = DEFAULT_SHARDS,
    dry_run_limit: int = DEFAULT_DRY_RUN_LIMIT,
    python_runner: str = PYTHON_RUNNER,
    backfill_script: str = BACKFILL_SCRIPT,
    per_host_delay_sec: float = DEFAULT_PER_HOST_DELAY_SEC,
) -> dict[str, Any]:
    """Collect a DB-only plan for quick A5 domain backfills."""
    if dry_run_limit <= 0:
        raise ValueError("dry_run_limit must be positive")
    if per_host_delay_sec < 1.0:
        raise ValueError("per_host_delay_sec must be at least 1.0")

    remaining_domains = select_remaining_http_domains(conn)
    quick_domains = [
        candidate for candidate in remaining_domains if candidate.unverified_http_rows <= threshold
    ]
    over_threshold_domains = [
        candidate for candidate in remaining_domains if candidate.unverified_http_rows > threshold
    ]
    shards = assign_shards(quick_domains, shard_count=shard_count)

    domain_rows: list[dict[str, Any]] = []
    shard_rows: list[dict[str, Any]] = []
    for shard in shards:
        rows = [
            _domain_row(
                candidate,
                shard=shard,
                db_path=db_path,
                dry_run_limit=dry_run_limit,
                python_runner=python_runner,
                backfill_script=backfill_script,
                per_host_delay_sec=per_host_delay_sec,
            )
            for candidate in shard.domains
        ]
        domain_rows.extend(rows)
        shard_rows.append(
            {
                "shard_id": shard.shard_id,
                "domain_count": shard.domain_count,
                "unverified_http_rows": shard.unverified_http_rows,
                "serial_lower_bound_seconds_at_1_req_per_sec": shard.unverified_http_rows,
                "serial_lower_bound_duration_at_1_req_per_sec": _duration_hms(
                    shard.unverified_http_rows
                ),
                "domains": [row["domain"] for row in rows],
                "dry_run_commands": [row["dry_run_command"] for row in rows],
                "apply_commands": [row["apply_command"] for row in rows],
            }
        )

    domain_rows.sort(
        key=lambda row: (
            int(row["shard_id"]),
            int(row["unverified_http_rows"]),
            str(row["domain"]),
        )
    )

    quick_rows = sum(candidate.unverified_http_rows for candidate in quick_domains)
    remaining_rows = sum(candidate.unverified_http_rows for candidate in remaining_domains)
    over_threshold_rows = sum(
        candidate.unverified_http_rows for candidate in over_threshold_domains
    )
    shard_seconds = max((shard.unverified_http_rows for shard in shards), default=0)
    missing_domain_rows = count_unverified_http_rows_without_domain(conn)

    return {
        "ok": True,
        "complete": False,
        "generated_at": _utc_now(),
        "scope": (
            "A5 quick-domain runner plan only; local SQLite read, no HTTP probes, "
            "no crawling, no DB mutation"
        ),
        "read_mode": {
            "sqlite_only": True,
            "network_fetch_performed": False,
            "db_mutation_performed": False,
            "database": str(db_path),
        },
        "rate_limit_model": {
            "per_host_delay_sec": per_host_delay_sec,
            "per_domain_request_rate_limit_per_sec": round(1.0 / per_host_delay_sec, 4),
            "shard_policy": (
                "Run at most one command per domain. Shards are disjoint by domain, "
                "so one shell per shard does not duplicate a domain."
            ),
        },
        "selection": {
            "threshold_unverified_http_rows_per_domain": threshold,
            "remaining_http_domain_count": len(remaining_domains),
            "remaining_http_unverified_rows": remaining_rows,
            "quick_domain_count": len(quick_domains),
            "quick_unverified_http_rows": quick_rows,
            "over_threshold_domain_count": len(over_threshold_domains),
            "over_threshold_unverified_http_rows": over_threshold_rows,
            "unverified_http_rows_without_stored_domain": missing_domain_rows,
        },
        "duration_estimates": {
            "all_quick_domains_single_shell_lower_bound_seconds": quick_rows,
            "all_quick_domains_single_shell_lower_bound_duration": _duration_hms(quick_rows),
            "all_shards_parallel_lower_bound_seconds": shard_seconds,
            "all_shards_parallel_lower_bound_duration": _duration_hms(shard_seconds),
        },
        "domains": domain_rows,
        "shards": shard_rows,
        "csv_fields": CSV_FIELDS,
        "next_command_notes": [
            "Commands are for later operator execution; this script did not run them.",
            "Use the dry-run command first if you want a small probe sample.",
            "Use the apply command to process the current quick-domain row count.",
            "Different shard shells are disjoint by domain; do not run two commands for the same domain at once.",
        ],
        "completion_status": {
            "A5": "quick_domain_runner_plan_only",
            "complete": False,
            "reason": (
                f"{remaining_rows} HTTP(S) am_source rows with stored domains still "
                "have last_verified missing; this script performed no network probes."
            ),
        },
    }


def write_json_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in report["domains"]:
            writer.writerow({field: row[field] for field in CSV_FIELDS})


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument("--shards", type=int, default=DEFAULT_SHARDS)
    parser.add_argument("--dry-run-limit", type=int, default=DEFAULT_DRY_RUN_LIMIT)
    parser.add_argument("--python-runner", default=PYTHON_RUNNER)
    parser.add_argument("--backfill-script", default=BACKFILL_SCRIPT)
    parser.add_argument("--per-host-delay-sec", type=float, default=DEFAULT_PER_HOST_DELAY_SEC)
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    parser.add_argument("--no-write", action="store_true", help="do not write CSV/JSON outputs")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    with _connect_readonly(args.db) as conn:
        report = collect_quick_domain_plan(
            conn,
            db_path=args.db,
            threshold=args.threshold,
            shard_count=args.shards,
            dry_run_limit=args.dry_run_limit,
            python_runner=args.python_runner,
            backfill_script=args.backfill_script,
            per_host_delay_sec=args.per_host_delay_sec,
        )

    if not args.no_write:
        write_json_report(report, args.json_output)
        write_csv_report(report, args.csv_output)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        selection = report["selection"]
        duration = report["duration_estimates"]
        print(f"quick_domain_count={selection['quick_domain_count']}")
        print(f"quick_unverified_http_rows={selection['quick_unverified_http_rows']}")
        print(f"remaining_http_domain_count={selection['remaining_http_domain_count']}")
        print(f"remaining_http_unverified_rows={selection['remaining_http_unverified_rows']}")
        print(
            "all_shards_parallel_lower_bound="
            f"{duration['all_shards_parallel_lower_bound_duration']}"
        )
        print("complete=False")
        if not args.no_write:
            print(f"json_output={args.json_output}")
            print(f"csv_output={args.csv_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
