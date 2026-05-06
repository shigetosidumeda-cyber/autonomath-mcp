#!/usr/bin/env python3
"""Build a read-only Tier B/C URL liveness full-scan plan.

This is an E3 planning/report helper. It reads local SQLite plus existing
``analysis_wave18`` liveness artifacts, estimates full-scan work, and writes a
JSON report. It never probes URLs and never mutates the source database.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import sys
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_ANALYSIS_DIR = REPO_ROOT / "analysis_wave18"
DEFAULT_BOUNDED_SCAN_CSV = DEFAULT_ANALYSIS_DIR / "tier_bc_url_liveness_2026-05-01.csv"
DEFAULT_OUTPUT = DEFAULT_ANALYSIS_DIR / "tier_bc_liveness_plan_2026-05-01.json"
DEFAULT_SAMPLE_LIMIT = 20
DEFAULT_SHARD_TARGET_ROWS = 750
MAX_PER_DOMAIN_RPS = 1.0
UNKNOWN_STATUSES = {"", "unknown"}
LIVE_CLASSIFICATIONS = {"ok", "ok_redirect"}
CONFIRMED_BROKEN_CLASSIFICATIONS = {"hard_404"}


@dataclass(frozen=True)
class CandidateRow:
    unified_id: str
    primary_name: str
    tier: str
    source_url: str
    domain: str
    previous_status: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _normalize_status(value: object) -> str:
    return str(value or "").strip().lower()


def _is_unknown_status(value: object) -> bool:
    return _normalize_status(value) in UNKNOWN_STATUSES


def _is_http_url(url: str | None) -> bool:
    if not url:
        return False
    return urllib.parse.urlsplit(url.strip()).scheme.lower() in {"http", "https"}


def _domain(url: str) -> str:
    return (urllib.parse.urlsplit(url.strip()).hostname or "").lower().rstrip(".")


def _duration(seconds: int) -> str:
    if seconds <= 0:
        return "0s"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _estimate_seconds(requests: int, per_domain_rps: float) -> int:
    if per_domain_rps <= 0 or per_domain_rps > MAX_PER_DOMAIN_RPS:
        raise ValueError("per_domain_rps must be > 0 and <= 1.0")
    return math.ceil(requests / per_domain_rps)


def load_unknown_tier_bc_candidates(
    conn: sqlite3.Connection,
) -> tuple[list[CandidateRow], dict[str, Any]]:
    """Load unknown Tier B/C source URL rows without mutating SQLite."""
    rows = conn.execute(
        """
        SELECT unified_id, primary_name, tier, source_url,
               COALESCE(source_url_status, '') AS previous_status
        FROM programs
        WHERE tier IN ('B', 'C')
          AND (
              source_url_status IS NULL
              OR TRIM(source_url_status) = ''
              OR LOWER(TRIM(source_url_status)) = 'unknown'
          )
        ORDER BY tier, unified_id
        """
    ).fetchall()

    candidates: list[CandidateRow] = []
    skipped = Counter[str]()
    all_tier_counts = Counter[str]()

    for row in rows:
        tier = str(row["tier"] or "")
        all_tier_counts[tier] += 1
        url = str(row["source_url"] or "").strip()
        if not url:
            skipped["missing_source_url"] += 1
            continue
        if not _is_http_url(url):
            skipped["non_http_source_url"] += 1
            continue
        domain = _domain(url)
        if not domain:
            skipped["missing_domain"] += 1
            continue
        candidates.append(
            CandidateRow(
                unified_id=str(row["unified_id"]),
                primary_name=str(row["primary_name"] or ""),
                tier=tier,
                source_url=url,
                domain=domain,
                previous_status=str(row["previous_status"] or ""),
            )
        )

    candidate_tier_counts = Counter(row.tier for row in candidates)
    summary = {
        "tier_bc_unknown_source_url_status_rows": len(rows),
        "http_candidate_rows": len(candidates),
        "non_http_or_missing_unknown_rows": len(rows) - len(candidates),
        "skipped_unknown_rows": dict(sorted(skipped.items())),
        "unknown_rows_by_tier": dict(sorted(all_tier_counts.items())),
        "http_candidate_rows_by_tier": dict(sorted(candidate_tier_counts.items())),
    }
    return candidates, summary


def count_candidates_by_domain(candidates: list[CandidateRow]) -> list[dict[str, Any]]:
    tiers_by_domain: dict[str, Counter[str]] = defaultdict(Counter)
    urls_by_domain: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        tiers_by_domain[candidate.domain][candidate.tier] += 1
        urls_by_domain[candidate.domain].add(candidate.source_url)

    domain_counts: list[dict[str, Any]] = []
    for domain, tier_counts in tiers_by_domain.items():
        row_count = sum(tier_counts.values())
        domain_counts.append(
            {
                "domain": domain,
                "row_count": row_count,
                "tier_counts": dict(sorted(tier_counts.items())),
                "unique_source_url_count": len(urls_by_domain[domain]),
            }
        )
    return sorted(domain_counts, key=lambda item: (-int(item["row_count"]), str(item["domain"])))


def estimate_scan_duration(
    domain_counts: list[dict[str, Any]],
    *,
    per_domain_rps: float = MAX_PER_DOMAIN_RPS,
) -> dict[str, Any]:
    """Estimate sequential scan duration with no more than one request/sec/domain."""
    total_rows = sum(int(item["row_count"]) for item in domain_counts)
    domain_count = len(domain_counts)
    largest_domain = domain_counts[0] if domain_counts else {"domain": None, "row_count": 0}
    candidate_only_seconds = _estimate_seconds(total_rows, per_domain_rps)
    with_robots_seconds = _estimate_seconds(total_rows + domain_count, per_domain_rps)
    largest_domain_seconds = _estimate_seconds(int(largest_domain["row_count"]) + 1, per_domain_rps)
    return {
        "model": (
            "Planning estimate only: one HTTP liveness request per candidate row, "
            "plus a conservative one robots.txt request per unique domain. Actual "
            "wall time depends on latency, retries, and scanner ordering."
        ),
        "max_requests_per_second_per_domain": per_domain_rps,
        "candidate_rows": total_rows,
        "unique_domains": domain_count,
        "sequential_candidate_only_seconds": candidate_only_seconds,
        "sequential_candidate_only_human": _duration(candidate_only_seconds),
        "sequential_with_robots_seconds": with_robots_seconds,
        "sequential_with_robots_human": _duration(with_robots_seconds),
        "largest_domain": largest_domain["domain"],
        "largest_domain_rows": int(largest_domain["row_count"]),
        "largest_domain_min_seconds_with_robots": largest_domain_seconds,
        "largest_domain_min_human_with_robots": _duration(largest_domain_seconds),
    }


def build_domain_exclusive_shards(
    domain_counts: list[dict[str, Any]],
    *,
    target_rows_per_shard: int = DEFAULT_SHARD_TARGET_ROWS,
    per_domain_rps: float = MAX_PER_DOMAIN_RPS,
) -> list[dict[str, Any]]:
    """Greedy bin-pack domains so no domain appears in more than one shard."""
    if target_rows_per_shard <= 0:
        raise ValueError("target_rows_per_shard must be positive")

    buckets: list[list[dict[str, Any]]] = []
    bucket_rows: list[int] = []
    for item in domain_counts:
        row_count = int(item["row_count"])
        best_idx: int | None = None
        best_remaining: int | None = None
        for idx, current_rows in enumerate(bucket_rows):
            remaining = target_rows_per_shard - (current_rows + row_count)
            if remaining < 0:
                continue
            if best_remaining is None or remaining < best_remaining:
                best_idx = idx
                best_remaining = remaining
        if best_idx is None:
            buckets.append([item])
            bucket_rows.append(row_count)
        else:
            buckets[best_idx].append(item)
            bucket_rows[best_idx] += row_count

    shards: list[dict[str, Any]] = []
    for idx, bucket in enumerate(buckets, start=1):
        rows = sum(int(item["row_count"]) for item in bucket)
        domains = sorted(str(item["domain"]) for item in bucket)
        with_robots_seconds = _estimate_seconds(rows + len(domains), per_domain_rps)
        candidate_only_seconds = _estimate_seconds(rows, per_domain_rps)
        top_domains = sorted(
            bucket, key=lambda item: (-int(item["row_count"]), str(item["domain"]))
        )[:10]
        shards.append(
            {
                "shard_id": f"tier-bc-liveness-{idx:02d}",
                "row_count": rows,
                "domain_count": len(domains),
                "estimated_candidate_only_seconds": candidate_only_seconds,
                "estimated_candidate_only_human": _duration(candidate_only_seconds),
                "estimated_with_robots_seconds": with_robots_seconds,
                "estimated_with_robots_human": _duration(with_robots_seconds),
                "top_domains": [
                    {"domain": str(item["domain"]), "row_count": int(item["row_count"])}
                    for item in top_domains
                ],
                "domains": domains,
            }
        )
    return shards


def summarize_bounded_scan_csv(path: Path | None, *, universe_rows: int) -> dict[str, Any]:
    if path is None or not path.exists():
        return {
            "present": False,
            "path": str(path) if path is not None else None,
            "note": "No bounded Tier B/C liveness CSV was available.",
        }

    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    classification_counts = Counter(
        (row.get("classification") or "unknown").strip() or "unknown" for row in rows
    )
    status_counts = Counter((row.get("status_code") or "none").strip() or "none" for row in rows)
    method_counts = Counter((row.get("method") or "unknown").strip() or "unknown" for row in rows)
    domain_counts = Counter(
        (row.get("domain") or _domain(row.get("source_url") or "") or "unknown").strip()
        for row in rows
    )
    sample_rows = len(rows)
    live_rows = sum(
        classification_counts[classification] for classification in LIVE_CLASSIFICATIONS
    )
    confirmed_broken_rows = sum(
        classification_counts[classification] for classification in CONFIRMED_BROKEN_CLASSIFICATIONS
    )
    non_live_or_uncertain_rows = sample_rows - live_rows

    if sample_rows:
        confirmed_rate = confirmed_broken_rows / sample_rows
        non_live_uncertain_rate = non_live_or_uncertain_rows / sample_rows
        confirmed_estimate = round(universe_rows * confirmed_rate)
        at_risk_estimate = round(universe_rows * non_live_uncertain_rate)
    else:
        confirmed_rate = 0.0
        non_live_uncertain_rate = 0.0
        confirmed_estimate = 0
        at_risk_estimate = 0

    return {
        "present": True,
        "path": str(path),
        "sample_rows": sample_rows,
        "classification_distribution": dict(sorted(classification_counts.items())),
        "status_code_distribution": dict(sorted(status_counts.items())),
        "method_distribution": dict(sorted(method_counts.items())),
        "top_domains": [
            {"domain": domain, "row_count": count}
            for domain, count in domain_counts.most_common(10)
        ],
        "hidden_broken_extrapolation": {
            "universe_rows": universe_rows,
            "observed_confirmed_broken_rows": confirmed_broken_rows,
            "observed_confirmed_broken_rate": round(confirmed_rate, 6),
            "estimated_confirmed_broken_rows_if_representative": confirmed_estimate,
            "observed_non_live_or_uncertain_rows": non_live_or_uncertain_rows,
            "observed_non_live_or_uncertain_rate": round(non_live_uncertain_rate, 6),
            "estimated_at_risk_rows_if_all_uncertain_are_broken": at_risk_estimate,
            "uncertainty_note": (
                "The bounded scan is not proven random or domain-balanced. Only hard_404 "
                "is treated as confirmed broken; transport_error, blocked, server_error, "
                "and other non-live outcomes may be transient or crawler-specific. Use "
                "these numbers for planning/readiness only, not DB mutation."
            ),
        },
    }


def discover_liveness_artifacts(analysis_dir: Path) -> list[dict[str, Any]]:
    if not analysis_dir.exists():
        return []
    paths = sorted(
        {
            *analysis_dir.glob("*liveness*.csv"),
            *analysis_dir.glob("*liveness*.json"),
            *analysis_dir.glob("loops/**/*liveness*.json"),
            *analysis_dir.glob("loops/**/*liveness*.csv"),
        }
    )
    artifacts: list[dict[str, Any]] = []
    for path in paths:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        artifacts.append({"path": str(path), "bytes": size})
    return artifacts


def build_liveness_plan(
    conn: sqlite3.Connection,
    *,
    analysis_dir: Path = DEFAULT_ANALYSIS_DIR,
    bounded_scan_csv: Path | None = DEFAULT_BOUNDED_SCAN_CSV,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    shard_target_rows: int = DEFAULT_SHARD_TARGET_ROWS,
    per_domain_rps: float = MAX_PER_DOMAIN_RPS,
) -> dict[str, Any]:
    candidates, db_counts = load_unknown_tier_bc_candidates(conn)
    domain_counts = count_candidates_by_domain(candidates)
    estimate = estimate_scan_duration(domain_counts, per_domain_rps=per_domain_rps)
    shards = build_domain_exclusive_shards(
        domain_counts,
        target_rows_per_shard=shard_target_rows,
        per_domain_rps=per_domain_rps,
    )
    unique_urls = {candidate.source_url for candidate in candidates}

    return {
        "mode": "planning_readiness_only",
        "generated_at": _utc_now(),
        "inputs": {
            "database": "local SQLite connection",
            "analysis_dir": str(analysis_dir),
            "bounded_scan_csv": str(bounded_scan_csv) if bounded_scan_csv else None,
            "network_used": False,
            "db_mutation": False,
        },
        "db_counts": {
            **db_counts,
            "unique_domains": len(domain_counts),
            "unique_source_urls": len(unique_urls),
        },
        "scan_duration_estimate": estimate,
        "safe_batching_plan": {
            "strategy": (
                "Domain-exclusive greedy shards. A domain is assigned to exactly one shard, "
                "so parallel shard workers cannot exceed <=1 req/sec/domain if each worker "
                "keeps the same per-domain throttle."
            ),
            "shard_target_rows": shard_target_rows,
            "shard_count": len(shards),
            "domain_exclusive": True,
            "run_guidance": [
                "For zero coordination risk, run shards sequentially.",
                "If running shards concurrently, keep one worker per shard and preserve the scanner's per-domain throttle.",
                "Do not write scan outcomes into programs until a separate reviewed promotion step exists.",
            ],
            "shards": shards,
        },
        "domain_counts": domain_counts,
        "sample_candidate_rows": [asdict(candidate) for candidate in candidates[:sample_limit]],
        "bounded_scan_observations": summarize_bounded_scan_csv(
            bounded_scan_csv,
            universe_rows=len(candidates),
        ),
        "liveness_artifacts_seen": discover_liveness_artifacts(analysis_dir),
        "completion_status": "planning_readiness_only",
    }


def write_json_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--analysis-dir", type=Path, default=DEFAULT_ANALYSIS_DIR)
    parser.add_argument("--bounded-scan-csv", type=Path, default=DEFAULT_BOUNDED_SCAN_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-limit", type=int, default=DEFAULT_SAMPLE_LIMIT)
    parser.add_argument("--shard-target-rows", type=int, default=DEFAULT_SHARD_TARGET_ROWS)
    parser.add_argument("--per-domain-rps", type=float, default=MAX_PER_DOMAIN_RPS)
    parser.add_argument("--json", action="store_true", help="Print the full report to stdout.")
    args = parser.parse_args(argv)

    with _connect_readonly(args.db) as conn:
        report = build_liveness_plan(
            conn,
            analysis_dir=args.analysis_dir,
            bounded_scan_csv=args.bounded_scan_csv,
            sample_limit=args.sample_limit,
            shard_target_rows=args.shard_target_rows,
            per_domain_rps=args.per_domain_rps,
        )
    write_json_report(args.output, report)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        counts = report["db_counts"]
        estimate = report["scan_duration_estimate"]
        batching = report["safe_batching_plan"]
        print(f"output={args.output}")
        print(
            f"tier_bc_unknown_source_url_status_rows={counts['tier_bc_unknown_source_url_status_rows']}"
        )
        print(f"http_candidate_rows={counts['http_candidate_rows']}")
        print(f"unique_domains={counts['unique_domains']}")
        print(f"sequential_with_robots={estimate['sequential_with_robots_human']}")
        print(f"shard_count={batching['shard_count']}")
        print("completion_status=planning_readiness_only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
