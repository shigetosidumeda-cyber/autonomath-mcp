#!/usr/bin/env python3
"""Common Crawl monthly coverage audit for jpcite.com.

Wave 16 B1 — runs the 5th of every month (after CC monthly snapshots ship).

What this does
--------------
Common Crawl publishes a fresh URL index (CC-MAIN-YYYY-WW) ~once per month.
For each currently-active snapshot, we hit the columnar index at
`https://index.commoncrawl.org/CC-MAIN-{slug}-index?url=jpcite.com&output=json`
and stream back per-URL CDX rows (one JSON object per line).

We then dump a snapshot of the coverage to
`analytics/common_crawl_coverage_{YYYY-MM-DD}.jsonl`:

  {"snapshot":"CC-MAIN-2026-19","captured_urls":N,"unique_urls":U,
   "depth_distribution":{"0":n0,"1":n1,...,"5+":n5},"freshest_capture_ts":"...",
   "stalest_capture_ts":"...","sample_paths":[ "/", "/docs/", ... ],
   "audited_at":"...", "host":"jpcite.com"}

LLM call: 0. Pure stdlib + httpx HEAD/GET. Best-effort: 4xx / 5xx / timeout
on a snapshot is logged + skipped (the next month's run picks it up). Output
file is append-only so dashboards can plot capture-rate over time.

Cadence
-------
`0 5 5 * *` — UTC 05:00 on the 5th of every month. Common Crawl's monthly
snapshot typically lands by the 1st-3rd, so the 5th gives buffer for the
index slug to settle. JST conversion: 14:00 JST on the 5th.

Required env / secrets
----------------------
None. Common Crawl index is fully public, no auth.

Output is committed to analytics/ via the workflow (no DB writes).
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    from jpintel_mcp.observability import heartbeat  # type: ignore
except ImportError:  # pragma: no cover - heartbeat optional for cron
    from contextlib import contextmanager

    @contextmanager
    def heartbeat(_name: str):  # type: ignore[misc]
        yield {}


ANALYTICS_DIR = _REPO_ROOT / "analytics"
HOST = "jpcite.com"
COLLINDEX_URL = "https://index.commoncrawl.org/collinfo.json"
QUERY_URL = "https://index.commoncrawl.org/{slug}-index"
USER_AGENT = "jpcite-cc-audit/1.0 (+https://jpcite.com/)"
MAX_SNAPSHOTS = 3  # cap to the 3 most-recent snapshots (~last 90 days)
MAX_URLS_PER_SNAPSHOT = 2000  # safety cap; jpcite.com has < 100 unique URLs
PAGESIZE = 1


def _list_recent_snapshots(cli: httpx.Client, max_n: int = MAX_SNAPSHOTS) -> list[dict]:
    """Return up to `max_n` most-recent Common Crawl snapshot descriptors.

    Each descriptor: {"id":"CC-MAIN-2026-19","cdx-api":".../CC-MAIN-2026-19-index"}.
    """
    try:
        resp = cli.get(COLLINDEX_URL, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"[cc-audit] collinfo fetch failed: {exc}", file=sys.stderr)
        return []
    main = [row for row in data if isinstance(row, dict) and "CC-MAIN" in (row.get("id") or "")]
    main.sort(key=lambda r: r.get("id", ""), reverse=True)
    return main[:max_n]


def _depth_bucket(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    n = len(parts)
    if n >= 5:
        return "5+"
    return str(n)


def _audit_snapshot(cli: httpx.Client, snapshot: dict, host: str) -> dict:
    """Stream CDX rows for `host` from a single CC snapshot."""
    slug = snapshot.get("id") or ""
    base_url = snapshot.get("cdx-api") or QUERY_URL.format(slug=slug)
    params = {
        "url": f"{host}/*",
        "output": "json",
        "pageSize": str(PAGESIZE),
    }
    full_url = f"{base_url}?{urllib.parse.urlencode(params)}"

    summary: dict = {
        "snapshot": slug,
        "captured_urls": 0,
        "unique_urls": 0,
        "depth_distribution": {},
        "freshest_capture_ts": None,
        "stalest_capture_ts": None,
        "sample_paths": [],
        "status": "ok",
    }

    try:
        with cli.stream("GET", full_url, timeout=60.0) as resp:
            if resp.status_code == 404:
                summary["status"] = "not_indexed"
                return summary
            resp.raise_for_status()
            depth_counter: Counter[str] = Counter()
            seen_paths: set[str] = set()
            tss: list[str] = []
            captured = 0
            for line in resp.iter_lines():
                if not line:
                    continue
                if captured >= MAX_URLS_PER_SNAPSHOT:
                    break
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                url = row.get("url") or ""
                ts = row.get("timestamp") or ""
                captured += 1
                # extract path
                try:
                    parsed = urllib.parse.urlparse(url)
                    path = parsed.path or "/"
                except ValueError:
                    path = "/"
                depth_counter[_depth_bucket(path)] += 1
                seen_paths.add(path)
                if ts:
                    tss.append(ts)
            summary["captured_urls"] = captured
            summary["unique_urls"] = len(seen_paths)
            summary["depth_distribution"] = dict(sorted(depth_counter.items()))
            summary["sample_paths"] = sorted(seen_paths)[:25]
            if tss:
                tss.sort()
                summary["freshest_capture_ts"] = tss[-1]
                summary["stalest_capture_ts"] = tss[0]
    except (httpx.HTTPError, ValueError) as exc:
        summary["status"] = f"error:{type(exc).__name__}"
        print(f"[cc-audit] {slug}: {exc}", file=sys.stderr)
    return summary


def main() -> int:
    with heartbeat("audit_common_crawl") as hb:
        today = datetime.now(UTC).date().isoformat()
        ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = ANALYTICS_DIR / f"common_crawl_coverage_{today}.jsonl"

        rows_written = 0
        with httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as cli:
            snapshots = _list_recent_snapshots(cli, MAX_SNAPSHOTS)
            if not snapshots:
                print("[cc-audit] no snapshots discovered — exit 0")
                hb["rows_processed"] = 0
                return 0
            print(f"[cc-audit] auditing {len(snapshots)} snapshot(s) for {HOST} → {out_path.name}")
            with out_path.open("a", encoding="utf-8") as fh:
                for snap in snapshots:
                    summary = _audit_snapshot(cli, snap, HOST)
                    summary["host"] = HOST
                    summary["audited_at"] = datetime.now(UTC).isoformat()
                    fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
                    rows_written += 1
                    print(
                        f"[cc-audit] {summary['snapshot']}: "
                        f"captured={summary['captured_urls']} "
                        f"unique={summary['unique_urls']} "
                        f"status={summary['status']}"
                    )
        print(f"[cc-audit] done — {rows_written} snapshot row(s) appended")
        hb["rows_processed"] = int(rows_written)
        hb["metadata"] = {"host": HOST, "date": today}
    return 0


if __name__ == "__main__":
    sys.exit(main())
