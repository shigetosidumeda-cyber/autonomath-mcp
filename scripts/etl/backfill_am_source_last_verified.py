#!/usr/bin/env python3
"""Backfill ``am_source.last_verified`` with polite HTTP probes.

A5 is intentionally separated from ``scripts/refresh_sources.py`` because that
script targets ``data/jpintel.db.programs``.  This script targets the
repo-root ``autonomath.db.am_source`` table and only updates
``last_verified`` for HTTP(S) rows that were actually probed or produced a
HTTP response.  It is resumable and safe to run in small batches.

No LLM. Robots respected. Per-domain pacing defaults to 1 request/second.
"""

from __future__ import annotations

import argparse
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
from typing import Protocol

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.http import (  # noqa: E402
    DEFAULT_PER_HOST_DELAY_SEC,
    DEFAULT_TIMEOUT_SEC,
    DEFAULT_USER_AGENT,
)

AUTONOMATH_DB = REPO_ROOT / "autonomath.db"


@dataclass(frozen=True)
class SourceCandidate:
    source_id: int
    source_url: str
    domain: str | None


@dataclass(frozen=True)
class ProbeResult:
    source_id: int
    source_url: str
    final_url: str
    status_code: int | None
    outcome: str
    method: str | None
    verified: bool
    error: str | None = None


class SourceProber(Protocol):
    def probe(self, row: SourceCandidate) -> ProbeResult: ...


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _utc_now_sql() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _is_http_url(url: str | None) -> bool:
    if not url:
        return False
    scheme = urllib.parse.urlparse(url).scheme.lower()
    return scheme in {"http", "https"}


def _host(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower()


def classify_http_status(status_code: int, *, final_url: str, original_url: str) -> str:
    if final_url.rstrip("/") != original_url.rstrip("/"):
        return "redirect"
    if 200 <= status_code < 300:
        return "ok"
    if 300 <= status_code < 400:
        return "redirect"
    if status_code in {401, 403, 429}:
        return "blocked"
    if status_code in {404, 410}:
        return "broken"
    if 400 <= status_code < 500:
        return "client_error"
    if status_code >= 500:
        return "server_error"
    return "other_status"


def load_candidates(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
    domain: str | None = None,
    resume_after_id: int = 0,
) -> list[SourceCandidate]:
    if limit is not None and limit <= 0:
        return []
    clauses = [
        "last_verified IS NULL",
        "id > ?",
        "(source_url LIKE 'http://%' OR source_url LIKE 'https://%')",
    ]
    params: list[object] = [resume_after_id]
    if domain:
        clauses.append("domain = ?")
        params.append(domain)
    sql = (
        "SELECT id, source_url, domain FROM am_source WHERE "
        + " AND ".join(clauses)
        + " ORDER BY id"
    )
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [
        SourceCandidate(
            source_id=int(row["id"]),
            source_url=str(row["source_url"]),
            domain=row["domain"],
        )
        for row in rows
    ]


class HttpHeadProber:
    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        per_host_delay_sec: float = DEFAULT_PER_HOST_DELAY_SEC,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        respect_robots: bool = True,
    ) -> None:
        self._ua = user_agent
        self._per_host_delay = per_host_delay_sec
        self._respect_robots = respect_robots
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Language": "ja,en;q=0.5"},
            timeout=timeout_sec,
            follow_redirects=True,
        )
        self._host_clock: dict[str, float] = {}
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpHeadProber:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

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

    def _pace_host(self, url: str) -> None:
        host = _host(url)
        now = time.monotonic()
        last = self._host_clock.get(host)
        if last is not None:
            wait = self._per_host_delay - (now - last)
            if wait > 0:
                time.sleep(wait)
        self._host_clock[host] = time.monotonic()

    def _request(self, method: str, url: str) -> httpx.Response:
        self._pace_host(url)
        if method == "GET":
            return self._client.get(
                url,
                headers={"Range": "bytes=0-0"},
            )
        return self._client.head(url)

    def probe(self, row: SourceCandidate) -> ProbeResult:
        url = row.source_url
        if not _is_http_url(url):
            return ProbeResult(
                source_id=row.source_id,
                source_url=url,
                final_url=url,
                status_code=None,
                outcome="non_http",
                method=None,
                verified=False,
            )
        if not self._robots_allowed(url):
            return ProbeResult(
                source_id=row.source_id,
                source_url=url,
                final_url=url,
                status_code=None,
                outcome="robots_disallow",
                method=None,
                verified=False,
            )
        try:
            resp = self._request("HEAD", url)
            method = "HEAD"
            if resp.status_code in {405, 501}:
                resp = self._request("GET", url)
                method = "GET"
            final_url = str(resp.url)
            outcome = classify_http_status(
                resp.status_code,
                final_url=final_url,
                original_url=url,
            )
            return ProbeResult(
                source_id=row.source_id,
                source_url=url,
                final_url=final_url,
                status_code=resp.status_code,
                outcome=outcome,
                method=method,
                verified=True,
            )
        except httpx.HTTPError as exc:
            return ProbeResult(
                source_id=row.source_id,
                source_url=url,
                final_url=url,
                status_code=None,
                outcome="transport_error",
                method="HEAD",
                verified=False,
                error=f"{type(exc).__name__}: {exc}",
            )


def _update_verified_rows(
    conn: sqlite3.Connection,
    results: list[ProbeResult],
    *,
    verified_at: str,
) -> int:
    rows = [(verified_at, result.source_id) for result in results if result.verified]
    if not rows:
        return 0
    cur = conn.executemany(
        """UPDATE am_source
              SET last_verified = ?
            WHERE id = ?
              AND last_verified IS NULL""",
        rows,
    )
    return cur.rowcount


def verify_am_sources(
    conn: sqlite3.Connection,
    *,
    prober: SourceProber,
    apply: bool,
    limit: int | None = None,
    domain: str | None = None,
    resume_after_id: int = 0,
    commit_every: int = 100,
) -> dict[str, object]:
    before_verified = conn.execute(
        "SELECT COUNT(*) FROM am_source WHERE last_verified IS NOT NULL"
    ).fetchone()[0]
    before_null = conn.execute(
        "SELECT COUNT(*) FROM am_source WHERE last_verified IS NULL"
    ).fetchone()[0]
    candidates = load_candidates(
        conn,
        limit=limit,
        domain=domain,
        resume_after_id=resume_after_id,
    )
    verified_at = _utc_now_sql()
    results: list[ProbeResult] = []
    updated_rows = 0
    batch: list[ProbeResult] = []
    for row in candidates:
        result = prober.probe(row)
        results.append(result)
        batch.append(result)
        if apply and len(batch) >= max(1, commit_every):
            with conn:
                updated_rows += _update_verified_rows(
                    conn,
                    batch,
                    verified_at=verified_at,
                )
            batch = []
    if apply and batch:
        with conn:
            updated_rows += _update_verified_rows(
                conn,
                batch,
                verified_at=verified_at,
            )

    outcomes = Counter(result.outcome for result in results)
    methods = Counter(result.method or "none" for result in results)
    after_verified = conn.execute(
        "SELECT COUNT(*) FROM am_source WHERE last_verified IS NOT NULL"
    ).fetchone()[0]
    after_null = conn.execute(
        "SELECT COUNT(*) FROM am_source WHERE last_verified IS NULL"
    ).fetchone()[0]
    return {
        "mode": "apply" if apply else "dry_run",
        "verified_at": verified_at,
        "candidate_rows": len(candidates),
        "probed_rows": len(results),
        "verified_probe_rows": sum(1 for result in results if result.verified),
        "updated_rows": updated_rows,
        "last_verified_non_null_before": before_verified,
        "last_verified_null_before": before_null,
        "last_verified_non_null_after": after_verified,
        "last_verified_null_after": after_null,
        "outcomes": dict(sorted(outcomes.items())),
        "methods": dict(sorted(methods.items())),
        "last_source_id": results[-1].source_id if results else None,
        "sample_results": [asdict(result) for result in results[:10]],
        "generated_at": datetime.now(UTC).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=AUTONOMATH_DB)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--domain", default=None)
    parser.add_argument("--resume-after-id", type=int, default=0)
    parser.add_argument("--commit-every", type=int, default=100)
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

    with (
        _connect(args.db) as conn,
        HttpHeadProber(
            per_host_delay_sec=args.per_host_delay_sec,
            timeout_sec=args.timeout_sec,
            respect_robots=not args.ignore_robots,
        ) as prober,
    ):
        result = verify_am_sources(
            conn,
            prober=prober,
            apply=args.apply,
            limit=args.limit,
            domain=args.domain,
            resume_after_id=args.resume_after_id,
            commit_every=args.commit_every,
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "am_source.last_verified non-NULL: "
            f"{result['last_verified_non_null_before']} -> "
            f"{result['last_verified_non_null_after']}"
        )
        print(f"candidate_rows={result['candidate_rows']}")
        print(f"verified_probe_rows={result['verified_probe_rows']}")
        print(f"updated_rows={result['updated_rows']}")
        print(f"outcomes={result['outcomes']}")
        if result["last_source_id"] is not None:
            print(f"resume hint: --resume-after-id {result['last_source_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
