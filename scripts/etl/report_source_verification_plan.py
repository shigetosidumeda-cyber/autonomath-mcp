#!/usr/bin/env python3
"""Build a read-only A5 source verification batching strategy report.

A5 verification is intentionally a strategy/readiness report here. This script
reads the local repo-root ``autonomath.db`` only, performs no HTTP probes, and
does not mutate SQLite. It summarizes ``am_source.last_verified`` coverage and
emits safe domain-sharded commands for the existing networked backfill helper.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "source_verification_plan_2026-05-01.json"

PYTHON_RUNNER = ".venv/bin/python"
BACKFILL_SCRIPT = "scripts/etl/backfill_am_source_last_verified.py"
DEFAULT_RATE_LIMIT_REQ_PER_SEC = 1.0
DEFAULT_BATCH_LIMIT = 1000
DEFAULT_DRY_RUN_LIMIT = 25
DEFAULT_DOMINANT_LIMIT = 12
DEFAULT_QUICK_THRESHOLD = 50
DEFAULT_QUICK_LIMIT = 25

HTTP_SCHEMES = {"http", "https"}
REQUIRED_COLUMNS = {"id", "source_url", "domain", "last_verified"}


@dataclass
class DomainStats:
    domain: str
    stored_domain: str | None
    total_rows: int = 0
    verified_rows: int = 0
    unverified_rows: int = 0
    http_rows: int = 0
    http_verified_rows: int = 0
    http_unverified_rows: int = 0
    non_http_rows: int = 0
    non_http_verified_rows: int = 0
    non_http_unverified_rows: int = 0
    scheme_counts: Counter[str] = field(default_factory=Counter)
    unverified_http_min_id: int | None = None
    unverified_http_max_id: int | None = None

    def add(self, *, source_id: int, scheme: str, is_http: bool, verified: bool) -> None:
        self.total_rows += 1
        self.scheme_counts[scheme] += 1
        if verified:
            self.verified_rows += 1
        else:
            self.unverified_rows += 1

        if is_http:
            self.http_rows += 1
            if verified:
                self.http_verified_rows += 1
            else:
                self.http_unverified_rows += 1
                if self.unverified_http_min_id is None:
                    self.unverified_http_min_id = source_id
                self.unverified_http_max_id = source_id
        else:
            self.non_http_rows += 1
            if verified:
                self.non_http_verified_rows += 1
            else:
                self.non_http_unverified_rows += 1


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


def _is_present(value: object) -> bool:
    return value is not None and str(value).strip() != ""


def _normalize_domain(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _url_scheme(url: object) -> str:
    if url is None:
        return "missing_scheme"
    scheme = urlparse(str(url).strip()).scheme.lower()
    return scheme or "missing_scheme"


def _url_host(url: object) -> str:
    if url is None:
        return ""
    return (urlparse(str(url).strip()).hostname or "").lower()


def _is_http_scheme(scheme: str) -> bool:
    return scheme in HTTP_SCHEMES


def _pct(part: int, total: int) -> float:
    if total == 0:
        return 100.0
    return round((part / total) * 100, 2)


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


def _command_quote(value: str) -> str:
    return shlex.quote(value)


def _domain_command(domain: str, *, limit: int, db_path: Path, apply: bool) -> str:
    db_arg = _command_quote(str(db_path))
    domain_arg = _command_quote(domain)
    mode = "--apply" if apply else "--dry-run"
    return (
        f"{PYTHON_RUNNER} {BACKFILL_SCRIPT} --db {db_arg} --domain {domain_arg} "
        f"--limit {limit} --per-host-delay-sec 1.0 --json {mode}"
    )


def _domain_commands(
    domain: str,
    *,
    dry_run_limit: int,
    apply_limit: int,
    db_path: Path,
) -> dict[str, str]:
    return {
        "dry_run_sample": _domain_command(
            domain,
            limit=dry_run_limit,
            db_path=db_path,
            apply=False,
        ),
        "apply_batch": _domain_command(
            domain,
            limit=apply_limit,
            db_path=db_path,
            apply=True,
        ),
    }


def _domain_report(
    stats: DomainStats,
    *,
    total_remaining_http_rows: int,
    db_path: Path,
    batch_limit: int,
) -> dict[str, Any]:
    remaining = stats.http_unverified_rows
    row: dict[str, Any] = {
        "domain": stats.domain,
        "stored_domain": stats.stored_domain,
        "commandable_with_existing_backfill_domain_filter": stats.stored_domain is not None,
        "total_rows": stats.total_rows,
        "verified_rows": stats.verified_rows,
        "unverified_rows": stats.unverified_rows,
        "verification_coverage_pct": _pct(stats.verified_rows, stats.total_rows),
        "http_rows": stats.http_rows,
        "http_verified_rows": stats.http_verified_rows,
        "http_unverified_rows": remaining,
        "http_verification_coverage_pct": _pct(stats.http_verified_rows, stats.http_rows),
        "non_http_rows": stats.non_http_rows,
        "non_http_verified_rows": stats.non_http_verified_rows,
        "non_http_unverified_rows": stats.non_http_unverified_rows,
        "non_http_verification_coverage_pct": _pct(
            stats.non_http_verified_rows,
            stats.non_http_rows,
        ),
        "scheme_counts": dict(sorted(stats.scheme_counts.items())),
        "remaining_http_share_pct": _pct(remaining, total_remaining_http_rows),
        "lower_bound_seconds_at_1_req_per_sec": remaining,
        "lower_bound_duration_at_1_req_per_sec": _duration_hms(remaining),
        "unverified_http_min_id": stats.unverified_http_min_id,
        "unverified_http_max_id": stats.unverified_http_max_id,
    }
    if stats.stored_domain is not None and remaining > 0:
        row["next_commands"] = _domain_commands(
            stats.stored_domain,
            dry_run_limit=min(DEFAULT_DRY_RUN_LIMIT, remaining),
            apply_limit=min(batch_limit, remaining),
            db_path=db_path,
        )
    return row


def _scheme_bucket_report(
    scheme_counts: dict[str, Counter[str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scheme, counts in sorted(scheme_counts.items()):
        total = counts["rows"]
        verified = counts["verified_rows"]
        rows.append(
            {
                "scheme": scheme,
                "url_kind": "http" if scheme in HTTP_SCHEMES else "non_http",
                "rows": total,
                "verified_rows": verified,
                "unverified_rows": counts["unverified_rows"],
                "verification_coverage_pct": _pct(verified, total),
            }
        )
    return rows


def _dominant_domains(
    domains: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    dominant: list[dict[str, Any]] = []
    cumulative = 0
    for row in domains:
        remaining = int(row["http_unverified_rows"])
        if remaining <= 0:
            continue
        cumulative += remaining
        item = {
            "domain": row["domain"],
            "stored_domain": row["stored_domain"],
            "http_unverified_rows": remaining,
            "remaining_http_share_pct": row["remaining_http_share_pct"],
            "cumulative_http_unverified_rows": cumulative,
            "lower_bound_duration_at_1_req_per_sec": row[
                "lower_bound_duration_at_1_req_per_sec"
            ],
        }
        if "next_commands" in row:
            item["next_commands"] = row["next_commands"]
        dominant.append(item)
        if len(dominant) >= limit:
            break
    return dominant


def _quick_parallel_domains(
    domains: list[dict[str, Any]],
    *,
    threshold: int,
    limit: int,
) -> tuple[int, int, list[dict[str, Any]]]:
    eligible = [
        row
        for row in domains
        if 0 < int(row["http_unverified_rows"]) <= threshold
        and row["commandable_with_existing_backfill_domain_filter"]
    ]
    eligible.sort(key=lambda row: (int(row["http_unverified_rows"]), str(row["domain"])))
    sample = [
        {
            "domain": row["domain"],
            "http_unverified_rows": row["http_unverified_rows"],
            "lower_bound_duration_at_1_req_per_sec": row[
                "lower_bound_duration_at_1_req_per_sec"
            ],
            "next_commands": row["next_commands"],
        }
        for row in eligible[:limit]
    ]
    return (
        len(eligible),
        sum(int(row["http_unverified_rows"]) for row in eligible),
        sample,
    )


def _completion_status(total_remaining_http_rows: int) -> dict[str, Any]:
    return {
        "A5": "strategy_readiness_only",
        "complete": False,
        "reason": (
            f"{total_remaining_http_rows} HTTP(S) am_source rows still have "
            "last_verified missing; this report performed no network probes."
        ),
    }


def collect_source_verification_plan(
    conn: sqlite3.Connection,
    *,
    db_path: Path = DEFAULT_DB,
    dominant_limit: int = DEFAULT_DOMINANT_LIMIT,
    quick_threshold: int = DEFAULT_QUICK_THRESHOLD,
    quick_limit: int = DEFAULT_QUICK_LIMIT,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
) -> dict[str, Any]:
    """Collect A5 verification coverage and batching estimates without probing URLs."""
    if not _table_exists(conn, "am_source"):
        raise ValueError("am_source table is missing")

    columns = _columns(conn, "am_source")
    missing_columns = sorted(REQUIRED_COLUMNS - columns)
    if missing_columns:
        raise ValueError(f"am_source is missing required columns: {missing_columns}")

    totals = Counter()
    scheme_counts: dict[str, Counter[str]] = {}
    domain_stats: dict[str, DomainStats] = {}
    http_rows_with_stored_domain = 0
    http_unverified_rows_with_stored_domain = 0

    rows = conn.execute(
        """
        SELECT id, source_url, domain, last_verified
          FROM am_source
         ORDER BY id
        """
    )
    for row in rows:
        source_id = int(row["id"])
        source_url = row["source_url"]
        stored_domain = _normalize_domain(row["domain"])
        url_host = _url_host(source_url)
        domain_key = stored_domain or url_host or "(missing-domain)"
        scheme = _url_scheme(source_url)
        is_http = _is_http_scheme(scheme)
        verified = _is_present(row["last_verified"])

        stats = domain_stats.get(domain_key)
        if stats is None:
            stats = DomainStats(
                domain=domain_key,
                stored_domain=stored_domain or None,
            )
            domain_stats[domain_key] = stats
        stats.add(source_id=source_id, scheme=scheme, is_http=is_http, verified=verified)

        scheme_counter = scheme_counts.setdefault(scheme, Counter())
        scheme_counter["rows"] += 1
        if verified:
            scheme_counter["verified_rows"] += 1
        else:
            scheme_counter["unverified_rows"] += 1

        totals["rows"] += 1
        if verified:
            totals["verified_rows"] += 1
        else:
            totals["unverified_rows"] += 1

        if is_http:
            totals["http_rows"] += 1
            if stored_domain:
                http_rows_with_stored_domain += 1
            if verified:
                totals["http_verified_rows"] += 1
            else:
                totals["http_unverified_rows"] += 1
                if stored_domain:
                    http_unverified_rows_with_stored_domain += 1
        else:
            totals["non_http_rows"] += 1
            if verified:
                totals["non_http_verified_rows"] += 1
            else:
                totals["non_http_unverified_rows"] += 1

    total_remaining_http_rows = totals["http_unverified_rows"]
    domains = [
        _domain_report(
            stats,
            total_remaining_http_rows=total_remaining_http_rows,
            db_path=db_path,
            batch_limit=batch_limit,
        )
        for stats in domain_stats.values()
    ]
    domains.sort(
        key=lambda row: (
            -int(row["http_unverified_rows"]),
            -int(row["total_rows"]),
            str(row["domain"]),
        )
    )

    dominant = _dominant_domains(domains, limit=dominant_limit)
    quick_domain_count, quick_rows, quick_domains = _quick_parallel_domains(
        domains,
        threshold=quick_threshold,
        limit=quick_limit,
    )
    max_domain_rows = max(
        (int(row["http_unverified_rows"]) for row in domains),
        default=0,
    )
    dominant_domain = dominant[0] if dominant else None

    return {
        "ok": True,
        "complete": False,
        "generated_at": _utc_now(),
        "scope": (
            "A5 am_source.last_verified batching strategy only; local SQLite read, "
            "no crawling, no HTTP probes, no DB mutation"
        ),
        "read_mode": {
            "sqlite_only": True,
            "network_fetch_performed": False,
            "db_mutation_performed": False,
            "database": str(db_path),
        },
        "rate_limit_model": {
            "per_domain_request_rate_limit_per_sec": DEFAULT_RATE_LIMIT_REQ_PER_SEC,
            "lower_bound_notes": (
                "Duration estimates assume one verification request per remaining HTTP(S) row "
                "at exactly 1 request/sec/domain and ignore robots.txt fetches, fallback GETs, "
                "network latency, retries, and operator pauses."
            ),
        },
        "totals": {
            "rows": totals["rows"],
            "verified_rows": totals["verified_rows"],
            "unverified_rows": totals["unverified_rows"],
            "verification_coverage_pct": _pct(totals["verified_rows"], totals["rows"]),
            "http_rows": totals["http_rows"],
            "http_verified_rows": totals["http_verified_rows"],
            "http_unverified_rows": total_remaining_http_rows,
            "http_verification_coverage_pct": _pct(
                totals["http_verified_rows"],
                totals["http_rows"],
            ),
            "non_http_rows": totals["non_http_rows"],
            "non_http_verified_rows": totals["non_http_verified_rows"],
            "non_http_unverified_rows": totals["non_http_unverified_rows"],
            "non_http_verification_coverage_pct": _pct(
                totals["non_http_verified_rows"],
                totals["non_http_rows"],
            ),
            "domain_count": len(domains),
            "http_domain_count": sum(1 for row in domains if int(row["http_rows"]) > 0),
            "remaining_http_domain_count": sum(
                1 for row in domains if int(row["http_unverified_rows"]) > 0
            ),
            "http_rows_with_stored_domain": http_rows_with_stored_domain,
            "http_rows_without_stored_domain": totals["http_rows"] - http_rows_with_stored_domain,
            "http_unverified_rows_with_stored_domain": http_unverified_rows_with_stored_domain,
            "http_unverified_rows_without_stored_domain": (
                total_remaining_http_rows - http_unverified_rows_with_stored_domain
            ),
        },
        "coverage_by_url_scheme": _scheme_bucket_report(scheme_counts),
        "domain_coverage": domains,
        "duration_estimates": {
            "serial_single_domain_shards_lower_bound_seconds": total_remaining_http_rows,
            "serial_single_domain_shards_lower_bound_duration": _duration_hms(
                total_remaining_http_rows
            ),
            "all_domains_parallel_lower_bound_seconds": max_domain_rows,
            "all_domains_parallel_lower_bound_duration": _duration_hms(max_domain_rows),
            "dominant_domain": dominant_domain,
        },
        "dominant_a5_domains": dominant,
        "quick_parallel_scan": {
            "threshold_remaining_http_rows_per_domain": quick_threshold,
            "domain_count": quick_domain_count,
            "http_unverified_rows": quick_rows,
            "domains": quick_domains,
        },
        "next_command_notes": [
            "Commands are for later operator execution; this report did not execute them.",
            "Run at most one process per --domain. Different domains can be run in parallel.",
            "Use --dry-run for a small probe sample first, then --apply for resumable batches.",
            "If interrupted, reuse the backfill output's last_source_id with --resume-after-id.",
        ],
        "completion_status": _completion_status(total_remaining_http_rows),
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dominant-limit", type=int, default=DEFAULT_DOMINANT_LIMIT)
    parser.add_argument("--quick-threshold", type=int, default=DEFAULT_QUICK_THRESHOLD)
    parser.add_argument("--quick-limit", type=int, default=DEFAULT_QUICK_LIMIT)
    parser.add_argument("--batch-limit", type=int, default=DEFAULT_BATCH_LIMIT)
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    parser.add_argument("--no-write", action="store_true", help="do not write --output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    with _connect_readonly(args.db) as conn:
        report = collect_source_verification_plan(
            conn,
            db_path=args.db,
            dominant_limit=args.dominant_limit,
            quick_threshold=args.quick_threshold,
            quick_limit=args.quick_limit,
            batch_limit=args.batch_limit,
        )

    if not args.no_write:
        write_report(report, args.output)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        totals = report["totals"]
        duration = report["duration_estimates"]
        print(f"am_source_rows={totals['rows']}")
        print(f"http_rows={totals['http_rows']}")
        print(f"http_unverified_rows={totals['http_unverified_rows']}")
        print(f"non_http_rows={totals['non_http_rows']}")
        print(
            "all_domains_parallel_lower_bound="
            f"{duration['all_domains_parallel_lower_bound_duration']}"
        )
        print("complete=False")
        if not args.no_write:
            print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
