#!/usr/bin/env python3
"""Report-only liveness scan for Tier B/C program URLs with unknown status.

E3 is an audit helper: it reads bounded candidate rows from ``data/jpintel.db``,
probes with a transparent User-Agent, writes a CSV report, and never mutates the
source database.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.robotparser
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.http import (  # noqa: E402
    DEFAULT_PER_HOST_DELAY_SEC,
    DEFAULT_TIMEOUT_SEC,
)

DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "tier_bc_url_liveness_2026-05-01.csv"
TRANSPARENT_USER_AGENT = "jpcite-research/1.0 (+https://jpcite.com/about)"
DEFAULT_LIMIT = 100
UNKNOWN_STATUSES = ("", "unknown")


@dataclass(frozen=True)
class ProgramUrlCandidate:
    unified_id: str
    primary_name: str
    tier: str
    source_url: str
    domain: str
    previous_status: str


@dataclass(frozen=True)
class LivenessResult:
    unified_id: str
    primary_name: str
    tier: str
    source_url: str
    domain: str
    previous_status: str
    final_url: str
    status_code: int | None
    classification: str
    method: str | None
    error: str | None = None


class UrlLivenessProber(Protocol):
    def probe(self, row: ProgramUrlCandidate) -> LivenessResult: ...


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


def _is_http_url(url: str | None) -> bool:
    if not url:
        return False
    return urllib.parse.urlparse(url.strip()).scheme.lower() in {"http", "https"}


def _host(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower()


def classify_liveness(status_code: int, *, final_url: str, original_url: str) -> str:
    if 200 <= status_code < 300:
        if final_url.rstrip("/") != original_url.rstrip("/"):
            return "ok_redirect"
        return "ok"
    if status_code in {401, 403, 429}:
        return "blocked"
    if 300 <= status_code < 400:
        return "redirect"
    if status_code in {404, 410}:
        return "hard_404"
    if 400 <= status_code < 500:
        return "client_error"
    if status_code >= 500:
        return "server_error"
    return "other_status"


def load_unknown_tier_bc_candidates(
    conn: sqlite3.Connection,
    *,
    limit: int = DEFAULT_LIMIT,
    domain: str | None = None,
) -> list[ProgramUrlCandidate]:
    """Load Tier B/C program URL candidates without mutating the database."""
    if limit <= 0:
        return []

    clauses = [
        "tier IN ('B', 'C')",
        "(source_url LIKE 'http://%' OR source_url LIKE 'https://%')",
        "(source_url_status IS NULL OR TRIM(source_url_status) = '' "
        "OR LOWER(TRIM(source_url_status)) = 'unknown')",
    ]
    params: list[Any] = []
    if domain:
        clauses.append("LOWER(source_url) LIKE ?")
        params.append(f"%://{domain.lower()}%")

    sql = (
        "SELECT unified_id, primary_name, tier, source_url, "
        "COALESCE(source_url_status, '') AS previous_status "
        "FROM programs WHERE "
        + " AND ".join(clauses)
        + " ORDER BY tier, unified_id LIMIT ?"
    )
    params.append(limit)

    rows: list[ProgramUrlCandidate] = []
    for row in conn.execute(sql, params).fetchall():
        url = str(row["source_url"] or "").strip()
        if not _is_http_url(url):
            continue
        rows.append(
            ProgramUrlCandidate(
                unified_id=str(row["unified_id"]),
                primary_name=str(row["primary_name"] or ""),
                tier=str(row["tier"] or ""),
                source_url=url,
                domain=_host(url),
                previous_status=str(row["previous_status"] or ""),
            )
        )
    return rows


class TransparentUserAgentLivenessProber:
    def __init__(
        self,
        *,
        user_agent: str = TRANSPARENT_USER_AGENT,
        per_host_delay_sec: float = DEFAULT_PER_HOST_DELAY_SEC,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        respect_robots: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._ua = user_agent
        self._per_host_delay = per_host_delay_sec
        self._respect_robots = respect_robots
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Language": "ja,en;q=0.5"},
            timeout=timeout_sec,
            follow_redirects=True,
            transport=transport,
        )
        self._host_clock: dict[str, float] = {}
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> TransparentUserAgentLivenessProber:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _pace_host(self, url: str) -> None:
        host = _host(url)
        now = time.monotonic()
        last = self._host_clock.get(host)
        if last is not None:
            wait = self._per_host_delay - (now - last)
            if wait > 0:
                time.sleep(wait)
        self._host_clock[host] = time.monotonic()

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        scheme = parsed.scheme or "https"
        key = f"{scheme}://{host}"
        if key in self._robots_cache:
            return self._robots_cache[key]

        rp = urllib.robotparser.RobotFileParser()
        robots_url = f"{key}/robots.txt"
        try:
            self._pace_host(robots_url)
            resp = self._client.get(robots_url, timeout=5.0)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
                self._robots_cache[key] = rp
                return rp
        except httpx.HTTPError:
            pass
        self._robots_cache[key] = None
        return None

    def _robots_allowed(self, url: str) -> bool:
        if not self._respect_robots:
            return True
        rp = self._robots_for(url)
        if rp is None:
            return True
        try:
            return rp.can_fetch(self._ua, url)
        except Exception:
            return True

    def _request(self, method: str, url: str) -> httpx.Response:
        self._pace_host(url)
        if method == "GET":
            return self._client.get(url, headers={"Range": "bytes=0-0"})
        return self._client.head(url)

    def probe(self, row: ProgramUrlCandidate) -> LivenessResult:
        url = row.source_url
        if not _is_http_url(url):
            return LivenessResult(
                **asdict(row),
                final_url=url,
                status_code=None,
                classification="non_http",
                method=None,
            )
        if not self._robots_allowed(url):
            return LivenessResult(
                **asdict(row),
                final_url=url,
                status_code=None,
                classification="robots_disallow",
                method=None,
            )
        try:
            resp = self._request("HEAD", url)
            method = "HEAD"
            if resp.status_code in {405, 501}:
                resp = self._request("GET", url)
                method = "GET"
            final_url = str(resp.url)
            return LivenessResult(
                **asdict(row),
                final_url=final_url,
                status_code=resp.status_code,
                classification=classify_liveness(
                    resp.status_code,
                    final_url=final_url,
                    original_url=url,
                ),
                method=method,
            )
        except httpx.HTTPError as exc:
            return LivenessResult(
                **asdict(row),
                final_url=url,
                status_code=None,
                classification="transport_error",
                method="HEAD",
                error=f"{type(exc).__name__}: {exc}",
            )


def write_results_csv(path: Path, results: list[LivenessResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(LivenessResult.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))


def scan_program_url_liveness(
    candidates: list[ProgramUrlCandidate],
    *,
    prober: UrlLivenessProber,
    output: Path,
) -> dict[str, Any]:
    results = [prober.probe(row) for row in candidates]
    write_results_csv(output, results)
    classifications = Counter(result.classification for result in results)
    statuses = Counter(str(result.status_code) if result.status_code is not None else "none" for result in results)
    return {
        "mode": "report_only",
        "generated_at": _utc_now(),
        "candidate_rows": len(candidates),
        "probed_rows": len(results),
        "output": str(output),
        "user_agent": TRANSPARENT_USER_AGENT,
        "classifications": dict(sorted(classifications.items())),
        "status_codes": dict(sorted(statuses.items())),
        "sample_results": [asdict(result) for result in results[:10]],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Bounded probe row count. Use 0 to only write an empty report.",
    )
    parser.add_argument("--domain", default=None)
    parser.add_argument(
        "--per-host-delay-sec",
        type=float,
        default=DEFAULT_PER_HOST_DELAY_SEC,
        help="Default 1.0 keeps the run at <=1 req/sec/domain.",
    )
    parser.add_argument("--timeout-sec", type=float, default=DEFAULT_TIMEOUT_SEC)
    parser.add_argument(
        "--ignore-robots",
        action="store_true",
        help="Debug only. Default respects robots.txt.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    with _connect_readonly(args.db) as conn:
        candidates = load_unknown_tier_bc_candidates(
            conn,
            limit=args.limit,
            domain=args.domain,
        )

    with TransparentUserAgentLivenessProber(
        per_host_delay_sec=args.per_host_delay_sec,
        timeout_sec=args.timeout_sec,
        respect_robots=not args.ignore_robots,
    ) as prober:
        result = scan_program_url_liveness(candidates, prober=prober, output=args.output)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"candidate_rows={result['candidate_rows']}")
        print(f"probed_rows={result['probed_rows']}")
        print(f"classifications={result['classifications']}")
        print(f"output={result['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
