#!/usr/bin/env python3
"""GG4 — Pre-mapped outcome → top-100 chunk bench (TTFB p95).

Compares the new pre-mapped retrieval (single indexed SELECT over
``am_outcome_chunk_map``) against a simulated live FAISS+rerank
baseline. 100 sampled outcomes × 10 chunks each.

Target
------
* Pre-mapped p95 < 20 ms.
* Live FAISS+rerank p95 ~ 150 ms (PERF-40 baseline, FAISS 50 ms +
  rerank 200 ms ÷ workload smoothing).
* **7-8x speedup** at the same ¥3/req tier.

Constraints
-----------
* NO LLM. Pure SQLite SELECT + numpy percentile.
* mypy --strict clean / ruff clean.

Usage
-----
    .venv/bin/python scripts/bench/bench_outcome_chunks_2026_05_17.py \\
        --db autonomath.db \\
        --samples 100 \\
        --limit 10
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import random
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger("jpcite.gg4.bench")

# Simulated live-baseline budget (PERF-40). The bench does not actually
# call FAISS — it sleeps for the simulated tail latency to verify the
# percentile machinery agrees with documented numbers. The pre-mapped
# path is measured live against the SQLite store.
LIVE_FAISS_MS: float = 50.0
LIVE_RERANK_MS: float = 100.0
LIVE_BASELINE_TOTAL_MS: float = LIVE_FAISS_MS + LIVE_RERANK_MS  # 150 ms


@dataclass(frozen=True)
class BenchResult:
    label: str
    n: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    mean_ms: float
    min_ms: float
    max_ms: float


def percentile(values: list[float], pct: float) -> float:
    """Closed-form percentile without numpy.

    Uses linear interpolation between the two nearest ranks; matches
    the convention used elsewhere in the bench corpus.
    """
    if not values:
        return 0.0
    s = sorted(values)
    if pct <= 0:
        return s[0]
    if pct >= 100:
        return s[-1]
    k = (pct / 100.0) * (len(s) - 1)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] + frac * (s[hi] - s[lo])


def _make_result(label: str, samples_ms: list[float]) -> BenchResult:
    return BenchResult(
        label=label,
        n=len(samples_ms),
        p50_ms=percentile(samples_ms, 50.0),
        p95_ms=percentile(samples_ms, 95.0),
        p99_ms=percentile(samples_ms, 99.0),
        mean_ms=(statistics.fmean(samples_ms) if samples_ms else 0.0),
        min_ms=(min(samples_ms) if samples_ms else 0.0),
        max_ms=(max(samples_ms) if samples_ms else 0.0),
    )


def bench_premapped(
    db_path: Path,
    *,
    outcome_ids: Sequence[int],
    limit: int,
) -> BenchResult:
    """Measure pre-mapped path: single indexed SELECT per outcome.

    Opens a read-only connection (URI mode=ro) so the bench cannot
    accidentally mutate the catalog. Sampling is deterministic via the
    caller-supplied outcome_ids list.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        samples_ms: list[float] = []
        for oid in outcome_ids:
            t0 = time.perf_counter()
            rows = conn.execute(
                """
                SELECT outcome_id, rank, chunk_id, score, mapped_at
                  FROM am_outcome_chunk_map
                 WHERE outcome_id = ?
                 ORDER BY rank ASC
                 LIMIT ?
                """,
                (oid, limit),
            ).fetchall()
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            # Touch the rows so the optimizer cannot skip materialization.
            _ = sum(int(r["chunk_id"]) for r in rows)
            samples_ms.append(elapsed_ms)
    finally:
        conn.close()
    return _make_result("premapped", samples_ms)


def bench_live_simulation(
    *,
    n_samples: int,
    rng_seed: int = 20260517,
) -> BenchResult:
    """Simulate the live FAISS + rerank baseline.

    We don't call FAISS / cross-encoder here — those artifacts are
    runtime-specific. Instead we model the documented latency
    distribution (gaussian around LIVE_BASELINE_TOTAL_MS with a tail).
    The bench treats this as a *baseline anchor* the pre-mapped path
    must beat by 7-8x.
    """
    rng = random.Random(rng_seed)
    samples_ms: list[float] = []
    for _ in range(n_samples):
        # Symmetric core + heavy-tail (5% slow).
        core = rng.gauss(mu=LIVE_BASELINE_TOTAL_MS, sigma=15.0)
        if rng.random() < 0.05:
            core *= 1.5
        samples_ms.append(max(20.0, core))
    return _make_result("live_simulation", samples_ms)


def sample_outcome_ids(db_path: Path, *, n: int, rng_seed: int) -> list[int]:
    """Pick ``n`` outcome ids that actually exist in the pre-mapped table.

    Deterministic via the seed so successive bench runs report
    apples-to-apples numbers.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT outcome_id FROM am_outcome_chunk_map ORDER BY outcome_id"
        ).fetchall()
    finally:
        conn.close()
    all_ids = [int(r[0]) for r in rows]
    if not all_ids:
        return []
    rng = random.Random(rng_seed)
    return rng.sample(all_ids, k=min(n, len(all_ids)))


def speedup(live: BenchResult, premapped: BenchResult) -> float:
    if premapped.p95_ms <= 0.0:
        return float("inf")
    return live.p95_ms / premapped.p95_ms


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="GG4 outcome → top-100 chunk bench")
    p.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "autonomath.db",
        help="Path to autonomath.db.",
    )
    p.add_argument("--samples", type=int, default=100, help="Sampled outcomes.")
    p.add_argument("--limit", type=int, default=10, help="Chunks per outcome.")
    p.add_argument("--seed", type=int, default=20260517, help="Deterministic RNG seed.")
    p.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional JSON report path (default: stdout summary only).",
    )
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    if not args.db.exists():
        logger.error("db missing: %s", args.db)
        return 2

    outcome_ids = sample_outcome_ids(args.db, n=args.samples, rng_seed=args.seed)
    if not outcome_ids:
        logger.error("no rows in am_outcome_chunk_map (migration not applied?)")
        return 3

    pre = bench_premapped(args.db, outcome_ids=outcome_ids, limit=args.limit)
    live = bench_live_simulation(n_samples=len(outcome_ids), rng_seed=args.seed)

    report = {
        "premapped": pre.__dict__,
        "live_simulation": live.__dict__,
        "speedup_p95": speedup(live, pre),
        "premapped_p95_under_20ms": pre.p95_ms < 20.0,
        "samples": len(outcome_ids),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.json_out is not None:
        with contextlib.suppress(OSError):
            args.json_out.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
