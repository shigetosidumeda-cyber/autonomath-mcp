#!/usr/bin/env python
"""Performance benchmark for AutonoMath REST API — launch baseline.

Measures p50/p90/p95/p99/max latency and throughput for 4 query shapes
at 3 concurrency levels. Writes a JSON report + prints a table.

Usage:
    .venv/bin/python scripts/bench_api.py --base-url http://127.0.0.1:18080

Shapes:
    1. search_nogyo        GET /v1/programs/search?q=農業&limit=20
    2. search_it_dounyuu   GET /v1/programs/search?q=IT導入補助金&limit=20
    3. search_hojokin_tko  GET /v1/programs/search?q=補助金&prefecture=東京都&limit=20
    4. get_program         GET /v1/programs/{unified_id}     (random sample)

Protocol:
    - warmup:    20 requests (ignored) per shape/concurrency before timing
    - sequential: 500 requests, concurrency=1
    - concurrent: 200 requests, at concurrency levels [1, 10, 50]
    - median of 3 runs per (shape, concurrency) pair
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "jpintel.db"
REPORT_PATH = ROOT / "data" / "bench_api_report.json"

WARMUP = 20
SEQUENTIAL_N = 500
CONCURRENT_N = 200
CONCURRENCY_LEVELS = [1, 10, 50]
RUNS_PER_CELL = 3
REQUEST_TIMEOUT_S = 30.0


# ---------------------------------------------------------------------------
# Shape definitions
# ---------------------------------------------------------------------------


@dataclass
class Shape:
    """Describes one query shape to benchmark.

    For the point-lookup we pass `path_fn` which draws a random unified_id
    per request — that way the cache doesn't artificially flatten p99.
    """

    name: str
    path: str | None = None
    path_fn: Any = None  # callable() -> str

    def render(self) -> str:
        if self.path_fn is not None:
            return self.path_fn()
        assert self.path is not None
        return self.path


def _load_unified_ids(limit: int = 500) -> list[str]:
    """Pull a sample of live (non-excluded, non-tier-X) unified_ids for the
    point-lookup shape. Falls back to an empty list if the DB is missing —
    in that case the get_program shape is skipped."""
    if not DB_PATH.exists():
        return []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT unified_id FROM programs "
            "WHERE excluded=0 AND COALESCE(tier,'X')!='X' "
            "ORDER BY RANDOM() LIMIT ?",
            (limit,),
        ).fetchall()
    return [r["unified_id"] for r in rows]


def _q(params: dict[str, str]) -> str:
    return urlencode(params, safe="", encoding="utf-8")


def build_shapes() -> list[Shape]:
    shapes: list[Shape] = [
        Shape(
            name="search(q=農業, limit=20)",
            path="/v1/programs/search?" + _q({"q": "農業", "limit": "20"}),
        ),
        Shape(
            name="search(q=IT導入補助金, limit=20)",
            path="/v1/programs/search?" + _q({"q": "IT導入補助金", "limit": "20"}),
        ),
        Shape(
            name="search(q=補助金, prefecture=東京都, limit=20)",
            path="/v1/programs/search?"
            + _q({"q": "補助金", "prefecture": "東京都", "limit": "20"}),
        ),
    ]
    ids = _load_unified_ids()
    if ids:
        pool = ids

        def _pick() -> str:
            return f"/v1/programs/{random.choice(pool)}"

        shapes.append(Shape(name="get_program(random)", path_fn=_pick))
    return shapes


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def pct(samples: list[float], p: float) -> float:
    if not samples:
        return float("nan")
    ordered = sorted(samples)
    k = max(0, min(len(ordered) - 1, int(round(p / 100.0 * (len(ordered) - 1)))))
    return ordered[k]


@dataclass
class RunStats:
    latencies_ms: list[float] = field(default_factory=list)
    statuses: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    wall_s: float = 0.0

    @property
    def total(self) -> int:
        return len(self.statuses)

    @property
    def ok_count(self) -> int:
        return sum(1 for s in self.statuses if 200 <= s < 400)

    @property
    def err_count(self) -> int:
        return self.total - self.ok_count + len(
            [e for e in self.errors if e]  # transport failures already in statuses=0
        )

    @property
    def err_5xx(self) -> int:
        return sum(1 for s in self.statuses if s >= 500)

    @property
    def timeouts(self) -> int:
        return sum(1 for e in self.errors if "Timeout" in e or "timeout" in e)

    @property
    def throughput(self) -> float:
        return self.total / self.wall_s if self.wall_s > 0 else 0.0


# ---------------------------------------------------------------------------
# Request loops
# ---------------------------------------------------------------------------


async def _one_request(
    client: httpx.AsyncClient,
    shape: Shape,
    stats: RunStats,
) -> None:
    path = shape.render()
    t0 = time.perf_counter()
    try:
        r = await client.get(path)
        _ = r.content
        stats.latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        stats.statuses.append(r.status_code)
    except Exception as e:  # noqa: BLE001
        stats.latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        stats.statuses.append(0)
        stats.errors.append(f"{type(e).__name__}: {e}")


async def _warmup(client: httpx.AsyncClient, shape: Shape, n: int) -> None:
    for _ in range(n):
        try:
            r = await client.get(shape.render())
            _ = r.content
        except Exception:  # noqa: BLE001
            pass


async def run_sequential(
    base_url: str, shape: Shape, n: int, warmup: int
) -> RunStats:
    stats = RunStats()
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=REQUEST_TIMEOUT_S,
        limits=httpx.Limits(max_keepalive_connections=2, max_connections=2),
    ) as client:
        await _warmup(client, shape, warmup)
        t0 = time.perf_counter()
        for _ in range(n):
            await _one_request(client, shape, stats)
        stats.wall_s = time.perf_counter() - t0
    return stats


async def run_concurrent(
    base_url: str, shape: Shape, n: int, concurrency: int, warmup: int
) -> RunStats:
    stats = RunStats()
    limits = httpx.Limits(
        max_keepalive_connections=concurrency,
        max_connections=concurrency,
    )
    async with httpx.AsyncClient(
        base_url=base_url, timeout=REQUEST_TIMEOUT_S, limits=limits
    ) as client:
        await _warmup(client, shape, warmup)

        sem = asyncio.Semaphore(concurrency)

        async def _bounded() -> None:
            async with sem:
                await _one_request(client, shape, stats)

        t0 = time.perf_counter()
        await asyncio.gather(*[_bounded() for _ in range(n)])
        stats.wall_s = time.perf_counter() - t0
    return stats


# ---------------------------------------------------------------------------
# Median-of-3 helper
# ---------------------------------------------------------------------------


def _summarize_runs(runs: list[RunStats]) -> dict[str, Any]:
    """Median of per-run percentiles (not pooled samples) — robust to outlier
    runs caused by GC or napping CPUs."""
    p50s = [pct(r.latencies_ms, 50) for r in runs]
    p90s = [pct(r.latencies_ms, 90) for r in runs]
    p95s = [pct(r.latencies_ms, 95) for r in runs]
    p99s = [pct(r.latencies_ms, 99) for r in runs]
    maxs = [max(r.latencies_ms) if r.latencies_ms else float("nan") for r in runs]
    throughputs = [r.throughput for r in runs]
    total_ok = sum(r.ok_count for r in runs)
    total_req = sum(r.total for r in runs)
    total_5xx = sum(r.err_5xx for r in runs)
    total_timeouts = sum(r.timeouts for r in runs)
    total_errors = total_req - total_ok
    return {
        "p50_ms": statistics.median(p50s),
        "p90_ms": statistics.median(p90s),
        "p95_ms": statistics.median(p95s),
        "p99_ms": statistics.median(p99s),
        "max_ms": statistics.median(maxs),
        "throughput_rps": statistics.median(throughputs),
        "total_requests": total_req,
        "ok": total_ok,
        "errors": total_errors,
        "http_5xx": total_5xx,
        "timeouts": total_timeouts,
        "runs": len(runs),
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


async def bench_shape(
    base_url: str, shape: Shape
) -> dict[str, Any]:
    out: dict[str, Any] = {"name": shape.name, "cells": {}}

    # Sequential (concurrency=1) baseline
    seq_runs: list[RunStats] = []
    print(f"[bench] {shape.name!s}  sequential x{SEQUENTIAL_N} ...", flush=True)
    for i in range(RUNS_PER_CELL):
        s = await run_sequential(base_url, shape, SEQUENTIAL_N, WARMUP)
        seq_runs.append(s)
        print(
            f"   run {i + 1}/{RUNS_PER_CELL}: p50={pct(s.latencies_ms, 50):.1f}ms "
            f"p95={pct(s.latencies_ms, 95):.1f}ms "
            f"p99={pct(s.latencies_ms, 99):.1f}ms "
            f"thr={s.throughput:.0f}rps "
            f"5xx={s.err_5xx} err={s.total - s.ok_count}",
            flush=True,
        )
    out["cells"]["sequential_500"] = _summarize_runs(seq_runs)

    # Concurrent sweep
    for conc in CONCURRENCY_LEVELS:
        runs: list[RunStats] = []
        print(
            f"[bench] {shape.name!s}  concurrent n={CONCURRENT_N} c={conc} ...",
            flush=True,
        )
        for i in range(RUNS_PER_CELL):
            s = await run_concurrent(base_url, shape, CONCURRENT_N, conc, WARMUP)
            runs.append(s)
            print(
                f"   run {i + 1}/{RUNS_PER_CELL}: p50={pct(s.latencies_ms, 50):.1f}ms "
                f"p95={pct(s.latencies_ms, 95):.1f}ms "
                f"p99={pct(s.latencies_ms, 99):.1f}ms "
                f"thr={s.throughput:.0f}rps "
                f"5xx={s.err_5xx} err={s.total - s.ok_count}",
                flush=True,
            )
        out["cells"][f"concurrent_c{conc}"] = _summarize_runs(runs)

    # Flatten top-level: use the sequential cell's percentiles as the "headline"
    seq_cell = out["cells"]["sequential_500"]
    out["p50_ms"] = seq_cell["p50_ms"]
    out["p90_ms"] = seq_cell["p90_ms"]
    out["p95_ms"] = seq_cell["p95_ms"]
    out["p99_ms"] = seq_cell["p99_ms"]
    return out


def print_table(shapes: list[dict[str, Any]]) -> None:
    print()
    print("=" * 110)
    print(f"{'Shape':<46} {'Cell':<18} {'p50':>7} {'p90':>7} {'p95':>7} {'p99':>7} {'max':>7} {'rps':>8}")
    print("-" * 110)
    for s in shapes:
        for cell_name, c in s["cells"].items():
            print(
                f"{s['name'][:46]:<46} {cell_name:<18} "
                f"{c['p50_ms']:>7.1f} {c['p90_ms']:>7.1f} {c['p95_ms']:>7.1f} "
                f"{c['p99_ms']:>7.1f} {c['max_ms']:>7.1f} {c['throughput_rps']:>8.1f}"
            )
    print("=" * 110)


def build_flags(shapes: list[dict[str, Any]]) -> list[str]:
    flags: list[str] = []
    for s in shapes:
        for cell_name, c in s["cells"].items():
            if c["p95_ms"] > 500:
                flags.append(
                    f"{s['name']} [{cell_name}] p95={c['p95_ms']:.1f}ms "
                    "exceeds 500ms — shipping blocker."
                )
            if c["p99_ms"] > 1000:
                flags.append(
                    f"{s['name']} [{cell_name}] p99={c['p99_ms']:.1f}ms "
                    "exceeds 1000ms."
                )
            if c["http_5xx"] > 0:
                flags.append(
                    f"{s['name']} [{cell_name}] {c['http_5xx']} 5xx responses."
                )
            if c["timeouts"] > 0:
                flags.append(
                    f"{s['name']} [{cell_name}] {c['timeouts']} timeouts."
                )
    return flags


async def run(base_url: str) -> int:
    print(f"[bench] base_url={base_url}")
    # Smoke check
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as c:
            r = await c.get("/readyz")
            if r.status_code != 200:
                print(f"[bench] ERROR: /readyz returned {r.status_code}", file=sys.stderr)
                return 2
    except Exception as e:  # noqa: BLE001
        print(f"[bench] ERROR: could not reach {base_url}: {e}", file=sys.stderr)
        return 2

    shapes = build_shapes()
    if not shapes:
        print("[bench] no shapes to run", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    for sh in shapes:
        results.append(await bench_shape(base_url, sh))

    print_table(results)

    flags = build_flags(results)
    if flags:
        print("\nFLAGS:")
        for f in flags:
            print(f"  - {f}")
    else:
        print("\nNo flags — all cells within p95<500ms and no 5xx/timeouts.")

    # Emit JSON report
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "base_url": base_url,
        "hardware": f"{os.uname().sysname} {os.uname().machine}",
        "protocol": {
            "warmup": WARMUP,
            "sequential_n": SEQUENTIAL_N,
            "concurrent_n": CONCURRENT_N,
            "concurrency_levels": CONCURRENCY_LEVELS,
            "runs_per_cell": RUNS_PER_CELL,
        },
        "shapes": results,
        "flags": flags,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[bench] report written to {REPORT_PATH}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--base-url",
        default=os.environ.get("BASE_URL", "http://127.0.0.1:18080"),
        help="Base URL of the API under test.",
    )
    return p.parse_args(argv)


def main() -> None:
    args = parse_args()
    rc = asyncio.run(run(args.base_url))
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
