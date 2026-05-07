#!/usr/bin/env python3
"""Re-probe previously blocked URLs with a transparent User-Agent.

D8 is an audit helper only: it records retry outcomes for URLs already marked
blocked elsewhere and never mutates the source database.
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

AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "blocked_url_reprobe_2026-05-01.csv"
TRANSPARENT_USER_AGENT = "jpcite-research/1.0 (+https://jpcite.com/about)"
DEFAULT_BLOCKED_STATUSES = (
    "blocked",
    "robots_blocked",
    "forbidden",
    "rate_limited",
    "broken",
)


@dataclass(frozen=True)
class BlockedUrlCandidate:
    source: str
    row_id: str
    source_url: str
    domain: str
    previous_status: str


@dataclass(frozen=True)
class ReprobeResult:
    source: str
    row_id: str
    source_url: str
    domain: str
    previous_status: str
    final_url: str
    status_code: int | None
    outcome: str
    method: str | None
    error: str | None = None


class UrlProber(Protocol):
    def probe(self, row: BlockedUrlCandidate) -> ReprobeResult: ...


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _is_http_url(url: str | None) -> bool:
    if not url:
        return False
    return urllib.parse.urlparse(url.strip()).scheme.lower() in {"http", "https"}


def _host(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower()


def classify_status(status_code: int, *, final_url: str, original_url: str) -> str:
    if status_code in {401, 403, 429}:
        return "still_blocked"
    if 200 <= status_code < 300:
        if final_url.rstrip("/") != original_url.rstrip("/"):
            return "reachable_redirect"
        return "reachable"
    if 300 <= status_code < 400:
        return "redirect"
    if status_code in {404, 410}:
        return "not_found"
    if 400 <= status_code < 500:
        return "client_error"
    if status_code >= 500:
        return "server_error"
    return "other_status"


def _placeholders(values: list[str]) -> str:
    return ", ".join("?" for _ in values)


def load_blocked_url_candidates(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
    domain: str | None = None,
    blocked_statuses: tuple[str, ...] = DEFAULT_BLOCKED_STATUSES,
) -> list[BlockedUrlCandidate]:
    """Load DB rows that are already marked blocked/broken, without mutation."""
    if limit is not None and limit <= 0:
        return []
    statuses = [status.lower() for status in blocked_statuses]
    out: list[BlockedUrlCandidate] = []

    if _table_exists(conn, "programs"):
        cols = _columns(conn, "programs")
        if {"unified_id", "source_url", "source_url_status"} <= cols:
            clauses = [
                "LOWER(COALESCE(source_url_status, '')) IN (" + _placeholders(statuses) + ")",
                "(source_url LIKE 'http://%' OR source_url LIKE 'https://%')",
            ]
            params: list[Any] = list(statuses)
            if domain:
                clauses.append("LOWER(source_url) LIKE ?")
                params.append(f"%://{domain.lower()}%")
            sql = (
                "SELECT unified_id AS row_id, source_url, source_url_status AS previous_status "
                "FROM programs WHERE " + " AND ".join(clauses) + " ORDER BY unified_id"
            )
            if limit is not None:
                sql += " LIMIT ?"
                params.append(limit)
            for row in conn.execute(sql, params).fetchall():
                url = str(row["source_url"] or "")
                out.append(
                    BlockedUrlCandidate(
                        source="programs",
                        row_id=str(row["row_id"]),
                        source_url=url,
                        domain=_host(url),
                        previous_status=str(row["previous_status"] or ""),
                    )
                )

    remaining = None if limit is None else max(0, limit - len(out))
    if remaining == 0:
        return out

    if _table_exists(conn, "am_source"):
        cols = _columns(conn, "am_source")
        if {"id", "source_url", "canonical_status"} <= cols:
            has_domain = "domain" in cols
            clauses = [
                "LOWER(COALESCE(canonical_status, '')) IN (" + _placeholders(statuses) + ")",
                "(source_url LIKE 'http://%' OR source_url LIKE 'https://%')",
            ]
            params = list(statuses)
            if domain and "domain" in cols:
                clauses.append("LOWER(COALESCE(domain, '')) = ?")
                params.append(domain.lower())
            sql = (
                "SELECT id AS row_id, source_url, canonical_status AS previous_status"
                + (", domain" if has_domain else "")
                + " FROM am_source WHERE "
                + " AND ".join(clauses)
                + " ORDER BY id"
            )
            if remaining is not None:
                sql += " LIMIT ?"
                params.append(remaining)
            for row in conn.execute(sql, params).fetchall():
                url = str(row["source_url"] or "")
                row_domain = str(row["domain"] or "") if has_domain else _host(url)
                out.append(
                    BlockedUrlCandidate(
                        source="am_source",
                        row_id=str(row["row_id"]),
                        source_url=url,
                        domain=row_domain,
                        previous_status=str(row["previous_status"] or ""),
                    )
                )
    return out


def load_candidates_csv(path: Path, *, limit: int | None = None) -> list[BlockedUrlCandidate]:
    rows: list[BlockedUrlCandidate] = []
    with path.open(encoding="utf-8", newline="") as f:
        for idx, row in enumerate(csv.DictReader(f), start=1):
            if limit is not None and len(rows) >= limit:
                break
            url = str(row.get("source_url") or row.get("url") or "").strip()
            if not _is_http_url(url):
                continue
            rows.append(
                BlockedUrlCandidate(
                    source=str(row.get("source") or "csv"),
                    row_id=str(row.get("row_id") or row.get("source_id") or idx),
                    source_url=url,
                    domain=str(row.get("domain") or _host(url)),
                    previous_status=str(row.get("previous_status") or row.get("outcome") or ""),
                )
            )
    return rows


class TransparentUserAgentProber:
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

    def __enter__(self) -> TransparentUserAgentProber:
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

    def probe(self, row: BlockedUrlCandidate) -> ReprobeResult:
        url = row.source_url
        if not _is_http_url(url):
            return ReprobeResult(
                **asdict(row),
                final_url=url,
                status_code=None,
                outcome="non_http",
                method=None,
            )
        if not self._robots_allowed(url):
            return ReprobeResult(
                **asdict(row),
                final_url=url,
                status_code=None,
                outcome="robots_disallow",
                method=None,
            )
        try:
            resp = self._request("HEAD", url)
            method = "HEAD"
            if resp.status_code in {405, 501}:
                resp = self._request("GET", url)
                method = "GET"
            final_url = str(resp.url)
            return ReprobeResult(
                **asdict(row),
                final_url=final_url,
                status_code=resp.status_code,
                outcome=classify_status(resp.status_code, final_url=final_url, original_url=url),
                method=method,
            )
        except httpx.HTTPError as exc:
            return ReprobeResult(
                **asdict(row),
                final_url=url,
                status_code=None,
                outcome="transport_error",
                method="HEAD",
                error=f"{type(exc).__name__}: {exc}",
            )


def write_results_csv(path: Path, results: list[ReprobeResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        list(asdict(results[0]).keys()) if results else list(ReprobeResult.__dataclass_fields__)
    )
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))


def reprobe_blocked_urls(
    candidates: list[BlockedUrlCandidate],
    *,
    prober: UrlProber,
    output: Path | None = None,
) -> dict[str, Any]:
    results = [prober.probe(row) for row in candidates]
    if output is not None:
        write_results_csv(output, results)
    outcomes = Counter(result.outcome for result in results)
    statuses = Counter(
        str(result.status_code) if result.status_code is not None else "none" for result in results
    )
    return {
        "mode": "report_only",
        "generated_at": _utc_now(),
        "candidate_rows": len(candidates),
        "probed_rows": len(results),
        "output": str(output) if output is not None else None,
        "user_agent": TRANSPARENT_USER_AGENT,
        "outcomes": dict(sorted(outcomes.items())),
        "status_codes": dict(sorted(statuses.items())),
        "sample_results": [asdict(result) for result in results[:10]],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=AUTONOMATH_DB)
    parser.add_argument("--input-csv", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
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
    parser.add_argument("--write-csv", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.input_csv:
        candidates = load_candidates_csv(args.input_csv, limit=args.limit)
    else:
        with _connect(args.db) as conn:
            candidates = load_blocked_url_candidates(
                conn,
                limit=args.limit,
                domain=args.domain,
            )
    output = (
        args.output if args.output is not None else (DEFAULT_OUTPUT if args.write_csv else None)
    )
    with TransparentUserAgentProber(
        per_host_delay_sec=args.per_host_delay_sec,
        timeout_sec=args.timeout_sec,
        respect_robots=not args.ignore_robots,
    ) as prober:
        result = reprobe_blocked_urls(candidates, prober=prober, output=output)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"candidate_rows={result['candidate_rows']}")
        print(f"probed_rows={result['probed_rows']}")
        print(f"outcomes={result['outcomes']}")
        if result["output"]:
            print(f"output={result['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
