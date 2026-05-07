#!/usr/bin/env python
"""Performance benchmark for jpintel-mcp REST API.

Captures baseline latency + throughput so we know what "normal" looks like
and can spot regressions.

Usage:
    .venv/bin/python scripts/bench.py
    .venv/bin/python scripts/bench.py --base-url http://localhost:8080

Env:
    BASE_URL  default http://localhost:8080
    API_KEY   optional, sent as x-api-key (anonymous if unset)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SEQUENTIAL_SAMPLES = 30
CONCURRENT_WORKERS = 10
CONCURRENT_DURATION_S = 30.0
REQUEST_TIMEOUT_S = 30.0

REPORT_PATH = Path(__file__).resolve().parent.parent / "research" / "perf_baseline.md"


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class SeqResult:
    name: str
    path: str
    samples: list[float] = field(default_factory=list)
    statuses: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for s in self.statuses if 200 <= s < 400)

    @property
    def err_5xx(self) -> int:
        return sum(1 for s in self.statuses if s >= 500)

    def percentile(self, p: float) -> float:
        if not self.samples:
            return float("nan")
        ordered = sorted(self.samples)
        # Nearest-rank inclusive
        k = max(0, min(len(ordered) - 1, int(round(p / 100.0 * (len(ordered) - 1)))))
        return ordered[k]

    @property
    def p50(self) -> float:
        return self.percentile(50)

    @property
    def p95(self) -> float:
        return self.percentile(95)

    @property
    def p99(self) -> float:
        return self.percentile(99)

    @property
    def max(self) -> float:
        return max(self.samples) if self.samples else float("nan")


@dataclass
class LoadResult:
    name: str
    path: str
    workers: int
    duration_s: float
    latencies_ms: list[float] = field(default_factory=list)
    statuses: list[int] = field(default_factory=list)
    wall_s: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.statuses)

    @property
    def ok_count(self) -> int:
        return sum(1 for s in self.statuses if 200 <= s < 400)

    @property
    def err_5xx(self) -> int:
        return sum(1 for s in self.statuses if s >= 500)

    @property
    def throughput(self) -> float:
        return self.total / self.wall_s if self.wall_s > 0 else 0.0

    def percentile(self, p: float) -> float:
        if not self.latencies_ms:
            return float("nan")
        ordered = sorted(self.latencies_ms)
        k = max(0, min(len(ordered) - 1, int(round(p / 100.0 * (len(ordered) - 1)))))
        return ordered[k]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _headers(api_key: str | None) -> dict[str, str]:
    h = {"accept": "application/json"}
    if api_key:
        h["x-api-key"] = api_key
    return h


async def _fetch_first_program_id(base_url: str, api_key: str | None) -> str | None:
    async with httpx.AsyncClient(
        base_url=base_url, headers=_headers(api_key), timeout=REQUEST_TIMEOUT_S
    ) as c:
        try:
            r = await c.get("/v1/programs/search", params={"limit": 1})
            if r.status_code != 200:
                return None
            data = r.json()
            results = data.get("results") or []
            if not results:
                return None
            return results[0].get("unified_id")
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Sequential probes
# ---------------------------------------------------------------------------


async def probe_sequential(
    client: httpx.AsyncClient,
    name: str,
    path: str,
    samples: int,
) -> SeqResult:
    out = SeqResult(name=name, path=path)
    # Warmup (1 call) so we don't count cold connect overhead in first sample
    try:
        r = await client.get(path)
        _ = r.content
    except Exception:
        pass

    for _ in range(samples):
        t0 = time.perf_counter()
        try:
            r = await client.get(path)
            _ = r.content  # force read
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            out.samples.append(elapsed_ms)
            out.statuses.append(r.status_code)
        except Exception as e:  # noqa: BLE001
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            out.samples.append(elapsed_ms)
            out.statuses.append(0)
            out.errors.append(f"{type(e).__name__}: {e}")
    return out


# ---------------------------------------------------------------------------
# Concurrent load
# ---------------------------------------------------------------------------


async def load_worker(
    client: httpx.AsyncClient,
    path: str,
    deadline: float,
    out: LoadResult,
) -> None:
    while time.perf_counter() < deadline:
        t0 = time.perf_counter()
        try:
            r = await client.get(path)
            _ = r.content
            out.latencies_ms.append((time.perf_counter() - t0) * 1000.0)
            out.statuses.append(r.status_code)
        except Exception as e:  # noqa: BLE001
            out.latencies_ms.append((time.perf_counter() - t0) * 1000.0)
            out.statuses.append(0)
            out.errors.append(f"{type(e).__name__}: {e}")


async def probe_concurrent(
    base_url: str,
    api_key: str | None,
    name: str,
    path: str,
    workers: int,
    duration_s: float,
) -> LoadResult:
    out = LoadResult(name=name, path=path, workers=workers, duration_s=duration_s)
    limits = httpx.Limits(max_keepalive_connections=workers, max_connections=workers)
    async with httpx.AsyncClient(
        base_url=base_url,
        headers=_headers(api_key),
        timeout=REQUEST_TIMEOUT_S,
        limits=limits,
    ) as client:
        start = time.perf_counter()
        deadline = start + duration_s
        tasks = [
            asyncio.create_task(load_worker(client, path, deadline, out)) for _ in range(workers)
        ]
        await asyncio.gather(*tasks)
        out.wall_s = time.perf_counter() - start
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def fmt_ms(x: float) -> str:
    if x != x:  # NaN
        return "-"
    return f"{x:7.2f}"


def render_seq_table(results: list[SeqResult]) -> str:
    header = (
        "| Endpoint | n | ok | 5xx | p50 (ms) | p95 (ms) | p99 (ms) | max (ms) |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|\n"
    )
    lines = []
    for r in results:
        lines.append(
            f"| `{r.path}` | {len(r.samples)} | {r.ok_count} | {r.err_5xx} | "
            f"{fmt_ms(r.p50)} | {fmt_ms(r.p95)} | {fmt_ms(r.p99)} | {fmt_ms(r.max)} |"
        )
    return header + "\n".join(lines)


def render_load_section(r: LoadResult) -> str:
    p50 = r.percentile(50)
    p95 = r.percentile(95)
    p99 = r.percentile(99)
    mx = max(r.latencies_ms) if r.latencies_ms else float("nan")
    mean_ms = statistics.fmean(r.latencies_ms) if r.latencies_ms else float("nan")
    return (
        f"**Endpoint:** `{r.path}`  \n"
        f"**Workers:** {r.workers}  **Wall:** {r.wall_s:.2f}s  "
        f"**Total req:** {r.total}  **ok:** {r.ok_count}  **5xx:** {r.err_5xx}  \n"
        f"**Throughput:** {r.throughput:.1f} req/s  \n"
        f"**Latency (ms):** mean={fmt_ms(mean_ms)} p50={fmt_ms(p50)} "
        f"p95={fmt_ms(p95)} p99={fmt_ms(p99)} max={fmt_ms(mx)}\n"
    )


def build_flags(seq: list[SeqResult], load: LoadResult) -> list[str]:
    flags: list[str] = []
    for r in seq:
        if r.p99 > 500:
            flags.append(
                f"- **p99 > 500ms**: `{r.path}` p99={r.p99:.1f}ms. "
                "Likely cause: SQLite full-table scan / JSON per-row parse. "
                "Suggested fix: add index on filter columns or cache result."
            )
        if r.err_5xx:
            flags.append(
                f"- **5xx under sequential probe**: `{r.path}` "
                f"5xx={r.err_5xx}. Investigate server logs."
            )
    if load.err_5xx:
        flags.append(
            f"- **5xx under load**: `{load.path}` "
            f"{load.err_5xx}/{load.total} returned 5xx. "
            "Likely cause: sqlite lock contention under 10 workers, or per-request "
            "`PRAGMA` setup in `connect()`. Suggested fix: WAL + shared readonly "
            "connections, or connection pool."
        )
    if load.percentile(99) > 500:
        flags.append(
            f"- **p99 > 500ms under load**: `{load.path}` "
            f"p99={load.percentile(99):.1f}ms. "
            "Likely cause: `COUNT(*)` over filtered set each call, or FTS rank "
            "path re-reading JSON columns. Suggested fix: cache `COUNT(*)`, "
            "short-circuit when `q` only (skip filters)."
        )
    if load.throughput < 100:
        flags.append(
            f"- **throughput < 100 req/s**: `{load.path}` "
            f"{load.throughput:.1f} req/s at {load.workers} workers. "
            "Likely cause: JSON parse per row in `_row_to_program` or sqlite "
            "single-writer lock. Suggested fix: project only listing columns, "
            "parse JSON lazily, or cache hot searches."
        )
    return flags


CACHE_SECTION = """\
## Cache / optimization recommendations

Scope: in-process LRU cache (functools.lru_cache or cachetools.TTLCache),
keyed on the full query string so cache keys are stable across workers.

| Endpoint | Cache? | TTL | Reason |
|---|---|---|---|
| `/v1/exclusions/rules` | yes | 24h | Static-ish, 22 rows, updates via ingest job. |
| `/meta` | yes | 1h | Aggregates over full table, changes only on ingest. |
| `/v1/programs/search` | no | - | High-entropy q/tier/prefecture cartesian, low hit rate. |
| `/v1/programs/{id}` | optional | 5m | Detail view often re-hit by UI; 5m TTL acceptable. |
| `/healthz` | no | - | Must reflect real DB reachability. |

Invalidation: on ingest completion, emit a `CACHE_EPOCH += 1` signal and wrap
caches with `@lru_cache(maxsize=64)` keyed on `(CACHE_EPOCH, args)`.
"""


def write_report(
    base_url: str,
    seq: list[SeqResult],
    load: LoadResult,
    flags: list[str],
) -> None:
    top_slow = max(seq, key=lambda r: r.p99 if r.p99 == r.p99 else -1)
    summary_lines = [
        "# jpintel-mcp REST API — Performance Baseline",
        "",
        f"_Generated: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}_  ",
        f"_Base URL: `{base_url}`_  ",
        f"_Samples per endpoint: {SEQUENTIAL_SAMPLES} sequential_  ",
        f"_Concurrent load: {CONCURRENT_WORKERS} workers × {CONCURRENT_DURATION_S:.0f}s_",
        "",
        "## Summary",
        "",
        f"Top slowest endpoint by p99: `{top_slow.path}` "
        f"(p99 = {top_slow.p99:.1f}ms, max = {top_slow.max:.1f}ms).  ",
        f"Concurrent search throughput: **{load.throughput:.1f} req/s** "
        f"across {load.workers} workers "
        f"(p50 {load.percentile(50):.1f}ms, p99 {load.percentile(99):.1f}ms).  ",
        f"HTTP errors observed: sequential 5xx = "
        f"{sum(r.err_5xx for r in seq)}, load 5xx = {load.err_5xx}.",
        "",
        "## Opportunity flags",
        "",
    ]
    if flags:
        summary_lines.extend(flags)
    else:
        summary_lines.append(
            "_None — all endpoints within p99 < 500ms, no 5xx, search throughput >= 100 req/s._"
        )
    summary_lines.append("")
    summary_lines.append(CACHE_SECTION)
    summary_lines.append("")
    summary_lines.append("## Raw numbers — sequential (30 samples each)")
    summary_lines.append("")
    summary_lines.append(render_seq_table(seq))
    summary_lines.append("")
    summary_lines.append("## Raw numbers — concurrent load")
    summary_lines.append("")
    summary_lines.append(render_load_section(load))

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(summary_lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(base_url: str, api_key: str | None) -> int:
    print(f"[bench] base_url={base_url} api_key={'set' if api_key else 'none'}")

    first_id = await _fetch_first_program_id(base_url, api_key)
    if not first_id:
        print("[bench] could not fetch first program id; /v1/programs/{id} will be skipped")
    else:
        print(f"[bench] using first_id={first_id}")

    endpoints: list[tuple[str, str]] = [
        ("healthz", "/healthz"),
        ("search-nogyo", "/v1/programs/search?q=%E8%BE%B2%E6%A5%AD&limit=20"),
        ("search-IT", "/v1/programs/search?q=IT&limit=20"),
    ]
    if first_id:
        endpoints.append(("program-detail", f"/v1/programs/{first_id}"))
    endpoints.append(("exclusions-rules", "/v1/exclusions/rules"))
    # NOTE: meta_router has no /v1 prefix in src/jpintel_mcp/api/meta.py — real
    # path is /meta. /v1/meta returns 404. Probing the real path for baseline.
    endpoints.append(("meta", "/meta"))

    # Sequential pass
    seq_results: list[SeqResult] = []
    async with httpx.AsyncClient(
        base_url=base_url,
        headers=_headers(api_key),
        timeout=REQUEST_TIMEOUT_S,
    ) as client:
        for name, path in endpoints:
            print(f"[bench] sequential: {path} x{SEQUENTIAL_SAMPLES} ...", flush=True)
            r = await probe_sequential(client, name, path, SEQUENTIAL_SAMPLES)
            seq_results.append(r)
            print(
                f"  -> p50={r.p50:.1f}ms p95={r.p95:.1f}ms p99={r.p99:.1f}ms "
                f"max={r.max:.1f}ms  ok={r.ok_count}/{len(r.samples)}  5xx={r.err_5xx}",
                flush=True,
            )

    # Concurrent load on search
    load_path = "/v1/programs/search?q=%E8%BE%B2%E6%A5%AD&limit=20"
    print(
        f"[bench] concurrent load: {load_path}  "
        f"{CONCURRENT_WORKERS} workers x {CONCURRENT_DURATION_S:.0f}s ...",
        flush=True,
    )
    load = await probe_concurrent(
        base_url=base_url,
        api_key=api_key,
        name="search-load",
        path=load_path,
        workers=CONCURRENT_WORKERS,
        duration_s=CONCURRENT_DURATION_S,
    )
    print(
        f"  -> throughput={load.throughput:.1f} req/s  "
        f"total={load.total}  ok={load.ok_count}  5xx={load.err_5xx}  "
        f"p50={load.percentile(50):.1f}ms p95={load.percentile(95):.1f}ms "
        f"p99={load.percentile(99):.1f}ms",
        flush=True,
    )

    # Flags
    flags = build_flags(seq_results, load)

    # Console table
    print()
    print("=" * 78)
    print("SEQUENTIAL (30 samples each)")
    print("-" * 78)
    print(f"{'Endpoint':<52} {'p50':>6} {'p95':>7} {'p99':>7} {'max':>7}")
    for r in seq_results:
        print(f"{r.path[:52]:<52} {r.p50:>6.1f} {r.p95:>7.1f} {r.p99:>7.1f} {r.max:>7.1f}")
    print("-" * 78)
    print("CONCURRENT LOAD")
    print("-" * 78)
    print(
        f"{load.path[:52]:<52} "
        f"thr={load.throughput:.1f} req/s  "
        f"p50={load.percentile(50):.1f}ms  "
        f"p95={load.percentile(95):.1f}ms  "
        f"p99={load.percentile(99):.1f}ms  "
        f"5xx={load.err_5xx}"
    )
    print("=" * 78)
    if flags:
        print("\nFLAGS:")
        for f in flags:
            print(f)
    else:
        print("\nNo flags raised.")

    write_report(base_url, seq_results, load, flags)
    print(f"\n[bench] report written to {REPORT_PATH}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--base-url",
        default=os.environ.get("BASE_URL", "http://localhost:8080"),
        help="Base URL of the API under test.",
    )
    p.add_argument(
        "--api-key",
        default=os.environ.get("API_KEY"),
        help="Optional API key (x-api-key header).",
    )
    return p.parse_args(argv)


def main() -> None:
    args = parse_args()
    rc = asyncio.run(run(args.base_url, args.api_key))
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
