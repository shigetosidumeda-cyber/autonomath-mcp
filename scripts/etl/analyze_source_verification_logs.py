#!/usr/bin/env python3
"""Analyze A5 source-verification shard logs after a run.

The analyzer is deliberately offline: it reads local shard logs plus read-only
SQLite counts from ``autonomath.db``. It performs no network probes and does
not mutate the database.
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DATE = "2026-05-01"

DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_LOG_DIR = REPO_ROOT / "analysis_wave18"
DEFAULT_JSON_OUTPUT = (
    REPO_ROOT / "analysis_wave18" / f"source_verification_shard_summary_{RUN_DATE}.json"
)
DEFAULT_MD_OUTPUT = (
    REPO_ROOT / "analysis_wave18" / f"source_verification_shard_summary_{RUN_DATE}.md"
)

REQUIRED_COLUMNS = {"id", "source_url", "domain", "last_verified"}
HTTP_URL_SQL = "(lower(source_url) LIKE 'http://%' OR lower(source_url) LIKE 'https://%')"
VERIFIED_SQL = "(last_verified IS NOT NULL AND trim(last_verified) <> '')"

HEADER_RE = re.compile(
    r"\bsource_verification_shard=(?P<shard_id>\d+)\b"
    r".*?\bdomain_count=(?P<domain_count>\d+)\b"
    r".*?\bunverified_http_rows=(?P<unverified_http_rows>\d+)\b"
)
DOMAIN_RE = re.compile(
    r"^domain=(?P<domain>\S+)\s+unverified_http_rows=(?P<unverified_http_rows>\d+)\s*$",
    re.MULTILINE,
)
COMPLETE_RE = re.compile(r"\bsource_verification_shard=(?P<shard_id>\d+)\s+complete\b")
TOP_LEVEL_JSON_START_RE = re.compile(r"(?m)^\{\s*$")

COUNT_FIELDS = (
    "candidate_rows",
    "probed_rows",
    "verified_probe_rows",
    "updated_rows",
)


@dataclass(frozen=True)
class DomainLine:
    domain: str
    unverified_http_rows: int
    position: int
    line_number: int


@dataclass(frozen=True)
class VerificationBlock:
    payload: dict[str, Any]
    position: int
    line_number: int


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _line_number(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def _as_int(value: object, *, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _pct(part: int, total: int) -> float:
    if total == 0:
        return 100.0
    return round((part / total) * 100, 2)


def _is_verification_payload(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return (
        "candidate_rows" in value
        and "verified_probe_rows" in value
        and "updated_rows" in value
        and isinstance(value.get("outcomes"), dict)
    )


def _verification_blocks(text: str) -> list[VerificationBlock]:
    decoder = json.JSONDecoder()
    blocks: list[VerificationBlock] = []
    index = 0

    while True:
        index = text.find("{", index)
        if index == -1:
            break
        try:
            payload, end_offset = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index += 1
            continue
        if _is_verification_payload(payload):
            blocks.append(
                VerificationBlock(
                    payload=payload,
                    position=index,
                    line_number=_line_number(text, index),
                )
            )
        index += end_offset
    return blocks


def _domain_lines(text: str) -> list[DomainLine]:
    return [
        DomainLine(
            domain=match.group("domain").strip().lower(),
            unverified_http_rows=int(match.group("unverified_http_rows")),
            position=match.start(),
            line_number=_line_number(text, match.start()),
        )
        for match in DOMAIN_RE.finditer(text)
    ]


def _header(text: str) -> dict[str, int | None]:
    match = HEADER_RE.search(text)
    if match is None:
        return {
            "shard_id": None,
            "planned_domain_count": None,
            "planned_unverified_http_rows": None,
        }
    return {
        "shard_id": int(match.group("shard_id")),
        "planned_domain_count": int(match.group("domain_count")),
        "planned_unverified_http_rows": int(match.group("unverified_http_rows")),
    }


def _complete_marker_seen(text: str, shard_id: int | None) -> bool:
    if shard_id is None:
        return COMPLETE_RE.search(text) is not None
    return any(int(match.group("shard_id")) == shard_id for match in COMPLETE_RE.finditer(text))


def _malformed_top_level_json_count(text: str, blocks: list[VerificationBlock]) -> int:
    block_positions = {block.position for block in blocks}
    return sum(
        1
        for match in TOP_LEVEL_JSON_START_RE.finditer(text)
        if match.start() not in block_positions
    )


def parse_shard_log(path: Path) -> dict[str, Any]:
    """Parse one shard log into counts and incomplete-domain indicators."""
    text = path.read_text(encoding="utf-8", errors="replace")
    header = _header(text)
    shard_id = header["shard_id"]
    domain_lines = _domain_lines(text)
    domain_positions = [line.position for line in domain_lines]
    blocks = _verification_blocks(text)

    assigned_domain_indexes: dict[int, VerificationBlock] = {}
    unpaired_json_blocks = 0
    for block in blocks:
        domain_index = bisect.bisect_right(domain_positions, block.position) - 1
        if domain_index < 0 or domain_index in assigned_domain_indexes:
            unpaired_json_blocks += 1
            continue
        assigned_domain_indexes[domain_index] = block

    outcomes: Counter[str] = Counter()
    methods: Counter[str] = Counter()
    count_totals: Counter[str] = Counter()
    observed_db_bounds: dict[str, int | None] = {
        "last_verified_non_null_before_min": None,
        "last_verified_non_null_after_max": None,
        "last_verified_null_before_max": None,
        "last_verified_null_after_min": None,
    }

    for block in assigned_domain_indexes.values():
        payload = block.payload
        for field in COUNT_FIELDS:
            count_totals[field] += _as_int(payload.get(field))
        outcomes.update(
            {str(key): _as_int(value) for key, value in dict(payload.get("outcomes") or {}).items()}
        )
        methods.update(
            {str(key): _as_int(value) for key, value in dict(payload.get("methods") or {}).items()}
        )

        before_non_null = payload.get("last_verified_non_null_before")
        after_non_null = payload.get("last_verified_non_null_after")
        before_null = payload.get("last_verified_null_before")
        after_null = payload.get("last_verified_null_after")
        if before_non_null is not None:
            current = observed_db_bounds["last_verified_non_null_before_min"]
            value = _as_int(before_non_null)
            observed_db_bounds["last_verified_non_null_before_min"] = (
                value if current is None else min(current, value)
            )
        if after_non_null is not None:
            current = observed_db_bounds["last_verified_non_null_after_max"]
            value = _as_int(after_non_null)
            observed_db_bounds["last_verified_non_null_after_max"] = (
                value if current is None else max(current, value)
            )
        if before_null is not None:
            current = observed_db_bounds["last_verified_null_before_max"]
            value = _as_int(before_null)
            observed_db_bounds["last_verified_null_before_max"] = (
                value if current is None else max(current, value)
            )
        if after_null is not None:
            current = observed_db_bounds["last_verified_null_after_min"]
            value = _as_int(after_null)
            observed_db_bounds["last_verified_null_after_min"] = (
                value if current is None else min(current, value)
            )

    processed_domain_count = len(assigned_domain_indexes)
    pending_started_domains = [
        {
            "domain": line.domain,
            "unverified_http_rows": line.unverified_http_rows,
            "line_number": line.line_number,
        }
        for index, line in enumerate(domain_lines)
        if index not in assigned_domain_indexes
    ]
    planned_domain_count = header["planned_domain_count"]
    planned_rows = header["planned_unverified_http_rows"]
    domains_remaining = (
        max(0, planned_domain_count - processed_domain_count)
        if planned_domain_count is not None
        else None
    )
    unlogged_remaining_domain_count = (
        max(0, planned_domain_count - len(domain_lines))
        if planned_domain_count is not None
        else None
    )
    rows_remaining = (
        max(0, planned_rows - count_totals["candidate_rows"]) if planned_rows is not None else None
    )
    complete_marker_seen = _complete_marker_seen(text, shard_id)
    complete = (
        complete_marker_seen
        and domains_remaining == 0
        and not pending_started_domains
        and unpaired_json_blocks == 0
    )

    return {
        "path": str(path),
        "shard_id": shard_id,
        "planned_domain_count": planned_domain_count,
        "planned_unverified_http_rows": planned_rows,
        "domain_lines_seen": len(domain_lines),
        "domains_processed": processed_domain_count,
        "domains_remaining_inferable": domains_remaining,
        "domains_started_without_result_count": len(pending_started_domains),
        "domains_started_without_result": pending_started_domains[:25],
        "unlogged_remaining_domain_count": unlogged_remaining_domain_count,
        "candidate_rows": count_totals["candidate_rows"],
        "probed_rows": count_totals["probed_rows"],
        "verified_probe_rows": count_totals["verified_probe_rows"],
        "updated_rows": count_totals["updated_rows"],
        "candidate_rows_remaining_inferable": rows_remaining,
        "outcomes": dict(sorted(outcomes.items())),
        "methods": dict(sorted(methods.items())),
        "observed_db_bounds_from_log": observed_db_bounds,
        "json_result_blocks": len(blocks),
        "unpaired_json_blocks": unpaired_json_blocks,
        "malformed_top_level_json_blocks": _malformed_top_level_json_count(text, blocks),
        "complete_marker_seen": complete_marker_seen,
        "complete": complete,
    }


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


def _single_row_int(row: sqlite3.Row | None, field: str) -> int:
    if row is None:
        return 0
    return _as_int(row[field])


def collect_db_counts(
    conn: sqlite3.Connection,
    *,
    quick_threshold: int = 50,
) -> dict[str, Any]:
    """Collect current ``am_source`` verification counts without mutation."""
    if not _table_exists(conn, "am_source"):
        raise ValueError("am_source table is missing")

    missing = sorted(REQUIRED_COLUMNS - _columns(conn, "am_source"))
    if missing:
        raise ValueError(f"am_source is missing required columns: {missing}")
    if quick_threshold <= 0:
        raise ValueError("quick_threshold must be positive")

    totals = conn.execute(
        f"""
        SELECT COUNT(*) AS rows,
               SUM(CASE WHEN {VERIFIED_SQL} THEN 1 ELSE 0 END) AS verified_rows,
               SUM(CASE WHEN NOT {VERIFIED_SQL} THEN 1 ELSE 0 END) AS unverified_rows,
               SUM(CASE WHEN source_url IS NOT NULL AND {HTTP_URL_SQL} THEN 1 ELSE 0 END)
                 AS http_rows,
               SUM(CASE WHEN source_url IS NOT NULL AND {HTTP_URL_SQL} AND {VERIFIED_SQL}
                        THEN 1 ELSE 0 END) AS http_verified_rows,
               SUM(CASE WHEN source_url IS NOT NULL AND {HTTP_URL_SQL} AND NOT {VERIFIED_SQL}
                        THEN 1 ELSE 0 END) AS http_unverified_rows,
               SUM(CASE WHEN source_url IS NULL OR NOT {HTTP_URL_SQL} THEN 1 ELSE 0 END)
                 AS non_http_rows,
               SUM(CASE WHEN (source_url IS NULL OR NOT {HTTP_URL_SQL}) AND {VERIFIED_SQL}
                        THEN 1 ELSE 0 END) AS non_http_verified_rows,
               SUM(CASE WHEN (source_url IS NULL OR NOT {HTTP_URL_SQL}) AND NOT {VERIFIED_SQL}
                        THEN 1 ELSE 0 END) AS non_http_unverified_rows,
               COUNT(DISTINCT CASE
                   WHEN domain IS NOT NULL AND trim(domain) <> ''
                   THEN lower(trim(domain))
               END) AS stored_domain_count,
               SUM(CASE WHEN source_url IS NOT NULL AND {HTTP_URL_SQL}
                          AND domain IS NOT NULL AND trim(domain) <> ''
                        THEN 1 ELSE 0 END) AS http_rows_with_stored_domain,
               SUM(CASE WHEN source_url IS NOT NULL AND {HTTP_URL_SQL}
                          AND (domain IS NULL OR trim(domain) = '')
                        THEN 1 ELSE 0 END) AS http_rows_without_stored_domain,
               SUM(CASE WHEN source_url IS NOT NULL AND {HTTP_URL_SQL}
                          AND NOT {VERIFIED_SQL}
                          AND domain IS NOT NULL AND trim(domain) <> ''
                        THEN 1 ELSE 0 END) AS http_unverified_rows_with_stored_domain,
               SUM(CASE WHEN source_url IS NOT NULL AND {HTTP_URL_SQL}
                          AND NOT {VERIFIED_SQL}
                          AND (domain IS NULL OR trim(domain) = '')
                        THEN 1 ELSE 0 END) AS http_unverified_rows_without_stored_domain
          FROM am_source
        """
    ).fetchone()

    remaining_domains = conn.execute(
        f"""
        SELECT COUNT(*) AS domain_count,
               COALESCE(SUM(unverified_http_rows), 0) AS unverified_http_rows,
               COALESCE(MAX(unverified_http_rows), 0) AS max_unverified_http_rows
          FROM (
                SELECT lower(trim(domain)) AS domain,
                       COUNT(*) AS unverified_http_rows
                  FROM am_source
                 WHERE source_url IS NOT NULL
                   AND {HTTP_URL_SQL}
                   AND NOT {VERIFIED_SQL}
                   AND domain IS NOT NULL
                   AND trim(domain) <> ''
                 GROUP BY lower(trim(domain))
          )
        """
    ).fetchone()

    quick_domains = conn.execute(
        f"""
        SELECT COUNT(*) AS domain_count,
               COALESCE(SUM(unverified_http_rows), 0) AS unverified_http_rows
          FROM (
                SELECT lower(trim(domain)) AS domain,
                       COUNT(*) AS unverified_http_rows
                  FROM am_source
                 WHERE source_url IS NOT NULL
                   AND {HTTP_URL_SQL}
                   AND NOT {VERIFIED_SQL}
                   AND domain IS NOT NULL
                   AND trim(domain) <> ''
                 GROUP BY lower(trim(domain))
                HAVING COUNT(*) <= ?
          )
        """,
        (quick_threshold,),
    ).fetchone()

    over_threshold_domains = conn.execute(
        f"""
        SELECT COUNT(*) AS domain_count,
               COALESCE(SUM(unverified_http_rows), 0) AS unverified_http_rows
          FROM (
                SELECT lower(trim(domain)) AS domain,
                       COUNT(*) AS unverified_http_rows
                  FROM am_source
                 WHERE source_url IS NOT NULL
                   AND {HTTP_URL_SQL}
                   AND NOT {VERIFIED_SQL}
                   AND domain IS NOT NULL
                   AND trim(domain) <> ''
                 GROUP BY lower(trim(domain))
                HAVING COUNT(*) > ?
          )
        """,
        (quick_threshold,),
    ).fetchone()

    rows = _single_row_int(totals, "rows")
    verified_rows = _single_row_int(totals, "verified_rows")
    http_rows = _single_row_int(totals, "http_rows")
    http_verified_rows = _single_row_int(totals, "http_verified_rows")
    non_http_rows = _single_row_int(totals, "non_http_rows")
    non_http_verified_rows = _single_row_int(totals, "non_http_verified_rows")

    return {
        "rows": rows,
        "verified_rows": verified_rows,
        "unverified_rows": _single_row_int(totals, "unverified_rows"),
        "verification_coverage_pct": _pct(verified_rows, rows),
        "http_rows": http_rows,
        "http_verified_rows": http_verified_rows,
        "http_unverified_rows": _single_row_int(totals, "http_unverified_rows"),
        "http_verification_coverage_pct": _pct(http_verified_rows, http_rows),
        "non_http_rows": non_http_rows,
        "non_http_verified_rows": non_http_verified_rows,
        "non_http_unverified_rows": _single_row_int(totals, "non_http_unverified_rows"),
        "non_http_verification_coverage_pct": _pct(non_http_verified_rows, non_http_rows),
        "stored_domain_count": _single_row_int(totals, "stored_domain_count"),
        "http_rows_with_stored_domain": _single_row_int(
            totals,
            "http_rows_with_stored_domain",
        ),
        "http_rows_without_stored_domain": _single_row_int(
            totals,
            "http_rows_without_stored_domain",
        ),
        "http_unverified_rows_with_stored_domain": _single_row_int(
            totals,
            "http_unverified_rows_with_stored_domain",
        ),
        "http_unverified_rows_without_stored_domain": _single_row_int(
            totals,
            "http_unverified_rows_without_stored_domain",
        ),
        "remaining_http_domain_count": _single_row_int(remaining_domains, "domain_count"),
        "remaining_http_domain_unverified_rows": _single_row_int(
            remaining_domains,
            "unverified_http_rows",
        ),
        "remaining_http_domain_max_unverified_rows": _single_row_int(
            remaining_domains,
            "max_unverified_http_rows",
        ),
        "quick_threshold_unverified_http_rows_per_domain": quick_threshold,
        "remaining_quick_domain_count": _single_row_int(quick_domains, "domain_count"),
        "remaining_quick_unverified_http_rows": _single_row_int(
            quick_domains,
            "unverified_http_rows",
        ),
        "remaining_over_threshold_domain_count": _single_row_int(
            over_threshold_domains,
            "domain_count",
        ),
        "remaining_over_threshold_unverified_http_rows": _single_row_int(
            over_threshold_domains,
            "unverified_http_rows",
        ),
    }


def _aggregate_shards(shards: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes: Counter[str] = Counter()
    methods: Counter[str] = Counter()
    totals: Counter[str] = Counter()

    for shard in shards:
        for field in (
            "planned_domain_count",
            "planned_unverified_http_rows",
            "domain_lines_seen",
            "domains_processed",
            "domains_started_without_result_count",
            "unlogged_remaining_domain_count",
            "candidate_rows",
            "probed_rows",
            "verified_probe_rows",
            "updated_rows",
            "json_result_blocks",
            "unpaired_json_blocks",
            "malformed_top_level_json_blocks",
        ):
            value = shard.get(field)
            if value is not None:
                totals[field] += _as_int(value)
        if shard.get("domains_remaining_inferable") is not None:
            totals["domains_remaining_inferable"] += _as_int(shard["domains_remaining_inferable"])
        if shard.get("candidate_rows_remaining_inferable") is not None:
            totals["candidate_rows_remaining_inferable"] += _as_int(
                shard["candidate_rows_remaining_inferable"]
            )
        outcomes.update(shard.get("outcomes") or {})
        methods.update(shard.get("methods") or {})

    return {
        **dict(totals),
        "outcomes": dict(sorted(outcomes.items())),
        "methods": dict(sorted(methods.items())),
        "complete_shard_count": sum(1 for shard in shards if shard.get("complete")),
        "incomplete_shard_count": sum(1 for shard in shards if not shard.get("complete")),
    }


def _completion_status(
    *,
    shards: list[dict[str, Any]],
    db_counts: dict[str, Any],
) -> dict[str, Any]:
    if not shards:
        return {
            "A5_complete": False,
            "complete": False,
            "reason": "No source verification shard logs were found.",
        }

    remaining_http_rows = int(db_counts["http_unverified_rows"])
    incomplete_shards = [shard for shard in shards if not shard.get("complete")]
    if remaining_http_rows > 0:
        return {
            "A5_complete": False,
            "complete": False,
            "reason": (
                f"{remaining_http_rows} HTTP(S) am_source rows still have "
                "last_verified missing in the current database."
            ),
        }
    if incomplete_shards:
        return {
            "A5_complete": False,
            "complete": False,
            "reason": (
                f"{len(incomplete_shards)} shard logs are missing a complete marker "
                "or have inferred remaining domains."
            ),
        }
    return {
        "A5_complete": True,
        "complete": True,
        "reason": "Current DB has no unverified HTTP(S) am_source rows and all shard logs completed.",
    }


def analyze_source_verification_logs(
    *,
    db_path: Path = DEFAULT_DB,
    log_dir: Path = DEFAULT_LOG_DIR,
    run_date: str = RUN_DATE,
    quick_threshold: int = 50,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Analyze shard logs and current DB counts."""
    log_paths = sorted(log_dir.glob(f"source_verification_shard_*_{run_date}.log"))
    shards = [parse_shard_log(path) for path in log_paths]
    with _connect_readonly(db_path) as conn:
        db_counts = collect_db_counts(conn, quick_threshold=quick_threshold)
    log_totals = _aggregate_shards(shards)
    completion_status = _completion_status(shards=shards, db_counts=db_counts)

    return {
        "ok": True,
        "run_date": run_date,
        "generated_at": generated_at or _utc_now(),
        "read_mode": {
            "network_fetch_performed": False,
            "db_mutation_performed": False,
        },
        "inputs": {
            "db": str(db_path),
            "log_dir": str(log_dir),
            "log_glob": f"source_verification_shard_*_{run_date}.log",
            "log_count": len(log_paths),
        },
        "log_totals": log_totals,
        "db_counts": db_counts,
        "completion_status": completion_status,
        "shards": shards,
    }


def write_json_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _compact_counter(counter: dict[str, int], *, limit: int = 6) -> str:
    if not counter:
        return "-"
    rows = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{key}={value}" for key, value in rows[:limit])


def render_markdown(report: dict[str, Any]) -> str:
    status = report["completion_status"]
    log_totals = report["log_totals"]
    db_counts = report["db_counts"]

    lines = [
        f"# A5 Source Verification Shard Summary ({report['run_date']})",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Gate",
        "",
        f"- A5 complete: {'yes' if status['A5_complete'] else 'no'}",
        f"- Reason: {status['reason']}",
        "- Network fetch performed by analyzer: no",
        "- DB mutation performed by analyzer: no",
        "",
        "## Log Totals",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Log files | {report['inputs']['log_count']} |",
        f"| Planned domains | {log_totals.get('planned_domain_count', 0)} |",
        f"| Domains with JSON result | {log_totals.get('domains_processed', 0)} |",
        f"| Domains remaining, inferred | {log_totals.get('domains_remaining_inferable', 0)} |",
        f"| Domain lines seen | {log_totals.get('domain_lines_seen', 0)} |",
        f"| Started without result | {log_totals.get('domains_started_without_result_count', 0)} |",
        f"| Planned unverified HTTP rows | {log_totals.get('planned_unverified_http_rows', 0)} |",
        f"| Candidate rows probed | {log_totals.get('candidate_rows', 0)} |",
        f"| Verified probe rows | {log_totals.get('verified_probe_rows', 0)} |",
        f"| Updated rows | {log_totals.get('updated_rows', 0)} |",
        f"| Candidate rows remaining, inferred | {log_totals.get('candidate_rows_remaining_inferable', 0)} |",
        "",
        f"Outcomes: {_compact_counter(log_totals.get('outcomes', {}))}",
        "",
        "## Current DB Counts",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| am_source rows | {db_counts['rows']} |",
        f"| Verified rows | {db_counts['verified_rows']} |",
        f"| Unverified rows | {db_counts['unverified_rows']} |",
        f"| Verification coverage pct | {db_counts['verification_coverage_pct']} |",
        f"| HTTP rows | {db_counts['http_rows']} |",
        f"| HTTP verified rows | {db_counts['http_verified_rows']} |",
        f"| HTTP unverified rows | {db_counts['http_unverified_rows']} |",
        f"| HTTP verification coverage pct | {db_counts['http_verification_coverage_pct']} |",
        f"| Remaining HTTP domains | {db_counts['remaining_http_domain_count']} |",
        f"| Remaining quick domains <= threshold | {db_counts['remaining_quick_domain_count']} |",
        f"| Remaining quick HTTP rows <= threshold | {db_counts['remaining_quick_unverified_http_rows']} |",
        f"| Remaining over-threshold domains | {db_counts['remaining_over_threshold_domain_count']} |",
        f"| HTTP unverified rows without stored domain | {db_counts['http_unverified_rows_without_stored_domain']} |",
        "",
        "## Shards",
        "",
        "| Shard | Planned domains | Processed | Remaining | Candidates | Verified | Updated | Complete | Top outcomes |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | --- |",
    ]

    for shard in report["shards"]:
        lines.append(
            "| {shard_id} | {planned} | {processed} | {remaining} | {candidates} | "
            "{verified} | {updated} | {complete} | {outcomes} |".format(
                shard_id=shard["shard_id"] if shard["shard_id"] is not None else "-",
                planned=shard["planned_domain_count"]
                if shard["planned_domain_count"] is not None
                else "-",
                processed=shard["domains_processed"],
                remaining=shard["domains_remaining_inferable"]
                if shard["domains_remaining_inferable"] is not None
                else "-",
                candidates=shard["candidate_rows"],
                verified=shard["verified_probe_rows"],
                updated=shard["updated_rows"],
                complete="yes" if shard["complete"] else "no",
                outcomes=_compact_counter(shard["outcomes"], limit=4),
            )
        )

    pending = [
        (shard["shard_id"], domain)
        for shard in report["shards"]
        for domain in shard["domains_started_without_result"]
    ]
    if pending:
        lines.extend(
            [
                "",
                "## Started Without Result",
                "",
            ]
        )
        for shard_id, domain in pending[:25]:
            lines.append(
                "- shard {shard}: {domain} ({rows} planned rows, line {line})".format(
                    shard=shard_id,
                    domain=domain["domain"],
                    rows=domain["unverified_http_rows"],
                    line=domain["line_number"],
                )
            )
        if len(pending) > 25:
            lines.append(f"- ... {len(pending) - 25} more")

    return "\n".join(lines) + "\n"


def write_markdown_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(report), encoding="utf-8")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--run-date", default=RUN_DATE)
    parser.add_argument("--quick-threshold", type=int, default=50)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--md-output", type=Path, default=DEFAULT_MD_OUTPUT)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = analyze_source_verification_logs(
        db_path=args.db,
        log_dir=args.log_dir,
        run_date=args.run_date,
        quick_threshold=args.quick_threshold,
    )
    write_json_report(report, args.json_output)
    write_markdown_report(report, args.md_output)

    if args.print_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"log_count={report['inputs']['log_count']}")
        print(f"domains_processed={report['log_totals'].get('domains_processed', 0)}")
        print(f"updated_rows={report['log_totals'].get('updated_rows', 0)}")
        print(f"http_unverified_rows={report['db_counts']['http_unverified_rows']}")
        print(f"A5_complete={report['completion_status']['A5_complete']}")
        print(f"json_output={args.json_output}")
        print(f"md_output={args.md_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
